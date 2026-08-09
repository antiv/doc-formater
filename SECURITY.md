# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for a security vulnerability.**

Report it through
[GitHub's private vulnerability reporting](https://github.com/antiv/doc-formater/security/advisories/new),
which keeps the report private until a fix is available.

### What to include

- A description of the vulnerability
- Steps to reproduce
- The impact you believe it has
- A suggested fix, if you have one

### Response timeline

- **Acknowledgement**: within 48 hours
- **Initial assessment**: within one week
- **Fix**: depends on severity; typically within two weeks for anything critical

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.0.x   | Yes       |

## What this application handles

Understanding what data passes through it makes most of the guidance below
obvious.

- **The thesis never touches the disk.** It is read from the upload straight
  into `io.BytesIO`, formatted in memory, and returned as a download.
- **The style guide touches the disk briefly.** PDF parsing needs a real file,
  so it is written to a temporary file and deleted in a `finally` block. Without
  that deletion, other people's style guides would accumulate in `/tmp`
  indefinitely.
- **Only the style guide is ever sent to an LLM.** When Mate is configured, the
  text of the style guide leaves the machine so the rules can be extracted from
  it. The thesis does not — it is formatted entirely locally.
- **The only persistent state is the rule library**, in `RULES_LIBRARY_DIR`.
  Rule sets contain formatting rules and the name of the institution, not
  documents.

## Deploying it safely

**`OIDC_COOKIE_SECRET` must be secret and stable.** Streamlit signs the identity
cookie with it. If it changes between restarts every user is logged out; if it
leaks, identity cookies can be forged. The container refuses to start when OAuth
is configured without it, rather than falling back to a value that changes on
every restart.

**`ADMIN_EMAILS` grants the right to edit and delete other people's rule sets.**
Treat the list as a privilege grant, not a convenience.

**A rule set with no owner is administrator-only.** Bundled presets and anything
created before ownership existed fall in this group. If you change this, do not
treat an absent owner as "unclaimed" — that would let the first visitor delete
everyone's rules.

**`APP_PASSWORD` is an access gate, not an identity.** It answers "who may reach
this application", while Google sign-in answers "who are you". It is compared
with `hmac.compare_digest`, and it is off by default.

**`MATE_PAT` is a credential for an external service.** Pass it through the
environment; never bake it into the image or commit it. Mate is entirely
optional — with no token the application uses its regex heuristic and nothing
leaves the machine.

**Terminate TLS in front of the app.** Streamlit is meant to run behind a
reverse proxy (Traefik, nginx, Caddy). Sign-in over plain HTTP exposes the
identity cookie.

**Mount `RULES_LIBRARY_DIR` on a volume.** It is the only persistent state;
without a volume every redeploy wipes the library. The container runs as a
non-root user, so the volume must be writable by uid 10001.

## Scope

Formatting is deliberately open to anyone, including anonymous visitors — that
is a design decision, not an oversight. Reports that amount to "an anonymous
user can format a document" are working as intended. Reports that an anonymous
user can **modify or delete** a rule set they do not own are vulnerabilities,
and we want to hear about them.
