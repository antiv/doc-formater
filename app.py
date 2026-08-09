"""Streamlit UI za doc_formater.

Dve celine: formatiranje dokumenta i upravljanje bibliotekom pravila.

Korak pregleda pravila pre primene nije ukras -- ekstrakcija iz pravilnika je
najnepouzdaniji deo lanca, pa se svako pravilo prikazuje uz poreklo, pouzdanost
i citat iz izvora, i ništa se ne primenjuje dok korisnik ne potvrdi.
"""

from __future__ import annotations

import io
import tempfile
from contextlib import contextmanager
from pathlib import Path

import streamlit as st

from docformat import identity
from docformat.extract.mate_client import MateClient, MateConfig
from docformat.extract.pipeline import extract_rule_set, identify_institution
from docformat.extract.source import NoTextLayerError, read_rules_document
from docformat.formatting.engine import FormatOptions, format_document
from docformat.library import RuleLibrary, suggest_display_name
from docformat.rules import (
    Casing,
    Evidence,
    RuleSet,
    enum_type_for_path,
    iter_field_paths,
    load_rule_set,
    set_by_path,
)

PRESETS_DIR = Path(__file__).resolve().parent / "presets"

st.set_page_config(page_title="Doc Formatter", page_icon="📄", layout="wide")


# --------------------------------------------------------------------------
# Zajedničko
# --------------------------------------------------------------------------


@st.cache_resource
def get_library() -> RuleLibrary:
    return RuleLibrary()


def load_presets() -> list[RuleSet]:
    out: list[RuleSet] = []
    for path in sorted(PRESETS_DIR.glob("*.json")):
        try:
            out.append(load_rule_set(path))
        except Exception:
            continue
    return out


def mate_client() -> MateClient | None:
    config = MateConfig.from_env()
    return MateClient(config) if config.is_configured else None


@contextmanager
def temp_upload(uploaded):
    """Uploadovani fajl na disku samo dok traje obrada.

    Bitno na serveru: bez brisanja bi se tuđi pravilnici gomilali u /tmp i
    ostajali tamo neograničeno. Sam rad nikad ne dodiruje disk -- ide kroz
    `io.BytesIO`.
    """
    suffix = Path(uploaded.name).suffix
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(uploaded.getbuffer())
        handle.close()
        yield Path(handle.name)
    finally:
        Path(handle.name).unlink(missing_ok=True)


@st.cache_data(ttl=120, show_spinner=False)
def _mate_ping(base_url: str, agent: str, token_fingerprint: str) -> tuple[bool, str]:
    """Keširan ping.

    Bez keša bi se Mate zvao pri svakom preiscrtavanju strane, a Streamlit
    preiscrtava na svaki klik. Argumenti ulaze u ključ keša da bi izmena
    konfiguracije oborila keš; token se ne prosleđuje u čitavom obliku.
    """
    return MateClient(MateConfig.from_env()).ping()


def mate_status_banner() -> None:
    """Mate je opciona nadogradnja, ne zavisnost.

    Bez njega ekstrakcija radi na regex heuristici, pa odsustvo Mate-a nije
    greška i ne prikazuje se kao greška.
    """
    config = MateConfig.from_env()
    if not config.is_configured:
        st.sidebar.caption(
            "Ekstrakcija pravila: regex heuristika. Za bolje rezultate poveži "
            "LLM agenta (`MATE_BASE_URL`, `MATE_PAT`)."
        )
        return
    ok, message = _mate_ping(config.base_url, config.agent, (config.token or "")[-6:])
    (st.sidebar.success if ok else st.sidebar.warning)(message)


# --------------------------------------------------------------------------
# Editor pravila
# --------------------------------------------------------------------------

_CONFIDENCE_ICON = {"high": "🟢", "medium": "🟡", "low": "🔴"}
_SOURCE_LABEL = {
    "mate": "Mate agent",
    "heuristic": "heuristika",
    "manual": "ručno",
    "preset": "preset",
}



def _render_evidence(evidence: Evidence | None) -> str:
    if evidence is None:
        return ""
    icon = _CONFIDENCE_ICON.get(evidence.confidence, "")
    source = _SOURCE_LABEL.get(evidence.source, evidence.source)
    page = f", str. {evidence.page}" if evidence.page else ""
    quote = f" — „{evidence.quote}”" if evidence.quote else ""
    return f"{icon} {source}{page}{quote}"


def rules_editor(rule_set: RuleSet, key_prefix: str) -> RuleSet:
    """Editor svih skalarnih polja, grupisan po sekciji šeme."""
    unresolved = set(rule_set.unresolved)
    groups: dict[str, list[tuple[str, object]]] = {}
    for path, value in iter_field_paths(rule_set.rules):
        groups.setdefault(path.split(".", 1)[0], []).append((path, value))

    for group, fields in groups.items():
        filled = sum(1 for _, value in fields if value is not None)
        with st.expander(f"{group}  ({filled}/{len(fields)} popunjeno)", expanded=group == "body"):
            for path, value in fields:
                evidence = rule_set.evidence_for(path)
                columns = st.columns([3, 2, 5])

                label = path.split(".", 1)[1] if "." in path else path
                if path in unresolved:
                    label += "  ⚠️"
                columns[0].markdown(f"`{label}`")

                enum_type = enum_type_for_path(rule_set.rules, path)
                new_value = _render_input(
                    path, value, f"{key_prefix}:{path}", columns[1], enum_type
                )
                if new_value != value:
                    set_by_path(rule_set.rules, path, new_value)
                    rule_set.evidence = [e for e in rule_set.evidence if e.field_path != path]
                    if new_value is not None:
                        rule_set.evidence.append(
                            Evidence(field_path=path, confidence="high", source="manual")
                        )
                    rule_set.unresolved = [u for u in rule_set.unresolved if u != path]

                columns[2].caption(_render_evidence(evidence) or "—")

    _render_headings_editor(rule_set, key_prefix)
    _render_keywords_editor(rule_set, key_prefix)
    return rule_set


def _render_input(path: str, value, key: str, column, enum_type=None):
    """Widget koji ume da vrati `None` -- prazno polje znači 'ne diraj'."""
    if enum_type is not None:
        options = ["(ne diraj)"] + [member.value for member in enum_type]
        current = value.value if value is not None else "(ne diraj)"
        chosen = column.selectbox(
            path, options, index=options.index(current), key=key, label_visibility="collapsed"
        )
        return None if chosen == "(ne diraj)" else enum_type(chosen)

    if isinstance(value, bool) or path.endswith(
        ("bold", "italic", "mirror_margins", "different_first_page", "allow_italic",
         "allow_empty_paragraphs", "insert_field", "header_row_bold", "header_row_repeat",
         "page_break_before", "keep_with_next")
    ):
        options = ["(ne diraj)", "da", "ne"]
        current = "(ne diraj)" if value is None else ("da" if value else "ne")
        chosen = column.selectbox(
            path, options, index=options.index(current), key=key, label_visibility="collapsed"
        )
        return None if chosen == "(ne diraj)" else chosen == "da"

    if isinstance(value, (int, float)) or path.endswith(("_pt", "_cm", "spacing", "levels")):
        text = "" if value is None else str(value)
        entered = column.text_input(path, text, key=key, label_visibility="collapsed",
                                    placeholder="ne diraj")
        if not entered.strip():
            return None
        try:
            return float(entered.replace(",", "."))
        except ValueError:
            column.error("broj")
            return value

    if isinstance(value, list):
        entered = column.text_input(
            path, ", ".join(str(v) for v in value), key=key, label_visibility="collapsed"
        )
        return [part.strip() for part in entered.split(",") if part.strip()]

    text = "" if value is None else str(value)
    entered = column.text_input(path, text, key=key, label_visibility="collapsed",
                                placeholder="ne diraj")
    return entered.strip() or None


def _render_headings_editor(rule_set: RuleSet, key_prefix: str) -> None:
    with st.expander(f"headings  ({len(rule_set.rules.headings)} nivoa)"):
        if not rule_set.rules.headings:
            st.info("Nijedan nivo naslova nije definisan — naslovi se neće formatirati.")
        for heading in rule_set.rules.headings:
            columns = st.columns(6)
            columns[0].markdown(f"**nivo {heading.level}**")
            heading.size_pt = _float_input(columns[1], "pt", heading.size_pt, f"{key_prefix}:h{heading.level}:size")
            heading.bold = _bool_input(columns[2], "krepko", heading.bold, f"{key_prefix}:h{heading.level}:bold")
            heading.casing = _casing_input(columns[3], heading.casing, f"{key_prefix}:h{heading.level}:casing")
            heading.page_break_before = _bool_input(
                columns[4], "nova strana", heading.page_break_before, f"{key_prefix}:h{heading.level}:pb"
            )
            heading.keep_with_next = _bool_input(
                columns[5], "drži uz sledeći", heading.keep_with_next, f"{key_prefix}:h{heading.level}:kwn"
            )


def _render_keywords_editor(rule_set: RuleSet, key_prefix: str) -> None:
    keywords = rule_set.rules.structure_profile.section_keywords
    with st.expander("structure_profile — ključne reči sekcija"):
        st.caption(
            "Ovim se dokument deli na sekcije. Ako `body_start` ne pogodi naslov "
            "kojim rad počinje glavni deo, formatiranje staje sa greškom."
        )
        for field in ("front_matter", "body_start", "bibliography", "appendix"):
            current = getattr(keywords, field)
            entered = st.text_input(
                field, ", ".join(current), key=f"{key_prefix}:kw:{field}"
            )
            setattr(keywords, field, [p.strip() for p in entered.split(",") if p.strip()])


def _float_input(column, label, value, key):
    entered = column.text_input(label, "" if value is None else str(value), key=key)
    if not entered.strip():
        return None
    try:
        return float(entered.replace(",", "."))
    except ValueError:
        return value


def _bool_input(column, label, value, key):
    options = ["—", "da", "ne"]
    current = "—" if value is None else ("da" if value else "ne")
    chosen = column.selectbox(label, options, index=options.index(current), key=key)
    return None if chosen == "—" else chosen == "da"


def _casing_input(column, value, key):
    options = ["—"] + [member.value for member in Casing]
    current = value.value if value is not None else "—"
    chosen = column.selectbox("velika slova", options, index=options.index(current), key=key)
    return None if chosen == "—" else Casing(chosen)


# --------------------------------------------------------------------------
# Stranica: formatiranje
# --------------------------------------------------------------------------


def page_format(user) -> None:
    library = get_library()
    st.header("Formatiranje dokumenta")

    document_file = st.file_uploader("Rad (.docx)", type=["docx"], key="doc")

    st.subheader("Izvor pravila")
    presets = load_presets()
    saved = library.list()
    source = st.radio(
        "Odakle pravila",
        ["Uploaduj pravilnik", "Iz biblioteke", "Preset", "Uploaduj rules.json"],
        horizontal=True,
        label_visibility="collapsed",
    )

    rule_set: RuleSet | None = st.session_state.get("rule_set")

    if source == "Uploaduj pravilnik":
        rules_file = st.file_uploader("Pravilnik (.pdf ili .docx)", type=["pdf", "docx"], key="rules")
        if rules_file and st.button("Izvuci pravila", type="primary"):
            rule_set = _extract_flow(rules_file, library)
            st.session_state["rule_set"] = rule_set

    elif source == "Iz biblioteke":
        if not saved:
            st.info("Biblioteka je prazna. Izvuci pravila iz pravilnika pa ih sačuvaj.")
        else:
            chosen = st.selectbox(
                "Set", saved, format_func=lambda rs: f"{rs.meta.display_name}  ({rs.meta.id})"
            )
            if st.button("Učitaj", type="primary"):
                rule_set = library.load(chosen.meta.id)
                st.session_state["rule_set"] = rule_set

    elif source == "Preset":
        chosen = st.selectbox("Preset", presets, format_func=lambda rs: rs.meta.display_name)
        if st.button("Učitaj", type="primary"):
            rule_set = chosen.model_copy(deep=True)
            st.session_state["rule_set"] = rule_set

    else:
        json_file = st.file_uploader("rules.json", type=["json"], key="rules_json")
        if json_file and st.button("Učitaj", type="primary"):
            rule_set = RuleSet.model_validate_json(json_file.getvalue().decode("utf-8"))
            st.session_state["rule_set"] = rule_set

    if rule_set is None:
        return

    st.divider()
    st.subheader(f"Pravila: {rule_set.meta.display_name}")
    if rule_set.unresolved:
        st.warning(
            f"{len(rule_set.unresolved)} polja nije pronađeno u pravilniku "
            "(označena sa ⚠️). Dopuni ih ili ostavi prazna — prazno polje znači "
            "da se to svojstvo ne dira."
        )
    rule_set = rules_editor(rule_set, key_prefix="fmt")
    st.session_state["rule_set"] = rule_set

    _save_to_library_controls(rule_set, library, user)

    if document_file is None:
        st.info("Uploaduj .docx da bi formatiranje bilo moguće.")
        return

    st.divider()
    st.subheader("Primena")
    columns = st.columns(3)
    cleanup = columns[0].checkbox("Briši prazne pasuse", value=True)
    lenient = columns[1].checkbox("Nastavi i bez prepoznate strukture", value=False)
    toc_choice = columns[2].selectbox("TOC polje", ["po pravilima", "ubaci", "ne ubacuj"])

    options = FormatOptions(
        strict_structure=not lenient,
        clean_empty_paragraphs=cleanup,
        insert_toc={"po pravilima": None, "ubaci": True, "ne ubacuj": False}[toc_choice],
    )

    if st.button("Prikaži šta bi bilo obrisano", width='stretch'):
        _run_format(document_file, rule_set, FormatOptions(**{**options.__dict__, "dry_run": True}))

    if st.button("Formatiraj", type="primary", width='stretch'):
        _run_format(document_file, rule_set, options, offer_download=True)


def _extract_flow(rules_file, library: RuleLibrary) -> RuleSet | None:
    try:
        with temp_upload(rules_file) as path:
            document = read_rules_document(path)
    except NoTextLayerError as exc:
        st.error(str(exc))
        return None
    except ValueError as exc:
        st.error(str(exc))
        return None

    client = mate_client()

    with st.status("Prepoznajem instituciju…", expanded=True) as status:
        institution, origin = identify_institution(document, client)
        st.write(
            f"Institucija ({origin}): "
            f"{suggest_display_name(institution) or 'nije prepoznata'}"
        )

        matches = library.find_matches(institution)
        if matches and (matches[0].is_strong or matches[0].is_suggestion):
            best = matches[0]
            status.update(label="Pronađen sličan set u biblioteci", state="complete")
            st.session_state["pending_match"] = best.rule_set.meta.id
            st.info(
                f"U biblioteci postoji **{best.rule_set.meta.display_name}** "
                f"(poklapanje {best.score:.2f}). Možeš ga koristiti bez nove ekstrakcije."
            )

        status.update(label="Izvlačim pravila…", state="running")
        outcome = extract_rule_set(
            document, client=client, library=library, institution=institution,
            on_progress=lambda msg: st.write(msg),
        )
        status.update(label=f"Gotovo — izvor: {outcome.source}", state="complete")

    for warning in outcome.warnings:
        st.warning(warning)
    if outcome.rejected:
        st.error(
            "Odbačena pravila čiji citat ne postoji u pravilniku: "
            + ", ".join(outcome.rejected)
        )
    return outcome.rule_set


def _save_to_library_controls(rule_set: RuleSet, library: RuleLibrary, user) -> None:
    with st.expander("Sačuvaj u biblioteku"):
        if not identity.can_create(user):
            st.caption(
                "Čuvanje pravila traži prijavu — set mora nekome da pripada. "
                "Bez prijave ih možeš preuzeti kao JSON i kasnije uvesti."
            )
            st.download_button(
                "Preuzmi rules.json",
                rule_set.model_dump_json(indent=2),
                file_name=f"{rule_set.meta.id}.json",
                mime="application/json",
            )
            return

        # Postojeći tuđi set se ne prepisuje: snimanje pravi novi, u vlasništvu
        # onoga ko snima. Original ostaje netaknut.
        existing = library.load(rule_set.meta.id) if library.exists(rule_set.meta.id) else None
        overwriting = existing is not None and identity.can_edit(existing, user)
        if existing is not None and not overwriting:
            st.caption(
                f"„{existing.meta.display_name}” je tuđ set — snimanje pravi tvoju kopiju."
            )

        columns = st.columns([4, 1])
        name = columns[0].text_input("Naziv", rule_set.meta.display_name, key="save_name")
        if columns[1].button("Sačuvaj", width='stretch'):
            if name != rule_set.meta.display_name:
                rule_set.meta.display_name = name
            if not overwriting:
                rule_set.meta.id = library.unique_id(name)
            rule_set.meta.owner = user.email
            rule_set.meta.owner_name = user.name
            library.save(rule_set)
            st.success(f"Sačuvano: {rule_set.meta.id}")
        st.download_button(
            "Preuzmi rules.json",
            rule_set.model_dump_json(indent=2),
            file_name=f"{rule_set.meta.id}.json",
            mime="application/json",
        )


def _run_format(document_file, rule_set: RuleSet, options: FormatOptions, offer_download: bool = False) -> None:
    try:
        result = format_document(io.BytesIO(document_file.getbuffer()), rule_set, options)
    except Exception as exc:
        st.error(f"Formatiranje nije uspelo: {exc}")
        return

    report = result.report
    columns = st.columns(3)
    columns[0].metric("Stilske izmene", len(report.style_changes))
    columns[1].metric("Brisanja", len(report.deletions))
    columns[2].metric("Dodato", len(report.insertions))

    for warning in report.warnings:
        st.warning(warning)

    if report.style_changes:
        st.dataframe(
            [
                {
                    "uloga": s.role or "—",
                    "svojstvo": s.rule_path,
                    "broj": s.count,
                    "izmene": s.describe_transitions(),
                }
                for s in report.by_rule()
            ],
            width='stretch',
            hide_index=True,
        )

    if report.deletions:
        with st.expander(f"Brisanja ({len(report.deletions)})", expanded=options.dry_run):
            st.dataframe(
                [
                    {
                        "pasus": c.paragraph_index,
                        "sekcija": c.section,
                        "šta": c.detail,
                    }
                    for c in report.deletions
                ],
                width='stretch',
                hide_index=True,
            )

    if offer_download:
        name = Path(document_file.name).stem
        st.download_button(
            "Preuzmi formatiran .docx",
            result.to_bytes(),
            file_name=f"Formatiran_{name}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
            width='stretch',
        )


# --------------------------------------------------------------------------
# Stranica: biblioteka
# --------------------------------------------------------------------------


def page_library(user) -> None:
    library = get_library()
    st.header("Biblioteka pravila")

    if user is None:
        st.info(
            "Biblioteku možeš pregledati i koristiti bez prijave. Za čuvanje i "
            "menjanje pravila prijavi se — svaki set pripada onome ko ga je napravio."
        )
    elif user.is_admin:
        st.caption("Admin: možeš menjati i brisati sve setove.")

    sets = library.list()
    if not sets:
        st.info(
            "Biblioteka je prazna. Na stranici *Formatiranje* izvuci pravila iz "
            "pravilnika pa ih sačuvaj — sledeći rad sa istog fakulteta ih onda "
            "koristi bez nove ekstrakcije."
        )
    else:
        st.dataframe(
            [
                {
                    "naziv": rs.meta.display_name,
                    "vlasnik": rs.meta.owner_name or rs.meta.owner or "— (ugrađen)",
                    "univerzitet": rs.meta.institution.university or "—",
                    "fakultet": rs.meta.institution.faculty or "—",
                    "tip": rs.meta.institution.document_type or "—",
                    "izmenjeno": rs.meta.updated_at.strftime("%Y-%m-%d %H:%M"),
                }
                for rs in sets
            ],
            width='stretch',
            hide_index=True,
        )

        chosen = st.selectbox(
            "Set", sets, format_func=lambda rs: f"{rs.meta.display_name}  ({rs.meta.id})"
        )
        may_edit = identity.can_edit(chosen, user)
        st.caption(identity.describe_permission(chosen, user))

        columns = st.columns(4)
        if columns[0].button("Uredi", width='stretch', disabled=not may_edit):
            st.session_state["editing"] = chosen.meta.id
        # Kopiranje je namerno dozvoljeno svakome ko je prijavljen, i nad tuđim
        # setom: to je izlaz koji zabranu izmene čini neblokirajućom.
        if columns[1].button("Kopiraj", width='stretch', disabled=not identity.can_create(user)):
            copy = library.duplicate(chosen.meta.id)
            copy.meta.owner = user.email
            copy.meta.owner_name = user.name
            library.save(copy)
            st.success(f"Kopirano kao tvoj set: {copy.meta.id}")
            st.rerun()
        if columns[2].button("Obriši", width='stretch', disabled=not may_edit):
            library.delete(chosen.meta.id)
            st.session_state.pop("editing", None)
            st.rerun()
        columns[3].download_button(
            "Izvezi",
            chosen.model_dump_json(indent=2),
            file_name=f"{chosen.meta.id}.json",
            mime="application/json",
            width='stretch',
        )

        editing = st.session_state.get("editing")
        if editing and library.exists(editing):
            rule_set = library.load(editing)
            # Dozvola se proverava i ovde, ne samo na dugmetu: `editing` preživi
            # u sesiji, pa odjava ili izbor tuđeg seta ne sme da ostavi otvoren
            # editor sa aktivnim snimanjem.
            if not identity.can_edit(rule_set, user):
                st.session_state.pop("editing", None)
                st.rerun()

            st.divider()
            st.subheader(f"Uređivanje: {rule_set.meta.display_name}")

            institution = rule_set.meta.institution
            columns = st.columns(4)
            rule_set.meta.display_name = columns[0].text_input("Naziv", rule_set.meta.display_name)
            institution.university = columns[1].text_input("Univerzitet", institution.university or "") or None
            institution.faculty = columns[2].text_input("Fakultet", institution.faculty or "") or None
            institution.document_type = columns[3].text_input("Tip rada", institution.document_type or "") or None

            rule_set = rules_editor(rule_set, key_prefix=f"lib:{editing}")
            if st.button("Sačuvaj izmene", type="primary"):
                library.save(rule_set)
                st.success("Sačuvano.")
                st.rerun()

    st.divider()
    if identity.can_create(user):
        uploaded = st.file_uploader("Uvezi rules.json", type=["json"], key="import_json")
        if uploaded and st.button("Uvezi"):
            with temp_upload(uploaded) as path:
                imported = library.import_(path)
            # Uvezen set pripada onome ko ga je uveo, bez obzira na to čiji je
            # bio u fajlu -- inače bi uvoz mogao da podmetne tuđe vlasništvo.
            imported.meta.owner = user.email
            imported.meta.owner_name = user.name
            library.save(imported)
            st.success(f"Uvezeno: {imported.meta.id}")
            st.rerun()


# --------------------------------------------------------------------------


def main() -> None:
    if not identity.require_gate(st):
        return

    user = identity.current_user(st)

    st.sidebar.title("📄 Doc Formatter")
    identity.render_sidebar(st, user)
    st.sidebar.divider()
    mate_status_banner()
    page = st.sidebar.radio("Stranica", ["Formatiranje", "Biblioteka pravila"])
    st.sidebar.divider()
    st.sidebar.caption(
        "Tekst dokumenta se nikad ne prepisuje. Briše se samo prazan prostor, "
        "i to samo kad pravila to traže. Slike, tabele i grafikoni ostaju."
    )

    if page == "Formatiranje":
        page_format(user)
    else:
        page_library(user)


if __name__ == "__main__":
    main()
