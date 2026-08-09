"""Formatiranje pasusa po ulozi: naslovi, telo teksta, natpisi, literatura.

Sve uloge dele isti obrazac -- pročitaj pravilo za ulogu, primeni ga na pasus i
na sve njegove run-ove (uključujući hyperlink run-ove) -- pa žive u jednom
modulu umesto u pet gotovo identičnih.
"""

from __future__ import annotations

from docx.document import Document as DocxDocument

from ...analyze.structure import ParagraphInfo, Role, Section
from ...report import Change
from ...rules import CaptionRule, FormattingRules
from ..runs import apply_paragraph_format, apply_run_format, caps_for, is_link_run


def _context(info: ParagraphInfo) -> dict:
    return {
        "paragraph_index": info.index,
        "section": info.section.value,
        "role": info.role.value,
    }


def _style_runs(
    info: ParagraphInfo,
    rules: FormattingRules,
    *,
    size_pt: float | None,
    bold: bool | None,
    italic: bool | None,
    caps: bool | None,
) -> list[Change]:
    """Font na sve run-ove pasusa.

    Kurziv se ne dira na run-ovima sa URL-om ili DOI-jem: zabrana kurziva u
    telu teksta je pravilo o prozi, a ne o bibliografskim linkovima koji su
    kurzivni po citatnom stilu.
    """
    from ..runs import iter_runs

    changes: list[Change] = []
    ctx = _context(info)
    font_name = rules.typography.font_family

    for run in iter_runs(info.paragraph):
        run_italic = italic
        if run_italic is False and is_link_run(run):
            run_italic = None
        changes.extend(
            apply_run_format(
                run,
                font_name=font_name,
                size_pt=size_pt,
                bold=bold,
                italic=run_italic,
                caps=caps,
                context=ctx,
            )
        )
    return changes


# --------------------------------------------------------------------------
# Naslovi
# --------------------------------------------------------------------------


def apply_headings(document: DocxDocument, infos: list[ParagraphInfo], rules: FormattingRules) -> list[Change]:
    changes: list[Change] = []

    for info in infos:
        if info.role is not Role.HEADING or info.heading_level is None:
            continue
        # Naslov literature ima svoje pravilo (`bibliography.*`).
        if info.section is Section.BIBLIOGRAPHY:
            continue

        rule = rules.heading(info.heading_level)
        if rule is None:
            continue

        changes.extend(
            apply_paragraph_format(
                info.paragraph,
                alignment=rule.alignment,
                space_before_pt=rule.space_before_pt,
                space_after_pt=rule.space_after_pt,
                line_spacing=rules.body.line_spacing,
                page_break_before=rule.page_break_before,
                keep_with_next=rule.keep_with_next,
                context=_context(info),
            )
        )
        changes.extend(
            _style_runs(
                info,
                rules,
                size_pt=rule.size_pt,
                bold=rule.bold,
                italic=rule.italic,
                caps=caps_for(rule.casing),
            )
        )

    return changes


# --------------------------------------------------------------------------
# Telo teksta
# --------------------------------------------------------------------------


def apply_body(document: DocxDocument, infos: list[ParagraphInfo], rules: FormattingRules) -> list[Change]:
    body = rules.body
    changes: list[Change] = []

    for info in infos:
        if info.role is not Role.BODY_TEXT:
            continue

        italic = False if body.allow_italic is False else None

        if info.section is Section.COVER:
            # Naslovnica je jedino mesto gde raspored nije predmet pravila o
            # telu teksta: centriranje i ručni razmaci tamo su namerni, pa se
            # dira samo pismo, ne i raspored.
            changes.extend(
                _style_runs(info, rules, size_pt=None, bold=None, italic=italic, caps=None)
            )
            continue

        # Razmak između pasusa je pravilo o prozi. U prilozima (anketni
        # upitnici, obrasci, izjave) pasus je stavka spiska, pa bi 12pt posle
        # svakog ponuđenog odgovora naduvalo upitnik na više strana. Pismo,
        # veličina, prored i poravnanje se primenjuju i tamo.
        in_appendix = info.section is Section.APPENDIX

        changes.extend(
            apply_paragraph_format(
                info.paragraph,
                alignment=body.alignment,
                line_spacing=body.line_spacing,
                space_before_pt=None if in_appendix else body.space_before_pt,
                space_after_pt=None if in_appendix else body.space_after_pt,
                first_line_indent_cm=None if in_appendix else body.first_line_indent_cm,
                context=_context(info),
            )
        )
        changes.extend(
            _style_runs(info, rules, size_pt=body.size_pt, bold=None, italic=italic, caps=None)
        )

    return changes


# --------------------------------------------------------------------------
# Natpisi slika i tabela, red sa izvorom
# --------------------------------------------------------------------------

_CAPTION_ROLES = {
    Role.FIGURE_CAPTION: "figure",
    Role.TABLE_CAPTION: "table",
    Role.SOURCE_LINE: "source_line",
}


def apply_captions(document: DocxDocument, infos: list[ParagraphInfo], rules: FormattingRules) -> list[Change]:
    changes: list[Change] = []

    for info in infos:
        attribute = _CAPTION_ROLES.get(info.role)
        if attribute is None:
            continue
        rule: CaptionRule = getattr(rules.captions, attribute)

        changes.extend(
            apply_paragraph_format(
                info.paragraph,
                alignment=rule.alignment,
                line_spacing=rules.body.line_spacing,
                space_before_pt=rule.space_before_pt,
                space_after_pt=rule.space_after_pt,
                keep_with_next=rule.keep_with_next,
                context=_context(info),
            )
        )
        changes.extend(
            _style_runs(info, rules, size_pt=rule.size_pt, bold=rule.bold, italic=rule.italic, caps=None)
        )

    return changes


# --------------------------------------------------------------------------
# Literatura
# --------------------------------------------------------------------------


def apply_bibliography(document: DocxDocument, infos: list[ParagraphInfo], rules: FormattingRules) -> list[Change]:
    biblio = rules.bibliography
    changes: list[Change] = []

    for info in infos:
        if info.section is not Section.BIBLIOGRAPHY:
            continue

        if info.role is Role.HEADING:
            rule = rules.heading(1)
            if rule is not None:
                changes.extend(
                    apply_paragraph_format(
                        info.paragraph,
                        alignment=rule.alignment,
                        space_before_pt=rule.space_before_pt,
                        space_after_pt=rule.space_after_pt,
                        line_spacing=rules.body.line_spacing,
                        page_break_before=(
                            biblio.page_break_before
                            if biblio.page_break_before is not None
                            else rule.page_break_before
                        ),
                        keep_with_next=rule.keep_with_next,
                        context=_context(info),
                    )
                )
                changes.extend(
                    _style_runs(
                        info, rules,
                        size_pt=rule.size_pt, bold=rule.bold, italic=rule.italic,
                        caps=caps_for(rule.casing),
                    )
                )
            continue

        if info.role is not Role.BIBLIOGRAPHY_ENTRY:
            continue

        changes.extend(
            apply_paragraph_format(
                info.paragraph,
                alignment=biblio.alignment,
                line_spacing=biblio.line_spacing,
                space_before_pt=biblio.space_before_pt,
                space_after_pt=biblio.space_after_pt,
                hanging_indent_cm=biblio.hanging_indent_cm,
                context=_context(info),
            )
        )
        changes.extend(
            _style_runs(info, rules, size_pt=biblio.size_pt, bold=None, italic=None, caps=None)
        )

    return changes
