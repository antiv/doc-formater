"""Testovi biblioteke pravila: matchovanje, kopiranje, trajnost."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from docformat.library import RuleLibrary, new_rule_set, suggest_display_name
from docformat.rules import Institution, load_rule_set

from .helpers import AMEU_PRESET


class LibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.library = RuleLibrary(self.directory)
        self.library.save(load_rule_set(AMEU_PRESET))

    def tearDown(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    # -- matchovanje -----------------------------------------------------

    def test_exact_institution_matches(self) -> None:
        match = self.library.find_matches(
            Institution(university="Univerza Alma Mater Europaea", faculty="Akademija za ples")
        )[0]
        self.assertTrue(match.is_strong)

    def test_match_survives_diacritics_and_stopwords(self) -> None:
        """Isti nosilac napisan drugačije mora i dalje da se prepozna."""
        match = self.library.find_matches(
            Institution(university="ALMA MATER EUROPAEA", faculty="AKADEMIJA ZA PLES")
        )[0]
        self.assertTrue(match.is_strong, f"ocena {match.score}")

    def test_different_faculty_is_not_a_strong_match(self) -> None:
        """Dva odseka istog univerziteta imaju različite pravilnike."""
        match = self.library.find_matches(
            Institution(
                university="Univerza Alma Mater Europaea",
                faculty="Fakulteta za zdravstvene vede",
            )
        )[0]
        self.assertFalse(match.is_strong)

    def test_unrelated_institution_scores_low(self) -> None:
        match = self.library.find_matches(
            Institution(university="Univerzitet u Beogradu", faculty="Matematički fakultet")
        )[0]
        self.assertLess(match.score, 0.7)

    def test_empty_institution_yields_no_match(self) -> None:
        self.assertEqual([], self.library.find_matches(Institution()))

    # -- CRUD ------------------------------------------------------------

    def test_duplicate_is_independent(self) -> None:
        copy = self.library.duplicate("ameu-akademija-za-ples")
        copy.rules.body.size_pt = 99.0
        self.library.save(copy)

        self.assertEqual("copied", copy.meta.origin)
        self.assertEqual("ameu-akademija-za-ples", copy.meta.copied_from)
        self.assertEqual(12.0, self.library.load("ameu-akademija-za-ples").rules.body.size_pt)
        self.assertEqual(99.0, self.library.load(copy.meta.id).rules.body.size_pt)

    def test_unique_id_avoids_collision(self) -> None:
        first = new_rule_set("AMEU — Akademija za ples (diplomski rad)", library=self.library)
        self.library.save(first)
        second = new_rule_set("AMEU — Akademija za ples (diplomski rad)", library=self.library)
        self.assertNotEqual(first.meta.id, second.meta.id)

    def test_round_trip_preserves_rules(self) -> None:
        original = self.library.load("ameu-akademija-za-ples")
        reloaded = self.library.load("ameu-akademija-za-ples")
        self.assertEqual(original.rules.model_dump(), reloaded.rules.model_dump())
        self.assertEqual(14.0, reloaded.rules.heading(1).size_pt)

    def test_delete_removes_the_set(self) -> None:
        self.library.delete("ameu-akademija-za-ples")
        self.assertFalse(self.library.exists("ameu-akademija-za-ples"))
        self.assertEqual([], self.library.list())

    def test_corrupt_file_does_not_break_listing(self) -> None:
        (self.directory / "pokvaren.json").write_text("{ ovo nije json", encoding="utf-8")
        self.assertEqual(1, len(self.library.list()))

    def test_suggested_name_uses_institution(self) -> None:
        name = suggest_display_name(
            Institution(university="Univerza X", faculty="Akademija Y", document_type="master rad")
        )
        self.assertIn("Univerza X", name)
        self.assertIn("Akademija Y", name)
        self.assertIn("master rad", name)


if __name__ == "__main__":
    unittest.main()
