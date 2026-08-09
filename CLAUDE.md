# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Streamlit app + CLI that formats a `.docx` academic thesis according to an
institution's style guide. The user uploads the thesis and the style guide
(`.pdf` or `.docx`); a **Mate agent** (`bt/adk/mate`) extracts the rules, with a
regex heuristic as fallback. Extracted rule sets are saved to a library and
re-offered when the same institution is recognised.

`fix_document.py` is the original single-purpose script, kept as reference. It
is not imported by anything.

## Commands

```bash
.venv/bin/streamlit run app.py
.venv/bin/python cli.py format --input rad.docx --rules-id ameu --out out.docx
.venv/bin/python cli.py --help

.venv/bin/python -m unittest discover -t . -s tests -p 'test_*.py'   # -t . is required
.venv/bin/python -m unittest tests.test_invariants -v                # single module
.venv/bin/python tests/compare_with_legacy.py                        # diff vs old script

.venv/bin/python mate_agent/build_agent.py    # regenerate agent JSON after prompt edits
.venv/bin/python docs/make_icon.py            # regenerate assets/ from the SVG master
.venv/bin/python docs/make_screenshots.py     # regenerate README images (needs playwright)
```

Python 3.11 venv at `.venv`. `-t .` on `unittest discover` is not optional — the
test package uses relative imports and without it every module fails to import.

CI is [.github/workflows/ci.yml](.github/workflows/ci.yml). Anything the app
reads at runtime must be added to the `COPY` list in the `Dockerfile` — the
image job asserts the catalogues, presets and icon are actually inside the
built image, because a missing `COPY` breaks only production and passes every
local test.

## The two invariants that drive the whole design

Everything in `docformat/formatting/` follows from these, and
[tests/test_invariants.py](tests/test_invariants.py) measures them:

1. **No character of text is ever rewritten.** No `re.sub` over content, no
   `.upper()`, no renaming. The `UPPERCASE` casing rule is implemented with
   Word's `w:caps` run property, which renders uppercase without touching the
   characters. If you are about to write `paragraph.text = ...`, stop.
2. **Images, tables, charts, footnotes and links are never removed.** Only
   whitespace may be deleted, and only when the rules ask for it.

## Architecture

### `None` means "the style guide is silent — don't touch this"

Every field in [docformat/rules.py](docformat/rules.py) is `Optional` and
defaults to `None`. `None` and `0` are different: the engine may only change
properties the style guide explicitly prescribes. Every op is a no-op for
fields that are `None`. Preserve this when adding rules — a "sensible default"
silently rewrites a document the author formatted deliberately.

### Three-layer heading detection

[docformat/analyze/structure.py](docformat/analyze/structure.py) resolves
heading level from, in order: Word's `w:outlineLvl` → `style.style_id`
(`"Heading1"` is stable across localised Word; `style.name` is `"Naslov 1"` in
Slovenian) → manual numbering.

The numbering layer is the weakest and carries guards: a numbered paragraph
longer than 120 chars or ending in sentence punctuation is not a heading.
Without them, questionnaire items in appendices (`1. Koliko časova…?`) become
level-1 headings and get 14pt bold with a page break. All three layers stay
active — a document that mostly uses Heading styles still has the occasional
chapter the author never styled.

A paragraph matching a `section_keywords` entry is treated as a level-1 heading
even without style or numbering; that is how `ZAHVALNICA` / `ABSTRACT` get
heading treatment.

Section transitions are **monotonic** (`COVER → FRONT_MATTER → BODY →
BIBLIOGRAPHY → APPENDIX`), so the word "UVOD" appearing inside the bibliography
cannot send the document back to body text.

### python-docx traps, all handled in `formatting/runs.py`

- `paragraph.runs` **excludes** runs inside `w:hyperlink`. Use `iter_runs()`.
  The sample thesis has 25 such runs; the old script left every bibliography
  link in the wrong font.
- `run.font.name` sets only `w:ascii` and `w:hAnsi`. `set_complex_script_font`
  adds `w:cs`, which is what Cyrillic actually reads.
- `paragraph.text` concatenates only `w:t` nodes, so a paragraph holding an
  image reports `""`. `analyze.has_embedded_content` is the real emptiness
  check — see the cleanup section below.
- Some documents write fractional twips into `w:pgMar`, which python-docx
  raises on when *reading*. `page_setup._read_cm` swallows that.

### Deletion is the only destructive operation

[docformat/formatting/ops/cleanup.py](docformat/formatting/ops/cleanup.py)
refuses to delete a paragraph that contains `w:drawing`, `w:pict`, `w:object`,
`mc:AlternateContent`, footnote/endnote/comment references, fields, bookmarks,
or `w:sectPr`. It runs only over body-level paragraphs (never inside `w:tc`),
only in `BODY` and `BIBLIOGRAPHY` (cover pages and appendices lay themselves
out with blank lines), and only when `body.allow_empty_paragraphs is False`.

Manual page breaks are removed only when the rules own pagination themselves
(some heading has `page_break_before`) — otherwise a manual break carries intent
we have nothing to replace it with.

### Mate integration

Mate exposes agents on `POST /v1/chat/completions` (`server/openai_routes.py`),
authenticated with `Authorization: Bearer <PAT>`. Two behaviours of that route
shape [docformat/extract/mate_client.py](docformat/extract/mate_client.py):

- **The route is text-only.** `extract_content_text` drops non-text blocks and
  the ADK message is built as `[{"text": ...}]`, so a PDF cannot be attached.
  Text is extracted locally in `extract/source.py` — which the regex fallback
  needs anyway, so one extraction path serves both.
- **`session_id` is derived from an md5 of the *first* message.** `MateSession`
  therefore keeps the first message fixed and appends only the latest one; the
  repair round lands in the same server-side session without resending the
  document. A content hash is prepended so different documents never collide.

Verified against a running Mate instance; four things bite in practice:

- `POST /dashboard/api/agents/import` takes `overwrite` as a **query param**.
  In the body it is ignored and the import silently skips an existing agent.
- **Import does not carry `expose_as_model`.** Set it afterwards via
  `PUT /dashboard/api/agents/{id}/expose` or the route 404s.
- There are **two different role checks**. `pat_auth.get_allowed_roles()` gates
  the `/v1` API (`admin`/`developer` by default); the agent's own
  `allowed_for_roles` gates that agent. If the caller's role is missing from
  the latter, the API returns **HTTP 200 with empty content and 0 tokens** —
  the only trace is `RBAC: Access DENIED` in the server log. The template ships
  `["admin","developer","user"]` because plain accounts carry `user`.
- `auth_server.py` spawns the agent runtime with a bare `"python"`
  (`server_control_service.py:174`), so Mate must be started with the venv
  **activated**; running `.venv/bin/python auth_server.py` without activation
  gives the subprocess the wrong interpreter.

The agent instruction lives in
[docformat/extract/prompt.py](docformat/extract/prompt.py) and is copied into
the JSON template by `mate_agent/build_agent.py` — one source, no drift. The
rules JSON schema deliberately does **not** go into the agent; it is generated
from the Pydantic model into every request payload, so editing `rules.py` never
requires re-importing the agent.

### Hallucination guard

Every extracted rule must carry a verbatim quote from the style guide.
`pipeline.apply_quote_verification` normalises whitespace and checks the quote
against the source: exact substring passes, a high word-overlap match passes
with reduced confidence, and anything below that **nulls the field** and reports
it. This is why line-broken quotes from PDFs survive while invented ones do not.

## Access model

[docformat/identity.py](docformat/identity.py). Formatting is open to anyone;
identity exists only so a rule set can have an owner. Anonymous → format and
read. Logged in (Google, via Streamlit's built-in OIDC) → owns what they save.
`ADMIN_EMAILS` → may edit and delete anything.

Three things are deliberate and easy to break:

- **A set with `owner = None` is admin-only**, not free-for-all. Bundled presets
  and anything created before ownership existed fall here; treating `None` as
  "unclaimed" would let the first visitor delete everyone's rules.
- **Copy is always available to a logged-in user, including on someone else's
  set** — that is what makes the edit ban non-blocking. Never gate copy behind
  `can_edit`.
- **Permission is re-checked when the editor renders**, not only on the button.
  `editing` survives in `st.session_state`, so logging out or switching sets
  must not leave a live editor over a set the user can no longer write.

When OIDC is not configured, `current_user()` returns a local admin — otherwise
a dev machine would have an untouchable library. Streamlit writes identity into
a signed cookie, so login survives a page refresh; `OIDC_COOKIE_SECRET` must be
stable across restarts or everyone is logged out.

## Deployment

Streamlit's OIDC reads `secrets.toml` only, while PaaS config is env vars —
[docker-entrypoint.sh](docker-entrypoint.sh) renders one from the other at
startup and deletes it when OAuth is unconfigured (an empty `[auth]` section
breaks `st.login()`).

`RULES_LIBRARY_DIR` points at the mounted volume. It is the only persistent
state; without the volume every redeploy wipes the library.

Mate is optional. Unset `MATE_PAT` → regex heuristic, and the sidebar says so
as information, not as an error. `_mate_ping` is cached (Streamlit reruns the
whole script on every interaction, so an uncached ping would hammer Mate).

## Translations

Everything a user reads goes through `t()` in
[docformat/i18n.py](docformat/i18n.py); catalogues are JSON in `locales/`, with
`en.json` as the source of truth. Three things are deliberate:

- **The active language is a `ContextVar`, not a module global.** Streamlit runs
  each browser session's script in its own thread, so a global would let one
  visitor's language leak into another's page.
- **A missing key falls back to English, then to the key itself** — a
  half-finished translation shows a bare key rather than crashing the page.
- **`tests/test_i18n.py` enforces catalogue parity**, including that no
  translation drops or invents a `{placeholder}`. A dropped placeholder would
  silently produce an unformatted string.

Adding a language is adding a file plus an entry in `LANGUAGE_NAMES`.

## Conventions

- Comments and docstrings are in Serbian; code identifiers are English; every
  user-facing string is a catalogue key, never a literal.
- Ops signature is `apply(document, infos, rules) -> list[Change]`. Report every
  change; the report is the only way a user can verify a 100-page result.
- Formatting must be idempotent — a second pass over an already-formatted
  document produces no changes. `IdempotencyTest` enforces this.
