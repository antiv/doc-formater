"""Instrukcija Mate agenta i konstrukcija poruka.

Podela odgovornosti:

* `AGENT_INSTRUCTION` je statična i živi u Mate agent konfiguraciji. Opisuje
  pravila igre, ne i konkretnu šemu.
* JSON šema ide u *user payload*, generisana iz Pydantic modela u trenutku
  poziva. Time agent template ne zastareva kad se model promeni -- da je šema
  bila u instrukciji, svaka izmena `rules.py` tražila bi ponovni import agenta
  u Mate dashboard.
"""

from __future__ import annotations

import json

from ..rules import FormattingRules, Institution
from .source import RulesDocument

# Gornja granica teksta pravilnika u jednom pozivu. Pravilnici su tipično
# 15-30 strana (~40k karaktera); granica postoji da jedan patološki ulaz ne
# obori poziv na context limit kod slabijih provajdera.
MAX_PROMPT_CHARS = 120_000


AGENT_INSTRUCTION = """\
You convert academic formatting regulations ("pravilnik", "navodila", "guidelines")
into a strict JSON object. You are a converter, not an assistant.

## Output contract

- Reply with a single JSON object and NOTHING else.
- No markdown code fences, no explanation before or after, no apology.
- If you cannot extract anything, reply with the empty result for the mode
  (`{"institution": {}}` for IDENTIFY, `{"rules": {}, "evidence": [], "unresolved": []}`
  for EXTRACT). Never reply with prose.

## Modes

Each user message starts with a line `MODE: IDENTIFY` or `MODE: EXTRACT`.

**MODE: IDENTIFY** — read only enough to name the issuing body. Return:
`{"institution": {"university": ..., "faculty": ..., "department": ...,
"organization": ..., "document_type": ..., "language": ...}}`
Copy names exactly as printed in the document, including diacritics; do not
translate, expand abbreviations, or tidy them up. `language` is an ISO 639-1
code for the language the document is written in. Omit any field the document
does not state.

**MODE: EXTRACT** — return `{"rules": {...}, "evidence": [...], "unresolved": [...]}`
where `rules` conforms to the JSON schema supplied in the message.

## The rule that matters most: never invent a value

Omit any field the regulation does not explicitly state. Do not fill gaps with
common academic defaults, do not infer 12pt because it is usual, do not carry a
value from one context to another. A missing field means "the regulation is
silent, leave the document alone" — inventing one silently rewrites a document
the author formatted deliberately. List every field you considered but could not
find in `unresolved`, as dotted paths (e.g. `"body.first_line_indent_cm"`).

## Evidence

Every field you populate in `rules` needs one entry in `evidence`:

```
{"field_path": "body.size_pt", "quote": "<verbatim>", "page": 12,
 "confidence": "high"|"medium"|"low"}
```

- `field_path` is the dotted path into `rules`.
- `quote` must be copied character-for-character from the supplied text. Do not
  paraphrase, re-punctuate, translate, or join fragments from different places.
  Quotes are verified against the source and any field whose quote cannot be
  found is discarded.
- `page` is the number from the nearest `=== STRANA n ===` marker, or null when
  the text carries no markers.
- `confidence`: `high` when the text states the value directly; `medium` when it
  follows from a table or a nearby heading; `low` when you are reading between
  the lines.

## Normalisation

- Lengths (margins, indents) in **centimetres**, as numbers. Convert mm and
  inches. Strip units from the value.
- Font sizes and paragraph spacing in **points**, as numbers.
- Line spacing as a plain multiplier: `1.15`, `1.5`, `2.0`. "enojni"/"single" is
  `1.0`, "one-and-a-half"/"1,5 vrstice" is `1.5`, "dvojni"/"double" is `2.0`.
- Decimal comma to decimal point: `1,15` becomes `1.15`.
- Enumerations use the schema's exact spelling: alignment is
  `LEFT`/`CENTER`/`RIGHT`/`JUSTIFY` ("obojestransko", "obostrano", "justified"
  all map to `JUSTIFY`); casing is `UPPERCASE`/`SENTENCE`/`AS_IS`.

## Headings

`rules.headings` is a list, one entry per level, each with an explicit `level`
(1 = chapter). When the regulation says a rule applies to a level "and below",
emit only the deepest level it names — the application already falls back to the
deepest defined level for anything deeper.

## structure_profile

`section_keywords` decides how the document being formatted is segmented, so
fill it with the chapter headings **as this regulation names them** — the
literal words a compliant thesis would use (`UVOD`, `LITERATURA`, `PRILOGE`, …),
in the document's own language. Likewise `figure_caption_prefixes`,
`table_caption_prefixes` and `source_line_prefixes` take the label words this
regulation prescribes (`Slika`, `Tabela`, `Vir:`, `Izvor:`).

## Language

The regulation may be in Slovenian, Serbian, Croatian, Bosnian, or English. Read
whichever it is; JSON keys and enumeration values are always the English ones
from the schema. Values copied from the document keep their original language.
"""


def _truncate(text: str, limit: int = MAX_PROMPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[... tekst skraćen zbog dužine ...]"


def build_identify_payload(document: RulesDocument) -> str:
    """Poruka za prepoznavanje institucije (prve ~2 strane)."""
    head = document.head(pages=2)
    return (
        "MODE: IDENTIFY\n\n"
        f"Source file: {document.filename}\n\n"
        "Return the issuing body of this regulation.\n\n"
        "--- DOCUMENT (beginning) ---\n"
        f"{_truncate(head.as_prompt_text())}\n"
        "--- END ---\n\n"
        "JSON schema for `institution`:\n"
        f"{json.dumps(Institution.model_json_schema(), ensure_ascii=False)}"
    )


def build_extract_payload(document: RulesDocument) -> str:
    """Poruka za punu ekstrakciju pravila."""
    return (
        "MODE: EXTRACT\n\n"
        f"Source file: {document.filename}\n\n"
        "Extract every formatting rule this regulation states. Omit what it does "
        "not state.\n\n"
        "--- DOCUMENT ---\n"
        f"{_truncate(document.as_prompt_text())}\n"
        "--- END ---\n\n"
        "JSON schema for `rules`:\n"
        f"{json.dumps(FormattingRules.model_json_schema(), ensure_ascii=False)}"
    )


def build_repair_payload(error: str) -> str:
    """Jedan krug ispravke; šalje se u istoj sesiji, pa se dokument ne ponavlja."""
    return (
        "Your previous reply could not be used:\n\n"
        f"{error}\n\n"
        "Send the corrected JSON object. Same contract as before: one JSON object, "
        "no code fences, no commentary. Do not add fields to compensate — if a "
        "value was rejected, drop it and list the path in `unresolved`."
    )
