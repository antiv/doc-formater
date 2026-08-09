# Contributing to Doc Formatter

Thank you for considering a contribution. This document covers the things you
cannot infer from reading the code — the rest is ordinary Python.

Read the two invariants first. They are the reason most of this codebase looks
the way it does, and a change that breaks one of them will be rejected no matter
how good it otherwise is.

## The two invariants

**1. No character of text is ever rewritten.**

The application changes how a document looks, never what it says. That means no
`re.sub` over content, no `.upper()`, no renaming, and in particular no
`paragraph.text = ...` — assigning to it destroys every run, and with them the
formatting, hyperlinks and footnote references the paragraph carried.

The `UPPERCASE` casing rule is implemented with Word's `w:caps` run property,
which renders text in capitals without touching a single character. If you find
yourself reaching for `.upper()`, that is the pattern to copy.

**2. Images, tables, charts, footnotes and links are never removed.**

Only whitespace may be deleted, and only when the rules ask for it.
[docformat/formatting/ops/cleanup.py](docformat/formatting/ops/cleanup.py) is
the only destructive code in the project and it refuses to delete a paragraph
containing `w:drawing`, `w:pict`, `w:object`, `mc:AlternateContent`, a
footnote/endnote/comment reference, a field, a bookmark or `w:sectPr`.

Note the trap it exists to avoid: `paragraph.text` concatenates only `w:t`
nodes, so a paragraph holding nothing but an image reports `""`. Testing
emptiness with `paragraph.text` deletes every figure in the document. Use
`analyze.has_embedded_content`.

Both invariants are measured by
[tests/test_invariants.py](tests/test_invariants.py): the text of non-empty
paragraphs must stay identical character for character, and the census of
images, tables, footnotes and links must not change.

## Rules that are easy to break by accident

**`None` is not `0`.** Every field in
[docformat/rules.py](docformat/rules.py) is optional and defaults to `None`,
meaning "the style guide is silent about this — do not touch it". Every
operation must be a no-op for such a field. A "sensible default" silently
rewrites a document that its author formatted deliberately, which is the exact
failure this design exists to prevent.

**Formatting must be idempotent.** A second pass over an already formatted
document produces no changes. `IdempotencyTest` enforces it; the usual cause of
a failure is comparing values of different types (an alignment enum against its
name, a length against a raw integer).

**Every operation reports what it changed.** The signature is
`apply(document, infos, rules) -> list[Change]`. The report is the only way a
user can verify a hundred-page result, so an unreported change is a bug even
when the edit itself is correct.

## Language conventions

These are unusual, and they are the most common reason a first contribution
fails CI:

- **Comments and docstrings are in Serbian.**
- **Code identifiers are in English.**
- **Every user-facing string is a catalogue key**, resolved through `t()` from
  [docformat/i18n.py](docformat/i18n.py) — never a literal. A test fails the
  build if a non-English literal reappears in a user-facing module.

Adding a language means adding `locales/<code>.json` and an entry in
`LANGUAGE_NAMES`; no code change. `en.json` is the source of truth, and
[tests/test_i18n.py](tests/test_i18n.py) enforces catalogue parity, including
that no translation drops or invents a `{placeholder}` — a dropped placeholder
renders an unformatted string silently, which is worse than an exception.

## Development setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## Running the tests

```bash
.venv/bin/python -m unittest discover -t . -s tests -p 'test_*.py'
```

**`-t .` is not optional.** The test package uses relative imports; without it
every module fails to import.

A single module:

```bash
.venv/bin/python -m unittest tests.test_invariants -v
```

Some tests need a real thesis and skip without one, because documents are not
part of this repository. To run them, point at your own file:

```bash
SAMPLE_DOCX=my-thesis.docx .venv/bin/python -m unittest discover -t . -s tests -p 'test_*.py'
```

Everything those tests cover is also covered by the synthetic document in
[tests/fixtures.py](tests/fixtures.py), which exists because a real thesis does
not hit every case — the sample has no tables and no footnotes.

## Things that are not committed

- **Documents.** `*.docx` and `*.pdf` are in `.gitignore`. A working directory
  holds other people's theses, which are personal data; they must never reach a
  commit, a fixture or a screenshot.
- **Secrets.** `.env` and `.streamlit/secrets.toml` are ignored. The container
  renders `secrets.toml` from environment variables at startup.

## Generated artefacts

Regenerate these, do not hand-edit them:

```bash
.venv/bin/python docs/make_icon.py           # assets/ from the SVG master
.venv/bin/python docs/make_screenshots.py    # README images (needs playwright)
.venv/bin/python mate_agent/build_agent.py   # agent JSON after prompt edits
```

The agent instruction lives in
[docformat/extract/prompt.py](docformat/extract/prompt.py) and is copied into
the JSON template by the build script — one source, no drift.

## The Dockerfile is part of the change

Anything the application reads at runtime must be added to the `COPY` list in
the [Dockerfile](Dockerfile). This is not theoretical: `locales/` was once
missing from that list, and every string in a container fell back to a bare key
while development was perfect. The `image` job in CI now asserts the catalogues,
presets and icon are actually inside the built image.

## Submitting a change

1. Open an issue first for anything larger than a fix — the invariants constrain
   the design more than is obvious, and it is better to find that out before you
   write the code.
2. Keep the commit history readable. A commit message should say why, not what;
   the diff already says what.
3. Make sure `unittest discover -t . -s tests` passes and CI is green.
4. If the change is user-visible, add an entry under `[Unreleased]` in
   [CHANGELOG.md](CHANGELOG.md).

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## Licence

By contributing you agree that your contribution is licensed under the MIT
licence, the same as the rest of the project.
