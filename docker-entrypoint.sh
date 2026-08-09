#!/bin/sh
set -e

# Streamlit-ov OIDC se konfiguriše isključivo kroz `secrets.toml`, a Dokploy
# (kao i svaki drugi PaaS) konfiguriše kroz env promenljive. Ovaj skript
# premošćuje to: ako su Google OAuth promenljive prisutne, secrets.toml se
# generiše pri pokretanju. Ako nisu, aplikacija radi u lokalnom režimu bez
# prijave -- fajl se tada ne pravi, jer bi prazna `[auth]` sekcija oborila
# `st.login()`.

SECRETS_DIR="${HOME}/.streamlit"
SECRETS_FILE="${SECRETS_DIR}/secrets.toml"

if [ -n "${GOOGLE_CLIENT_ID}" ] && [ -n "${GOOGLE_CLIENT_SECRET}" ] && [ -n "${OIDC_REDIRECT_URI}" ]; then
    if [ -z "${OIDC_COOKIE_SECRET}" ]; then
        echo "GREŠKA: OIDC_COOKIE_SECRET nije postavljen." >&2
        echo "  Bez njega bi se kolačić sesije potpisivao nasumičnim ključem," >&2
        echo "  pa bi restart aplikacije odjavio sve korisnike." >&2
        echo "  Generiši ga sa: openssl rand -hex 32" >&2
        exit 1
    fi

    mkdir -p "${SECRETS_DIR}"
    cat > "${SECRETS_FILE}" <<EOF
[auth]
redirect_uri = "${OIDC_REDIRECT_URI}"
cookie_secret = "${OIDC_COOKIE_SECRET}"

[auth.google]
client_id = "${GOOGLE_CLIENT_ID}"
client_secret = "${GOOGLE_CLIENT_SECRET}"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
EOF
    chmod 600 "${SECRETS_FILE}"
    echo "Google prijava je podešena (redirect_uri: ${OIDC_REDIRECT_URI})."
else
    rm -f "${SECRETS_FILE}"
    echo "Google prijava nije podešena — aplikacija radi u lokalnom režimu."
fi

exec "$@"
