"""Pretraga setova pravila.

Testira se ono što je u regionu specifično i što se tiho pokvari: ćirilica,
dijakritika i padeži. Pretraga koja ih ne podnosi izgleda ispravno na engleskim
primerima, a na stvarnim nazivima vraća prazno.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from styleguard.rules import load_rule_set
from styleguard.search import fold, matches, score, search

PRESETS = sorted((Path(__file__).resolve().parent.parent / "presets").glob("*.json"))


class FoldTest(unittest.TestCase):
    def test_diacritics_are_removed(self):
        self.assertEqual(fold("Niš"), "nis")
        self.assertEqual(fold("Sveučilište"), "sveuciliste")
        self.assertEqual(fold("Đorđe"), "djordje")

    def test_cyrillic_is_transliterated(self):
        self.assertEqual(fold("Скопје"), "skopje")
        self.assertEqual(fold("Економски"), "ekonomski")

    def test_punctuation_becomes_word_breaks(self):
        self.assertEqual(fold("Univerzitet „Džemal Bijedić“"), "univerzitet dzemal bijedic")

    def test_empty_input(self):
        self.assertEqual(fold(None), "")
        self.assertEqual(fold("   "), "")


class SearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sets = [load_rule_set(path) for path in PRESETS]

    def ids(self, query):
        return [rs.meta.id for rs in search(self.sets, query)]

    def test_empty_query_returns_everything(self):
        self.assertEqual(len(search(self.sets, "")), len(self.sets))
        self.assertEqual(len(search(self.sets, "   ")), len(self.sets))

    def test_city_in_nominative_finds_the_inflected_name(self):
        """Korisnik kuca „Sarajevo", u pravilniku piše „u Sarajevu"."""
        for query, expected in [
            ("sarajevo", "sa-medicinski"),
            ("ljubljana", "lj-pef"),
            ("rijeka", "ri-pomorski"),
            ("novi sad", "ns-poljoprivredni"),
        ]:
            with self.subTest(query=query):
                self.assertIn(expected, self.ids(query))

    def test_latin_query_finds_a_cyrillic_set(self):
        self.assertEqual(self.ids("skopje"), ["sk-ekonomski"])

    def test_diacritics_are_optional(self):
        self.assertEqual(self.ids("nis"), self.ids("niš"))

    def test_best_match_comes_first(self):
        """Dve reči koje pogađaju isti set dižu ga iznad onog sa jednom."""
        self.assertEqual(self.ids("nis elektronski")[0], "ni-elfak")
        self.assertEqual(self.ids("sarajevo medicinski")[0], "sa-medicinski")

    def test_more_words_never_yield_fewer_hits_than_none(self):
        """„Banja Luka" -- „Luka" se u „Luci" ne pogađa nastavkom.

        Da se tražilo poklapanje svih reči, ovo bi bilo prazno iako „banja"
        sam vraća tačan set. Pretraga u kojoj duže kucanje daje nula rezultata
        je gora od nikakve.
        """
        self.assertIn("bl-tehnoloski", self.ids("banja luka"))

    def test_unknown_query_returns_nothing(self):
        self.assertEqual(self.ids("qwertzuiop"), [])

    def test_score_counts_matched_words(self):
        elfak = next(rs for rs in self.sets if rs.meta.id == "ni-elfak")
        self.assertEqual(score(elfak, "nis elektronski"), 2)
        self.assertEqual(score(elfak, "nis"), 1)
        self.assertEqual(score(elfak, "qwertz"), 0)

    def test_matches_agrees_with_score(self):
        for rule_set in self.sets:
            with self.subTest(rule_set=rule_set.meta.id):
                self.assertEqual(matches(rule_set, "zagreb"), score(rule_set, "zagreb") > 0)

    def test_every_bundled_set_is_reachable_by_its_own_words(self):
        """Set koji se ne može naći pretragom je isporučen uzalud."""
        for rule_set in self.sets:
            with self.subTest(rule_set=rule_set.meta.id):
                faculty = rule_set.meta.institution.faculty or ""
                university = rule_set.meta.institution.university or ""
                query = fold(faculty or university).split()[0]
                self.assertIn(rule_set.meta.id, self.ids(query))


if __name__ == "__main__":
    unittest.main()
