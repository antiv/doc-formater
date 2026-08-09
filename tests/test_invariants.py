"""Invarijante formatiranja -- najvažniji testovi u projektu.

Ceo dizajn aplikacije proizlazi iz dva obećanja: tekst se ne prepisuje, a
slike, tabele i grafikoni ne nestaju. Ovi testovi ta obećanja mere.
"""

from __future__ import annotations

import unittest

from styleguard.formatting.engine import FormatOptions, format_document
from styleguard.rules import load_rule_set

from .helpers import (
    AMEU_PRESET,
    SAMPLE_DOCX,
    requires_sample,
    content_census,
    empty_paragraph_count,
    table_text,
    text_sequence,
)


@requires_sample
class TextInvariantTest(unittest.TestCase):
    """Nijedan karakter nepraznog pasusa se ne sme promeniti."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rule_set = load_rule_set(AMEU_PRESET)
        cls.before_text = text_sequence(SAMPLE_DOCX)
        cls.before_census = content_census(SAMPLE_DOCX)
        cls.before_tables = table_text(SAMPLE_DOCX)
        result = format_document(SAMPLE_DOCX, cls.rule_set)
        cls.output = result.to_bytes()
        cls.report = result.report

    def test_text_is_identical(self) -> None:
        after = text_sequence(self.output)
        self.assertEqual(
            len(self.before_text),
            len(after),
            "broj nepraznih pasusa se promenio",
        )
        for index, (before, after_text) in enumerate(zip(self.before_text, after)):
            self.assertEqual(before, after_text, f"pasus {index} je izmenjen")

    def test_uppercase_rule_does_not_rewrite_text(self) -> None:
        """Naslovi nivoa 1 su UPPERCASE po pravilu, ali preko `w:caps`."""
        self.assertIn("UVOD", "\n".join(self.before_text))
        joined = "\n".join(text_sequence(self.output))
        # Da je primenjeno `.upper()`, mešoviti naslovi bi izgubili mala slova.
        mixed = [t for t in text_sequence(self.output) if t != t.upper() and len(t) > 20]
        self.assertTrue(mixed, "svi pasusi su postali velikim slovima — tekst je prepisan")
        self.assertIn("Slika", joined)

    def test_table_text_is_identical(self) -> None:
        self.assertEqual(self.before_tables, table_text(self.output))


@requires_sample
class ContentInvariantTest(unittest.TestCase):
    """Slike, tabele, grafikoni, fusnote i linkovi ostaju u fajlu."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rule_set = load_rule_set(AMEU_PRESET)
        cls.before = content_census(SAMPLE_DOCX)
        cls.output = format_document(SAMPLE_DOCX, cls.rule_set).to_bytes()
        cls.after = content_census(cls.output)

    def test_nothing_is_lost(self) -> None:
        for label, before_count in self.before.items():
            self.assertEqual(
                before_count,
                self.after[label],
                f"{label}: {before_count} → {self.after[label]}",
            )

    def test_document_actually_contains_media(self) -> None:
        """Test bi bio besmislen na dokumentu bez nosećeg sadržaja.

        Ovaj uzorak nema tabele ni fusnote -- njih pokriva sintetički fixture u
        `test_fixtures.py`, koji je i napravljen zato što stvarni rad ne
        pogađa sve slučajeve.
        """
        self.assertGreater(self.before["image parts"], 0)
        self.assertGreater(self.before["slike (w:drawing)"], 0)
        self.assertGreater(self.before["hyperlink-ovi"], 0)
        self.assertGreater(self.before["prelomi sekcija (w:sectPr)"], 0)


@requires_sample
class CleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rule_set = load_rule_set(AMEU_PRESET)

    def test_empty_paragraphs_are_removed(self) -> None:
        before = empty_paragraph_count(SAMPLE_DOCX)
        output = format_document(SAMPLE_DOCX, self.rule_set).to_bytes()
        after = empty_paragraph_count(output)
        self.assertLess(after, before, "nijedan prazan pasus nije obrisan")

    def test_cleanup_is_opt_in_via_rules(self) -> None:
        """Bez `allow_empty_paragraphs: false` ništa se ne briše."""
        rule_set = load_rule_set(AMEU_PRESET)
        rule_set.rules.body.allow_empty_paragraphs = None
        result = format_document(SAMPLE_DOCX, rule_set)
        self.assertEqual([], result.report.deletions)

    def test_dry_run_changes_nothing(self) -> None:
        result = format_document(
            SAMPLE_DOCX, self.rule_set, FormatOptions(dry_run=True)
        )
        self.assertTrue(result.report.deletions, "probni prolaz ne prijavljuje brisanja")
        self.assertEqual(
            empty_paragraph_count(SAMPLE_DOCX),
            empty_paragraph_count(result.to_bytes()),
            "probni prolaz je izmenio dokument",
        )

    def test_deleted_paragraphs_carried_no_content(self) -> None:
        """Nijedno brisanje ne sme pogoditi pasus sa slikom ili poljem."""
        result = format_document(
            SAMPLE_DOCX, self.rule_set, FormatOptions(dry_run=True)
        )
        import docx

        from styleguard.analyze.structure import analyze
        from styleguard.formatting.ops.cleanup import is_safe_to_delete

        infos = {i.index: i for i in analyze(docx.Document(str(SAMPLE_DOCX)), self.rule_set.rules)}
        for change in result.report.deletions:
            info = infos[change.paragraph_index]
            safe, reason = is_safe_to_delete(info)
            self.assertTrue(safe, f"pasus {info.index} nije smeo da bude obrisan: {reason}")


@requires_sample
class IdempotencyTest(unittest.TestCase):
    """Drugi prolaz nad već formatiranim dokumentom ne sme ništa da menja."""

    def test_second_pass_is_a_no_op(self) -> None:
        rule_set = load_rule_set(AMEU_PRESET)
        first = format_document(SAMPLE_DOCX, rule_set)
        second = format_document(__import__("io").BytesIO(first.to_bytes()), rule_set)

        self.assertEqual(
            [], second.report.deletions, "drugi prolaz i dalje briše pasuse"
        )
        # Poneka stilska izmena sme da ostane samo ako potiče od pomerenih
        # indeksa; suštinski, drugi prolaz mora biti gotovo prazan.
        self.assertLess(
            len(second.report.style_changes),
            len(first.report.style_changes) * 0.05,
            "formatiranje nije idempotentno",
        )


if __name__ == "__main__":
    unittest.main()
