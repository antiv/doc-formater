"""Ubacivanje pravog Word TOC polja.

Jedina operacija koja dodaje sadržaj, pa je podrazumevano isključena
(`toc.insert_field`).

Ubacuje se `w:fldSimple` sa `TOC` instrukcijom, a ne ispisana lista naslova:
polje Word sam popuni i održava, dok je ispisana lista mrtav tekst koji
zastari čim se dokument izmeni. Uz to se u `settings.xml` postavlja
`w:updateFields`, pa Word pri otvaranju ponudi osvežavanje.
"""

from __future__ import annotations

from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from ...analyze.structure import ParagraphInfo, Role, Section
from ...report import Change
from ...rules import FormattingRules
from ..runs import apply_paragraph_format, apply_run_format, caps_for


def _has_toc_field(document: DocxDocument) -> bool:
    for element in document.element.body.iter():
        if element.tag == qn("w:fldSimple"):
            instruction = element.get(qn("w:instr")) or ""
            if "TOC" in instruction.upper():
                return True
        if element.tag == qn("w:instrText") and "TOC" in (element.text or "").upper():
            return True
    return False


def _set_update_fields(document: DocxDocument) -> None:
    settings = document.settings.element
    if settings.find(qn("w:updateFields")) is not None:
        return
    element = settings.makeelement(qn("w:updateFields"), {qn("w:val"): "true"})
    settings.append(element)


def _insert_toc_field(anchor: Paragraph, levels: int) -> Paragraph:
    paragraph = anchor.insert_paragraph_before("")
    fld = paragraph._p.makeelement(
        qn("w:fldSimple"),
        {qn("w:instr"): f'TOC \\o "1-{levels}" \\h \\z \\u'},
    )
    # Word traži bar jedan run unutar polja kao rezervisano mesto do osvežavanja.
    run = paragraph._p.makeelement(qn("w:r"), {})
    text = paragraph._p.makeelement(qn("w:t"), {})
    text.text = "Sadržaj se osvežava u Word-u (Ctrl+A pa F9)."
    run.append(text)
    fld.append(run)
    paragraph._p.append(fld)
    return paragraph


def apply(document: DocxDocument, infos: list[ParagraphInfo], rules: FormattingRules) -> list[Change]:
    config = rules.toc
    if config.insert_field is not True:
        return []
    if _has_toc_field(document):
        return []

    anchor = next(
        (i for i in infos if i.section is Section.BODY and i.role is Role.HEADING),
        None,
    )
    if anchor is None:
        return []

    changes: list[Change] = []
    levels = config.levels or 3

    field_paragraph = _insert_toc_field(anchor.paragraph, levels)
    changes.append(
        Change(kind="insert", rule_path="toc.insert_field",
               detail=f'TOC polje (nivoi 1-{levels}) pre "{anchor.text[:40]}"')
    )

    if config.title:
        title = field_paragraph.insert_paragraph_before(config.title)
        rule = rules.heading(1)
        if rule is not None:
            apply_paragraph_format(
                title,
                alignment=rule.alignment,
                space_before_pt=rule.space_before_pt,
                space_after_pt=rule.space_after_pt,
                page_break_before=rule.page_break_before,
            )
            for run in title.runs:
                apply_run_format(
                    run,
                    font_name=rules.typography.font_family,
                    size_pt=rule.size_pt,
                    bold=rule.bold,
                    caps=caps_for(rule.casing),
                )
        changes.append(
            Change(kind="insert", rule_path="toc.title", detail=f'naslov "{config.title}"')
        )

    _set_update_fields(document)
    return changes
