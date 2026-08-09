"""Identitet i dozvole.

Model pristupa ima tri nivoa i namerno je asimetričan -- formatiranje je
otvoreno, a vlasništvo nad pravilima traži identitet:

| ko                | formatira | čita biblioteku | menja svoja | menja tuđa |
|-------------------|-----------|-----------------|-------------|------------|
| anoniman posetilac| da        | da              | ne          | ne         |
| prijavljen        | da        | da              | da          | ne         |
| admin             | da        | da              | da          | da         |

Prijava ide preko Google-a, Streamlit-ovim ugrađenim OIDC-om (`st.login`).
Aplikacija time ne čuva nijednu lozinku niti sesiju: identitet stoji u
potpisanom kolačiću koji preživljava osvežavanje strane.

Ko ne može da menja tuđ set pravila, uvek može da ga **kopira** -- kopija
postaje njegova. To je izlaz koji čini zabranu neblokirajućom.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from .i18n import t

APP_PASSWORD_ENV = "APP_PASSWORD"
ADMIN_EMAILS_ENV = "ADMIN_EMAILS"

_GATE_KEY = "_gate_ok"

# Vlasnik koji se dodeljuje kad OIDC nije podešen (lokalni rad).
LOCAL_OWNER = "local"


@dataclass(frozen=True)
class User:
    email: str
    name: str
    is_admin: bool
    is_local: bool = False

    @property
    def label(self) -> str:
        return self.name or self.email


# --------------------------------------------------------------------------
# Konfiguracija
# --------------------------------------------------------------------------


def admin_emails() -> set[str]:
    raw = os.getenv(ADMIN_EMAILS_ENV, "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def app_password() -> str | None:
    value = os.getenv(APP_PASSWORD_ENV, "").strip()
    return value or None


def gate_is_open() -> bool:
    """Bez `APP_PASSWORD` do aplikacije može svako ko zna adresu."""
    return app_password() is None


def check_password(candidate: str, expected: str | None) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(candidate.strip(), expected)


def oidc_configured(st) -> bool:
    """Da li je Google prijava uopšte podešena.

    Bez `[auth]` sekcije u `secrets.toml` `st.login()` baca, pa se aplikacija
    vraća u lokalni režim umesto da pukne.
    """
    try:
        return "auth" in st.secrets
    except Exception:
        return False


# --------------------------------------------------------------------------
# Ko je na vezi
# --------------------------------------------------------------------------


def current_user(st) -> User | None:
    """Prijavljeni korisnik, ili None za anonimnog posetioca.

    Kad OIDC nije podešen, vraća lokalnog administratora: bez toga bi na
    razvojnoj mašini biblioteka bila nedodirljiva, jer prijava ne postoji.
    """
    if not oidc_configured(st):
        return User(email=LOCAL_OWNER, name=t("auth.local_user"), is_admin=True, is_local=True)

    try:
        if not st.user.is_logged_in:
            return None
        email = (st.user.email or "").strip()
        name = (getattr(st.user, "name", "") or "").strip()
    except Exception:
        return None

    if not email:
        return None
    return User(email=email, name=name or email, is_admin=email.lower() in admin_emails())


# --------------------------------------------------------------------------
# Dozvole
# --------------------------------------------------------------------------


def can_edit(rule_set, user: User | None) -> bool:
    """Da li `user` sme da menja ili obriše dati set pravila.

    Set bez vlasnika (ugrađeni preset, ili set nastao pre uvođenja vlasništva)
    pripada aplikaciji, pa ga menja samo admin -- inače bi ga prvi prijavljeni
    posetilac mogao obrisati svima.
    """
    if user is None:
        return False
    if user.is_admin:
        return True
    owner = getattr(rule_set.meta, "owner", None)
    if not owner:
        return False
    return owner.lower() == user.email.lower()


def can_create(user: User | None) -> bool:
    """Snimanje novog seta traži identitet -- inače nema čemu da pripadne."""
    return user is not None


def describe_permission(rule_set, user: User | None) -> str:
    if user is None:
        return t("auth.perm.sign_in")
    if can_edit(rule_set, user):
        return t("auth.perm.admin") if user.is_admin else t("auth.perm.yours")
    owner = getattr(rule_set.meta, "owner", None)
    whose = t("auth.perm.owner", owner=owner) if owner else t("auth.perm.builtin")
    return t("auth.perm.copy_hint", whose=whose)


# --------------------------------------------------------------------------
# Streamlit sloj
# --------------------------------------------------------------------------


def require_gate(st) -> bool:
    """Opciona zajednička lozinka za pristup aplikaciji.

    Odvojeno pitanje od prijave: ovo je „ko sme do aplikacije", a Google
    prijava je „ko si ti". Podrazumevano je isključeno.
    """
    if gate_is_open() or st.session_state.get(_GATE_KEY):
        return True

    st.title(f"📄 {t('app.title')}")
    st.caption(t("auth.gate_caption"))
    with st.form("gate"):
        entered = st.text_input(t("auth.password"), type="password")
        if st.form_submit_button(t("auth.enter"), type="primary"):
            if check_password(entered, app_password()):
                st.session_state[_GATE_KEY] = True
                st.rerun()
            else:
                st.error(t("auth.wrong_password"))
    return False


def render_sidebar(st, user: User | None) -> None:
    """Prijava/odjava i ko je trenutno na vezi."""
    if not oidc_configured(st):
        st.sidebar.caption(t("auth.local_mode"))
        return

    if user is None:
        st.sidebar.info(t("auth.sign_in_hint"))
        if st.sidebar.button(t("auth.sign_in_google"), type="primary", width="stretch"):
            st.login("google")
        return

    badge = t("auth.admin_badge") if user.is_admin else ""
    st.sidebar.success(f"{user.label}{badge}")
    if st.sidebar.button(t("auth.sign_out"), width="stretch"):
        st.logout()
