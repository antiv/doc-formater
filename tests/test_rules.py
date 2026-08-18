"""Testovi modela pravila i pomoćnih funkcija koje vozi UI editor."""

from __future__ import annotations

import unittest

from styleguard.rules import (
    Alignment,
    CaptionPosition,
    Casing,
    FormattingRules,
    HeadingLevel,
    RuleSet,
    RuleSetMeta,
    enum_type_for_path,
    field_type_for_path,
    get_by_path,
    iter_field_paths,
    load_rule_set,
    set_by_path,
    slugify,
)

from .helpers import AMEU_PRESET


class HeadingFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = FormattingRules(
            headings=[
                HeadingLevel(level=1, size_pt=14, bold=True),
                HeadingLevel(level=3, size_pt=12, bold=False),
            ]
        )

    def test_exact_level(self) -> None:
        self.assertEqual(14.0, self.rules.heading(1).size_pt)

    def test_missing_level_falls_back_to_nearest_shallower(self) -> None:
        self.assertEqual(1, self.rules.heading(2).level)

    def test_deeper_level_falls_back_to_deepest_defined(self) -> None:
        """Pravilnik definiše 1-3 pa kaže „i niže isto”."""
        self.assertEqual(3, self.rules.heading(7).level)

    def test_no_headings_yields_none(self) -> None:
        self.assertIsNone(FormattingRules().heading(1))


class FieldPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = load_rule_set(AMEU_PRESET).rules

    def test_model_lists_are_excluded(self) -> None:
        """Generički editor bi `headings` pregazio listom stringova."""
        paths = [path for path, _ in iter_field_paths(self.rules)]
        self.assertNotIn("headings", paths)

    def test_empty_model_list_is_also_excluded(self) -> None:
        paths = [path for path, _ in iter_field_paths(FormattingRules())]
        self.assertNotIn("headings", paths)

    def test_plain_lists_are_kept(self) -> None:
        paths = [path for path, _ in iter_field_paths(self.rules)]
        self.assertIn("structure_profile.figure_caption_prefixes", paths)
        self.assertIn("typography.fallback_fonts", paths)

    def test_nested_models_are_flattened(self) -> None:
        paths = [path for path, _ in iter_field_paths(self.rules)]
        self.assertIn("page_setup.margins_cm.inside", paths)
        self.assertIn("captions.figure.alignment", paths)

    def test_get_and_set_by_path(self) -> None:
        set_by_path(self.rules, "body.size_pt", 11.0)
        self.assertEqual(11.0, get_by_path(self.rules, "body.size_pt"))
        self.assertIsNone(get_by_path(self.rules, "nema.takvog.polja"))


class EnumTypeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = load_rule_set(AMEU_PRESET).rules

    def test_enum_fields_are_detected(self) -> None:
        self.assertIs(Alignment, enum_type_for_path(self.rules, "body.alignment"))
        self.assertIs(CaptionPosition, enum_type_for_path(self.rules, "captions.figure.position"))
        self.assertIs(Alignment, enum_type_for_path(self.rules, "captions.table.alignment"))

    def test_detection_works_when_value_is_none(self) -> None:
        """Polje koje pravilnik ne propisuje i dalje mora biti izbor, ne tekst."""
        self.rules.body.alignment = None
        self.assertIs(Alignment, enum_type_for_path(self.rules, "body.alignment"))

    def test_non_enum_fields_return_none(self) -> None:
        self.assertIsNone(enum_type_for_path(self.rules, "body.size_pt"))
        self.assertIsNone(enum_type_for_path(self.rules, "typography.font_family"))
        self.assertIsNone(enum_type_for_path(self.rules, "nema.takvog"))

    def test_detection_works_on_a_default_model(self) -> None:
        """Tip se čita iz anotacije, pa radi i na praznom modelu."""
        self.assertIs(Alignment, enum_type_for_path(FormattingRules(), "bibliography.alignment"))


class SlugifyTest(unittest.TestCase):
    def test_diacritics_are_folded(self) -> None:
        self.assertEqual("djordje-scepanovic", slugify("Đorđe Šćepanović"))

    def test_punctuation_collapses(self) -> None:
        self.assertEqual(
            "univerza-alma-mater-europaea-akademija-za-ples",
            slugify("Univerza Alma Mater Europaea – Akademija za ples"),
        )

    def test_empty_input_has_a_fallback(self) -> None:
        self.assertEqual("rule-set", slugify("!!!"))


class FieldTypeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = load_rule_set(AMEU_PRESET).rules

    def test_margin_fields_are_detected_as_float(self) -> None:
        self.assertIs(float, field_type_for_path(self.rules, "page_setup.margins_cm.top"))
        self.assertIs(float, field_type_for_path(self.rules, "page_setup.margins_cm.bottom"))
        self.assertIs(float, field_type_for_path(self.rules, "page_setup.margins_cm.inside"))
        self.assertIs(float, field_type_for_path(self.rules, "page_setup.margins_cm.outside"))

    def test_other_types_are_detected(self) -> None:
        self.assertIs(float, field_type_for_path(self.rules, "body.size_pt"))
        self.assertIs(bool, field_type_for_path(self.rules, "page_setup.mirror_margins"))
        self.assertIs(Alignment, field_type_for_path(self.rules, "body.alignment"))
        self.assertIs(list, field_type_for_path(self.rules, "typography.fallback_fonts"))
        self.assertIs(str, field_type_for_path(self.rules, "typography.font_family"))


class AssignmentValidationTest(unittest.TestCase):
    def test_string_number_coerced_on_assignment(self) -> None:
        rules = FormattingRules()
        set_by_path(rules, "page_setup.margins_cm.top", "2.5")
        self.assertEqual(2.5, rules.page_setup.margins_cm.top)
        self.assertIsInstance(rules.page_setup.margins_cm.top, float)


class SerializationTest(unittest.TestCase):
    def test_round_trip_preserves_enums(self) -> None:
        rule_set = load_rule_set(AMEU_PRESET)
        reloaded = RuleSet.model_validate_json(rule_set.model_dump_json())
        self.assertEqual(Alignment.JUSTIFY, reloaded.rules.body.alignment)
        self.assertEqual(CaptionPosition.BELOW, reloaded.rules.captions.figure.position)
        self.assertEqual(Casing.UPPERCASE, reloaded.rules.heading(1).casing)

    def test_none_is_preserved_not_dropped(self) -> None:
        """`None` znači „ne diraj” i mora preživeti serijalizaciju."""
        rule_set = RuleSet(meta=RuleSetMeta(id="t", display_name="T"))
        reloaded = RuleSet.model_validate_json(rule_set.model_dump_json())
        self.assertIsNone(reloaded.rules.body.size_pt)
        self.assertIsNone(reloaded.rules.body.allow_empty_paragraphs)


if __name__ == "__main__":
    unittest.main()
