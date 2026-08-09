# Setting up Google sign-in

How to create an OAuth client in the Google Cloud Console and connect it to Doc
Formatter.

**Why you might not need this:** formatting documents works without signing in.
A Google account is required only so that someone can **save rules** to the
library — a rule set has to belong to someone before it can be decided who may
change it. If you do not need the library, skip this entirely.

---

## Before you start

- A Google account.
- The address the app will run on. In production this must be an **HTTPS**
  domain (Dokploy provides one through Traefik). For local testing
  `http://localhost:8501` is fine.

No Google API needs enabling. Sign-in uses only the standard OpenID Connect
claims (`openid`, `email`, `profile`), which do not require activating a
service — if you find a guide telling you to enable the "Google People API", it
is describing a different use case.

---

## 1. Project

1. Open [console.cloud.google.com](https://console.cloud.google.com/).
2. Project picker in the top left → **New Project**.
3. Name it something like `styleguard`. Leave the organisation alone if you
   do not have one.
4. Wait for it to be created and **select it** in the picker.

Everything below happens inside that project — check the top left to be sure
the right one is selected.

---

## 2. Consent screen

In the left menu: **APIs & Services → OAuth consent screen**.

> Google has renamed this area to **Google Auth Platform**, with tabs
> *Overview*, *Branding*, *Audience*, *Clients* and *Data Access*. If that is
> what you see, the steps are the same — the consent screen is now *Branding*
> and the user type is *Audience*.

1. **User type:**
   - **Internal** — only accounts in your Google Workspace organisation. Choose
     this if you have Workspace and want sign-in limited to it. No verification
     and no cap on users.
   - **External** — any Google account. Choose this if you have no Workspace.
2. **App name** — e.g. `StyleGuard`. This is what users see when signing in.
3. **User support email** — yours.
4. **Developer contact information** — yours.
5. **Scopes** — add none. `openid`, `email` and `profile` are implicit and are
   not sensitive.
6. Save.

### If you chose External: publish the app

A new app sits in **Testing**, which means only accounts you list explicitly as
test users can sign in (100 maximum).

For real use, hit **Publish app** under *Overview* / *Publishing status*.

Because you are only using non-sensitive scopes, **no verification is
required** — publishing takes effect immediately. Google's verification warning
applies to apps requesting access to Gmail, Drive and similar.

While the status is *Testing*, anyone not on the list gets
`Access blocked: <app> has not completed the Google verification process`.

---

## 3. OAuth client

**APIs & Services → Credentials → Create Credentials → OAuth client ID**.

1. **Application type: Web application**.
2. **Name** — e.g. `styleguard-web` (internal only; users never see it).
3. **Authorized JavaScript origins** — leave empty; not needed.
4. **Authorized redirect URIs** → **Add URI**. This is the app's address plus
   the path `/oauth2callback`:

   | where | value |
   |---|---|
   | local | `http://localhost:8501/oauth2callback` |
   | production | `https://formatter.your-domain.com/oauth2callback` |

   You can add both and use one client for local development and the server.

5. **Create**.
6. The **Client ID** and **Client secret** are shown. Copy both now — the
   secret can later only be reset, never read again.

### The URI has to match exactly

Google compares the redirect URI **literally**. These are all different values
and none of them are interchangeable:

```
https://formatter.example.com/oauth2callback     ✅ what the app uses
https://formatter.example.com/oauth2callback/    ❌ trailing slash
http://formatter.example.com/oauth2callback      ❌ http instead of https
https://www.formatter.example.com/oauth2callback ❌ different host
https://formatter.example.com/callback           ❌ different path
```

The `/oauth2callback` path is not arbitrary — Streamlit's built-in OIDC expects
it and it cannot be changed.

---

## 4. Connecting it to the app

### On a server (Dokploy)

Under **Environment**:

```bash
GOOGLE_CLIENT_ID=1234...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
OIDC_REDIRECT_URI=https://formatter.your-domain.com/oauth2callback
OIDC_COOKIE_SECRET=<openssl rand -hex 32>
ADMIN_EMAILS=you@example.com
```

`OIDC_REDIRECT_URI` must be **character for character** what you entered in
step 3.

`OIDC_COOKIE_SECRET` signs the session cookie. Generate it once:

```bash
openssl rand -hex 32
```

It must stay **the same across restarts** — changing it signs everyone out. The
app refuses to start if OAuth is configured without it.

`ADMIN_EMAILS` is a comma-separated list of addresses allowed to edit and
delete **other people's** rules. Everyone else edits only their own.

You do not write any of this into a file — `docker-entrypoint.sh` generates
`secrets.toml` from these variables when the container starts, and that file is
the only place Streamlit reads OIDC configuration from.

### Locally

Create `.streamlit/secrets.toml` following
[`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example):

```toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "..."

[auth.google]
client_id = "...apps.googleusercontent.com"
client_secret = "GOCSPX-..."
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

That file is in `.gitignore` and must not be committed.

You do not need to configure an admin locally: without `secrets.toml` the app
runs in local mode where everything is permitted.

---

## 5. Checking it works

1. Open the app. The sidebar should offer **"Prijavi se preko Google-a"**
   (sign in with Google).
   - If it says *"Lokalni režim — prijava nije podešena"* (local mode) instead,
     `secrets.toml` was not created: check that all four variables are set and
     read the container log from startup.
2. Click it → Google account chooser → back to the app.
3. The sidebar should show your name; if your address is in `ADMIN_EMAILS`,
   `· admin` appears next to it.
4. Go to **Biblioteka pravila** (rule library) and confirm the *Uredi* (edit)
   and *Obriši* (delete) buttons are active on your own set.
5. Refresh the page — you should stay signed in, since identity lives in a
   cookie.

---

## Who can sign in

With **External** and a published app, **anyone with a Google account** can
sign in. For this app that is mostly harmless — a signed-in user can create
their own rules, but cannot touch anyone else's and cannot see anyone's
documents (documents are never stored at all).

If you do want to narrow it:

- **You have Google Workspace** → choose **Internal** in step 2. Sign-in is
  then limited to your organisation with no code involved.
- **You do not have Workspace** → the app would need an allowlist of addresses
  or domains. That does not exist yet; open an issue if you want
  `ALLOWED_EMAIL_DOMAINS`.
- **Temporarily** → leave the app in *Testing* and add the permitted accounts
  as test users (up to 100).

Independently of all this, `APP_PASSWORD` closes the entire app behind a shared
password, formatting included.

---

## Errors and their causes

| Message | Cause |
|---|---|
| `Error 400: redirect_uri_mismatch` | `OIDC_REDIRECT_URI` does not match the Console. Compare character by character — usually a trailing slash, `http` instead of `https`, or a missing `www.` |
| `Access blocked: ... has not completed the Google verification process` | The app is in *Testing* and the account is not a listed test user. Publish it, or add the account |
| `Error 401: invalid_client` | Wrong `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET`, or the secret was reset and the old value no longer works |
| Sidebar says local mode although the variables are set | One of the four is empty. The container log at startup names which |
| Container exits immediately with `OIDC_COOKIE_SECRET nije postavljen` | OAuth is configured without a signing key. Generate one with `openssl rand -hex 32` |
| Everyone is signed out after a redeploy | `OIDC_COOKIE_SECRET` changed. Set it as a fixed value in the Dokploy environment; do not generate it per deploy |
| Sign-in succeeds and immediately drops back to signed out | The proxy is not forwarding cookies or `Upgrade` headers. Traefik in Dokploy does both by default |

---

## If the domain changes

1. Add the new redirect URI to the OAuth client (keep the old one until you
   have switched over).
2. Change `OIDC_REDIRECT_URI` in the Dokploy environment.
3. Redeploy.

Leave `OIDC_COOKIE_SECRET` alone — changing it signs everyone out for no
reason.
