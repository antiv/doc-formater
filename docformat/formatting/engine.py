"""Orkestracija formatiranja.

Redosled operacija nije proizvoljan: čišćenje ide poslednje, nad strukturom
koja je već analizirana, da brisanje pasusa ne pomeri indekse pod nogama
operacijama koje još rade.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import docx
from docx.document import Document as DocxDocument

from ..analyze.structure import (
    ParagraphInfo,
    Section,
    StructureError,
    analyze,
    missing_sections,
    summarize,
)
from ..report import Report
from ..rules import FormattingRules, RuleSet
from .ops import cleanup, page_setup, paragraphs, tables, toc


@dataclass
class FormatOptions:
    dry_run: bool = False
    strict_structure: bool = True
    clean_empty_paragraphs: bool = True
    insert_toc: bool | None = None  # None = poštuj pravila


@dataclass
class FormatResult:
    document: DocxDocument
    report: Report
    structure: list[ParagraphInfo]

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        self.document.save(str(path))
        return path

    def to_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self.document.save(buffer)
        return buffer.getvalue()


def format_document(
    source: str | Path | io.IOBase,
    rule_set: RuleSet | FormattingRules,
    options: FormatOptions | None = None,
) -> FormatResult:
    opts = options or FormatOptions()
    rules = rule_set.rules if isinstance(rule_set, RuleSet) else rule_set

    document = docx.Document(source if isinstance(source, io.IOBase) else str(source))
    report = Report(dry_run=opts.dry_run)

    if opts.insert_toc is not None:
        rules = rules.model_copy(deep=True)
        rules.toc.insert_field = opts.insert_toc

    try:
        infos = analyze(document, rules, strict=opts.strict_structure)
    except StructureError as exc:
        if opts.strict_structure:
            raise
        report.warnings.append(str(exc))
        infos = analyze(document, rules, strict=False)

    for section in missing_sections(infos, rules):
        report.warnings.append(
            f"Sekcija {section.value} nije pronađena u dokumentu. Pravila je "
            f"očekuju po ključnim rečima "
            f"({', '.join(_keywords_for(rules, section)) or '—'}), ali ih dokument "
            "imenuje drugačije. Njen sadržaj je pripisan prethodnoj sekciji i "
            "dobija njena pravila — dopuni `structure_profile.section_keywords`."
        )

    if opts.dry_run:
        # Probni prolaz prijavljuje samo brisanja: stilske izmene se ionako ne
        # upisuju na disk, a brisanja su jedino što korisnik treba da odobri
        # pre nego što se dogode.
        report.extend(cleanup.preview(document, infos, rules))
        report.warnings.append(
            "Probni prolaz prikazuje samo brisanja; stilske izmene nisu računate."
        )
        return FormatResult(document=document, report=report, structure=infos)

    report.extend(page_setup.apply(document, infos, rules))
    report.extend(paragraphs.apply_headings(document, infos, rules))
    report.extend(paragraphs.apply_body(document, infos, rules))
    report.extend(paragraphs.apply_captions(document, infos, rules))
    report.extend(paragraphs.apply_bibliography(document, infos, rules))
    report.extend(tables.apply(document, infos, rules))
    report.extend(toc.apply(document, infos, rules))

    if opts.clean_empty_paragraphs:
        report.extend(cleanup.apply(document, infos, rules))

    return FormatResult(document=document, report=report, structure=infos)


def _keywords_for(rules: FormattingRules, section: Section) -> list[str]:
    keywords = rules.structure_profile.section_keywords
    return {
        Section.FRONT_MATTER: keywords.front_matter,
        Section.BODY: keywords.body_start,
        Section.BIBLIOGRAPHY: keywords.bibliography,
        Section.APPENDIX: keywords.appendix,
    }.get(section, [])


def describe_structure(source: str | Path, rule_set: RuleSet | FormattingRules) -> dict[str, int]:
    rules = rule_set.rules if isinstance(rule_set, RuleSet) else rule_set
    document = docx.Document(str(source))
    return summarize(analyze(document, rules, strict=False))
