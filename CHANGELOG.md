# Changelog

All notable changes to StyleGuard will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Renamed from Doc Formatter to StyleGuard**, repository `doc-formater` to
  `styleguard`, and the Python package `docformat` to `styleguard`. The old name
  was generic enough to be unsearchable next to the several existing products
  called some variation of "AI document formatter", said nothing about academic
  style guides, and the repository spelled it `formater` with one `t` while the
  application spelled it with two. GitHub redirects the old repository URL, so
  existing links and clones keep working.

### Removed

- `fix_document.py`, the original single-purpose script, and `ameu_rules.json`,
  the file it read. Nothing imported either one, `presets/ameu.json` supersedes
  the rules file, and `tests/compare_with_legacy.py` compares against a
  pre-generated document rather than the script. Keeping it was actively
  misleading: the script rewrites text with `.upper()` and `re.sub`, which
  [CONTRIBUTING.md](CONTRIBUTING.md) forbids, and `ameu_rules.json` declared ten
  sections of which the script ever read two. Both remain available at
  `git show v1.0.0:fix_document.py`.

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

[Unreleased]: https://github.com/antiv/styleguard/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/antiv/styleguard/releases/tag/v1.0.0
