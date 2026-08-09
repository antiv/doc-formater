"""Brisanje suvišnog praznog prostora.

Jedina nepovratna operacija u celoj aplikaciji, pa su granice eksplicitne:

* Briše se **samo** pasus koji je stvarno prazan. `paragraph.text` konkatenira
  isključivo `w:t` čvorove, pa vraća `""` i za pasus koji sadrži sliku,
  grafikon, fusnotu ili polje -- brisanje po tom uslovu uništava figure.
* Pasus koji nosi `w:sectPr` se nikad ne briše: u njemu žive margine,
  orijentacija i numeracija cele sekcije.
* Tabele se ne diraju -- operacija radi nad pasusima na nivou tela dokumenta,
  nikad nad sadržajem ćelija.
* Prelom strane se uklanja tek kad pravila propisuju sopstvenu paginaciju
  naslova; inače ručni prelom nosi autorovu nameru koju nemamo čime zameniti.
"""

from __future__ import annotations

from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from ...analyze.structure import (
    ParagraphInfo,
    Role,
    Section,
    has_page_break,
    missing_sections,
)
from ...i18n import t
from ...report import Change
from ...rules import FormattingRules

# Prazni pasusi se brišu samo tamo gde pravilo o razmaku između pasusa uopšte
# važi. Naslovnica i prilozi (izjave, obrasci, anketni upitnici) drže raspored
# ručno postavljenim praznim redovima i njihovo brisanje razbija stranu.
_CLEANUP_SECTIONS = {Section.BODY, Section.BIBLIOGRAPHY}


def carries_section_properties(paragraph: Paragraph) -> bool:
    """Pasus u kome je smešten `w:sectPr` (prelom sekcije)."""
    p_pr = paragraph._p.pPr
    return p_pr is not None and p_pr.find(qn("w:sectPr")) is not None


def is_safe_to_delete(info: ParagraphInfo) -> tuple[bool, str]:
    """(sme li da se obriše, razlog kad ne sme)."""
    if info.text:
        return False, t("cleanup.reason.has_text")
    if info.has_content:
        return False, t("cleanup.reason.has_content")
    if carries_section_properties(info.paragraph):
        return False, t("cleanup.reason.section_properties")
    return True, ""


def remove_paragraph(paragraph: Paragraph) -> None:
    element = paragraph._p
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _rules_control_pagination(rules: FormattingRules) -> bool:
    """Da li pravila sama propisuju gde počinje nova strana."""
    return any(h.page_break_before for h in rules.headings) or bool(
        rules.bibliography.page_break_before
    )


def apply(
    document: DocxDocument,
    infos: list[ParagraphInfo],
    rules: FormattingRules,
    dry_run: bool = False,
) -> list[Change]:
    if rules.body.allow_empty_paragraphs is not False:
        return []

    # Ako pravila poznaju priloge a u dokumentu nisu prepoznati, kraj dokumenta
    # nije pouzdano razgraničen: prilozi su tada pripisani literaturi, pa bi se
    # brisanje proširilo na prazne redove koji drže raspored obrazaca i
    # anketnih upitnika. Brisanje se u tom slučaju ograničava na telo teksta.
    sections = set(_CLEANUP_SECTIONS)
    if Section.APPENDIX in missing_sections(infos, rules):
        sections.discard(Section.BIBLIOGRAPHY)

    changes: list[Change] = []
    pagination_owned = _rules_control_pagination(rules)
    last_index = infos[-1].index if infos else -1

    for info in infos:
        if info.role is not Role.EMPTY:
            continue
        if info.section not in sections:
            continue
        # Poslednji pasus u telu se ostavlja: Word očekuje da telo dokumenta ne
        # završi neposredno pred `w:sectPr`.
        if info.index == last_index:
            continue

        safe, reason = is_safe_to_delete(info)
        if not safe:
            continue

        carries_break = has_page_break(info.paragraph)
        if carries_break and not pagination_owned:
            # Bez pravila o prelomu pre naslova nemamo čime da zamenimo ručni
            # prelom, pa ga ostavljamo.
            continue

        detail = t(
            "cleanup.empty_paragraph_with_break"
            if carries_break
            else "cleanup.empty_paragraph"
        )
        rule_path = (
            "cleanup.page_break" if carries_break else "cleanup.empty_paragraph"
        )

        if not dry_run:
            remove_paragraph(info.paragraph)

        changes.append(
            Change(
                kind="delete",
                rule_path=rule_path,
                paragraph_index=info.index,
                section=info.section.value,
                role=info.role.value,
                detail=detail,
            )
        )

    return changes


def preview(document: DocxDocument, infos: list[ParagraphInfo], rules: FormattingRules) -> list[Change]:
    """Šta bi bilo obrisano, bez izmene dokumenta."""
    return apply(document, infos, rules, dry_run=True)
