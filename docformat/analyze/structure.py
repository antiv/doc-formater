"""Detekcija naslova, uloga pasusa i sekcija dokumenta.

Ovo je mesto na kome je originalna skripta bila najkrhkija: sekcije je
prepoznavala poređenjem doslovnog teksta, u dva duplirana prolaza, pa je
drugačije formulisan naslov tiho ostavljao state machine u prethodnoj sekciji
i pogrešno formatirao sve nizvodno.

Ovde detekcija ide u tri sloja (Word outline -> numeracija -> ključne reči),
računa se jednom, i prelazi između sekcija su monotoni -- pomen reči "UVOD" u
literaturi ne može da vrati dokument u telo teksta.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from ..i18n import t
from ..rules import FormattingRules


class Section(str, Enum):
    COVER = "COVER"
    FRONT_MATTER = "FRONT_MATTER"
    BODY = "BODY"
    BIBLIOGRAPHY = "BIBLIOGRAPHY"
    APPENDIX = "APPENDIX"


# Sekcije teku samo unapred; indeks sprečava da usputni pomen ključne reči
# vrati klasifikaciju unazad.
_SECTION_ORDER = {
    Section.COVER: 0,
    Section.FRONT_MATTER: 1,
    Section.BODY: 2,
    Section.BIBLIOGRAPHY: 3,
    Section.APPENDIX: 4,
}


class Role(str, Enum):
    EMPTY = "EMPTY"
    HEADING = "HEADING"
    FIGURE_CAPTION = "FIGURE_CAPTION"
    TABLE_CAPTION = "TABLE_CAPTION"
    SOURCE_LINE = "SOURCE_LINE"
    BODY_TEXT = "BODY_TEXT"
    BIBLIOGRAPHY_ENTRY = "BIBLIOGRAPHY_ENTRY"


@dataclass
class ParagraphInfo:
    index: int
    paragraph: Paragraph
    text: str
    section: Section
    role: Role
    heading_level: int | None = None
    has_content: bool = False  # slika/tabela/polje -- pasus nije zaista prazan


class StructureError(RuntimeError):
    """Struktura nije prepoznata; bolje stati nego tiho pogrešno formatirati."""


# --------------------------------------------------------------------------
# Normalizacija i poređenje naslova
# --------------------------------------------------------------------------


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    ascii_only = ascii_only.replace("đ", "dj").replace("Đ", "DJ")
    return re.sub(r"\s+", " ", ascii_only).strip().lower()


_NUMBER_PREFIX = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")


def strip_numbering(text: str) -> str:
    return _NUMBER_PREFIX.sub("", text).strip()


def matches_keyword(text: str, keywords: list[str]) -> bool:
    """Da li naslov odgovara nekoj ključnoj reči, bez obzira na numeraciju.

    Poredi se i sa i bez vodeće numeracije, jer pravilnici pišu "LITERATURA",
    a dokumenti "5 LITERATURA I IZVORI".
    """
    if not keywords:
        return False
    folded = _fold(strip_numbering(text))
    if not folded:
        return False
    for keyword in keywords:
        target = _fold(strip_numbering(keyword))
        if not target:
            continue
        if folded == target or folded.startswith(target + " ") or folded.startswith(target):
            return True
    return False


# --------------------------------------------------------------------------
# Sloj 1-3: nivo naslova
# --------------------------------------------------------------------------


def outline_level(paragraph: Paragraph) -> int | None:
    """Word-ov sopstveni outline nivo (`w:outlineLvl`), 1-baziran."""
    p_pr = paragraph._p.pPr
    if p_pr is None:
        return None
    element = p_pr.find(qn("w:outlineLvl"))
    if element is None:
        return None
    value = element.get(qn("w:val"))
    try:
        level = int(value)
    except (TypeError, ValueError):
        return None
    return level + 1 if 0 <= level <= 8 else None


def style_level(paragraph: Paragraph) -> int | None:
    """Nivo iz stila.

    Gleda se `style_id`, ne `style.name`: `style_id` ostaje "Heading1" i u
    lokalizovanom Word-u, dok je ime na slovenačkom "Naslov 1", na nemačkom
    "Überschrift 1" -- poređenje po imenu ne prelazi jezičku granicu.
    """
    try:
        style = paragraph.style
    except Exception:
        return None
    if style is None:
        return None

    style_id = style.style_id or ""
    match = re.fullmatch(r"Heading(\d)", style_id)
    if match:
        return int(match.group(1))

    name = style.name or ""
    match = re.fullmatch(r"(?:Heading|Naslov|Überschrift|Titre)\s*(\d)", name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


# Naslov po numeraciji ne sme biti dug kao rečenica ni završen interpunkcijom
# koja završava rečenicu -- inače numerisane stavke ankete ("1. Koliko časova
# nedeljno …?") prolaze kao poglavlja i dobiju 14pt bold sa prelomom strane.
_MAX_HEADING_CHARS = 120
_SENTENCE_END = re.compile(r"[.?!,;:]$")


def numbering_level(text: str) -> int | None:
    """Nivo iz ručne numeracije: `2.1.3 Naslov` -> 3.

    Najslabiji od tri sloja, pa nosi i najviše provera.
    """
    match = re.match(r"^\s*(\d+(?:\.\d+)*)\.?\s+\S", text)
    if not match:
        return None
    if len(text) > _MAX_HEADING_CHARS:
        return None
    if _SENTENCE_END.search(text.rstrip()):
        return None
    return match.group(1).count(".") + 1


def uses_word_outline(document: DocxDocument, threshold: int = 3) -> bool:
    """Da li dokument koristi Word heading stilove / outline nivoe.

    Dijagnostika za izveštaj i poruku o grešci: dokument bez ijednog heading
    stila oslanja se isključivo na numeraciju, pa je detekcija utoliko slabija
    i korisnik to treba da zna.
    """
    found = 0
    for paragraph in iter_body_paragraphs(document):
        if outline_level(paragraph) is not None or style_level(paragraph) is not None:
            found += 1
            if found >= threshold:
                return True
    return False


def detect_heading_level(paragraph: Paragraph, text: str) -> int | None:
    """Nivo naslova iz najpouzdanijeg raspoloživog signala.

    Slojevi se ne isključuju međusobno: dokument koji uglavnom koristi Word
    heading stilove i dalje ume da ima poglavlje kome stil nije dodeljen, pa
    numeracija ostaje uključena -- od lažnih pogodaka je čuvaju guard-ovi u
    `numbering_level`.
    """
    level = outline_level(paragraph)
    if level is not None:
        return level
    level = style_level(paragraph)
    if level is not None:
        return level
    return numbering_level(text)


# --------------------------------------------------------------------------
# Sadržaj pasusa
# --------------------------------------------------------------------------

# Elementi koji čine pasus "nepraznim" i onda kad `paragraph.text` vrati "".
# `paragraph.text` konkatenira isključivo `w:t` čvorove, pa pasus sa slikom
# izgleda prazan -- brisanje po tom uslovu uništava figure.
_CONTENT_TAGS = (
    "w:drawing",
    "w:pict",
    "w:object",
    "w:footnoteReference",
    "w:endnoteReference",
    "w:commentReference",
    "w:fldSimple",
    "w:instrText",
    "w:bookmarkStart",
    "w:hyperlink",
    "w:sdt",
)

_MC_ALTERNATE = "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"


def has_embedded_content(paragraph: Paragraph) -> bool:
    element = paragraph._p
    for tag in _CONTENT_TAGS:
        if element.find(f".//{qn(tag)}") is not None:
            return True
    return element.find(f".//{_MC_ALTERNATE}") is not None


def has_page_break(paragraph: Paragraph) -> bool:
    for br in paragraph._p.iter(qn("w:br")):
        if br.get(qn("w:type")) == "page":
            return True
    return False


# --------------------------------------------------------------------------
# Glavni prolaz
# --------------------------------------------------------------------------


def iter_body_paragraphs(document: DocxDocument) -> Iterator[Paragraph]:
    """Pasusi na nivou tela dokumenta, bez sadržaja tabela.

    Tabele imaju svoju operaciju formatiranja; mešanje njihovih pasusa u glavni
    tok pokvarilo bi i klasifikaciju sekcija i brojanje indeksa.
    """
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)


def _classify_role(
    text: str,
    section: Section,
    heading_level: int | None,
    profile,
    has_content: bool,
) -> Role:
    if heading_level is not None:
        return Role.HEADING
    if not text:
        return Role.EMPTY if not has_content else Role.BODY_TEXT

    for prefix in profile.source_line_prefixes:
        if text.lower().startswith(prefix.lower()):
            return Role.SOURCE_LINE
    for prefix in profile.figure_caption_prefixes:
        if re.match(rf"^{re.escape(prefix)}\s*\d", text, re.IGNORECASE):
            return Role.FIGURE_CAPTION
    for prefix in profile.table_caption_prefixes:
        if re.match(rf"^{re.escape(prefix)}\s*\d", text, re.IGNORECASE):
            return Role.TABLE_CAPTION

    if section is Section.BIBLIOGRAPHY:
        return Role.BIBLIOGRAPHY_ENTRY
    return Role.BODY_TEXT


def analyze(
    document: DocxDocument,
    rules: FormattingRules,
    strict: bool = True,
) -> list[ParagraphInfo]:
    """Jedan prolaz kroz telo dokumenta -> lista `ParagraphInfo`."""
    profile = rules.structure_profile
    keywords = profile.section_keywords

    section = Section.COVER
    infos: list[ParagraphInfo] = []
    body_found = False

    for index, paragraph in enumerate(iter_body_paragraphs(document)):
        text = paragraph.text.strip()
        heading_level = detect_heading_level(paragraph, text) if text else None
        has_content = has_embedded_content(paragraph)

        # Prelaz sekcije se razmatra samo na naslovima nivoa 1 i na pasusima
        # koji doslovno pogađaju ključnu reč -- ne na svakom pasusu.
        if text and (heading_level == 1 or heading_level is None):
            target = _section_for(text, keywords)
            if target is not None:
                # Pasus koji imenuje sekciju jeste naslov poglavlja, i onda kad
                # mu autor nije dodelio Word stil ni numeraciju. Bez ovoga
                # "ZAHVALNICA" i "ABSTRACT" prolaze kao obično telo teksta i
                # dobiju veličinu tela umesto naslovne.
                if heading_level is None:
                    heading_level = 1
                if _SECTION_ORDER[target] > _SECTION_ORDER[section]:
                    section = target
                    if target is Section.BODY:
                        body_found = True

        role = _classify_role(text, section, heading_level, profile, has_content)

        infos.append(
            ParagraphInfo(
                index=index,
                paragraph=paragraph,
                text=text,
                section=section,
                role=role,
                heading_level=heading_level,
                has_content=has_content,
            )
        )

    if strict and not body_found and keywords.body_start:
        hint = t(
            "structure.hint_outline"
            if uses_word_outline(document)
            else "structure.hint_no_outline"
        )
        raise StructureError(
            t(
                "structure.body_not_found",
                keywords=", ".join(keywords.body_start),
                hint=hint,
            )
        )

    return infos


def _section_for(text: str, keywords) -> Section | None:
    # Redosled provere prati redosled u dokumentu; prilozi se proveravaju pre
    # literature jer "IZJAVA" i "PRILOG" dolaze na kraju.
    if matches_keyword(text, keywords.appendix):
        return Section.APPENDIX
    if matches_keyword(text, keywords.bibliography):
        return Section.BIBLIOGRAPHY
    if matches_keyword(text, keywords.body_start):
        return Section.BODY
    if matches_keyword(text, keywords.front_matter):
        return Section.FRONT_MATTER
    return None


def missing_sections(infos: list[ParagraphInfo], rules: FormattingRules) -> list[Section]:
    """Sekcije za koje pravila imaju ključne reči, a u dokumentu nisu nađene.

    Nastaje redovno i bez ičije greške: pravilnik propisuje "PRILOGE", a autor
    napiše "PRILOG A". Posledica nije bezazlena -- nenađena sekcija znači da je
    njen sadržaj pripisan prethodnoj, pa se na njega primenjuju tuđa pravila.
    """
    keywords = rules.structure_profile.section_keywords
    configured = {
        Section.FRONT_MATTER: keywords.front_matter,
        Section.BODY: keywords.body_start,
        Section.BIBLIOGRAPHY: keywords.bibliography,
        Section.APPENDIX: keywords.appendix,
    }
    reached = {info.section for info in infos}
    return [section for section, words in configured.items() if words and section not in reached]


def summarize(infos: list[ParagraphInfo]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for info in infos:
        key = f"{info.section.value}/{info.role.value}"
        counts[key] = counts.get(key, 0) + 1
    return counts
