# Changelog

All notable changes to Doc Formatter will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-08-09

First release.

### Added

- **Formatting engine** — applies a rule set to a `.docx` under two invariants:
  no character of text is ever rewritten, and images, tables, charts, footnotes
  and links are never removed. `UPPERCASE` headings use Word's `w:caps` run
  property rather than `.upper()`, so the characters stay untouched.
- **Rule extraction from a style guide** (`.pdf` or `.docx`) through an LLM agent
  running on [Mate](https://github.com/antiv/mate), with a regex heuristic as
  fallback. Mate is optional; without `MATE_PAT` the heuristic runs and the
  sidebar says so as information, not as an error.
- **Hallucination guard** — every extracted rule must carry a verbatim quote
  from the style guide. A quote that cannot be found in the source nulls the
  field instead of applying it; a high word-overlap match applies with reduced
  confidence, which is what lets line-broken quotes from PDFs survive.
- **`None` means the style guide is silent** — every rule field is optional and
  every operation is a no-op for fields the guide never prescribed, so a
  document is only changed where a rule actually says so.
- **Three-layer heading detection** — Word's `w:outlineLvl`, then `style_id`
  (stable across localised Word), then manual numbering, with guards that keep
  numbered questionnaire items in appendices from becoming headings. Section
  transitions are monotonic, so "UVOD" inside the bibliography cannot send the
  document back to body text.
- **Controlled whitespace deletion** — the only destructive operation. It
  refuses to delete a paragraph holding a drawing, picture, object, footnote or
  endnote reference, field, bookmark or section properties; it runs only over
  body-level paragraphs and only when the rules ask for it.
- **Rule library** — extracted sets are saved, matched against a new style guide
  by university, faculty and department, and offered again when the same
  institution is recognised. Sets can be copied, edited, exported and deleted.
- **Ownership model** — formatting is open to anyone; a rule set can be edited
  only by its owner, or by an administrator. Sign-in is Google OIDC through
  Streamlit; when OIDC is not configured the app runs in local admin mode.
- **Change report** — every operation reports what it changed, with deletions
  listed separately because they are the only irreversible edit.
- **Command line** (`cli.py`) — format, extract, and manage the library without
  the web interface, including `--dry-run`.
- **Translated interface** — English (default), Serbian, French and German. The
  active language is a `ContextVar`, so one visitor's choice cannot leak into
  another's page. First visit is negotiated from `Accept-Language`.
- **Deployment** — Docker image and a Dokploy-oriented compose file; the
  entrypoint renders Streamlit's `secrets.toml` from environment variables and
  removes it when OAuth is unconfigured.
- **Continuous integration** — tests on Python 3.11 and 3.12, plus a Docker
  image build whose smoke step reads from inside the built image.

### Security

- A rule set whose `owner` is `None` is **administrator-only**, not
  unclaimed. Bundled presets and anything created before ownership existed fall
  in this group; treating them as free-for-all would let the first visitor
  delete everyone's rules.
- `OIDC_COOKIE_SECRET` is required whenever OAuth is configured — the container
  refuses to start without it rather than signing identity cookies with a value
  that changes on every restart.

[Unreleased]: https://github.com/antiv/doc-formater/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/antiv/doc-formater/releases/tag/v1.0.0
