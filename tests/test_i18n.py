"""Translation catalogue tests.

The point of these is that a half-finished translation should be caught here
rather than surfacing as a bare key in someone's browser.
"""

from __future__ import annotations

import json
import re
import string
import unittest

from docformat import i18n


class CatalogueConsistencyTest(unittest.TestCase):
    """Every language must cover exactly the English key set."""

    def setUp(self) -> None:
        i18n.reload_catalogues()

    def test_english_exists_and_is_not_empty(self) -> None:
        catalogue = i18n._catalogue(i18n.DEFAULT_LANGUAGE)
        self.assertGreater(len(catalogue), 50, "the English catalogue looks truncated")

    def test_every_language_has_every_key(self) -> None:
        for language in i18n.available_languages():
            with self.subTest(language=language):
                self.assertEqual(
                    [], i18n.missing_keys(language), f"{language} is missing keys"
                )

    def test_no_language_has_stale_keys(self) -> None:
        """A key left behind after a rename would never be shown."""
        for language in i18n.available_languages():
            with self.subTest(language=language):
                self.assertEqual(
                    [], i18n.extra_keys(language), f"{language} has keys English does not"
                )

    def test_placeholders_match_english(self) -> None:
        """A translation that drops or invents a placeholder breaks formatting."""
        def placeholders(text: str) -> set[str]:
            return {
                name
                for _, name, _, _ in string.Formatter().parse(text)
                if name
            }

        english = i18n._catalogue(i18n.DEFAULT_LANGUAGE)
        for language in i18n.available_languages():
            if language == i18n.DEFAULT_LANGUAGE:
                continue
            catalogue = i18n._catalogue(language)
            for key, source in english.items():
                with self.subTest(language=language, key=key):
                    self.assertEqual(
                        placeholders(source),
                        placeholders(catalogue[key]),
                        f"{language}:{key} placeholder mismatch",
                    )

    def test_every_catalogue_is_valid_json(self) -> None:
        for path in i18n.LOCALES_DIR.glob("*.json"):
            with self.subTest(file=path.name):
                json.loads(path.read_text(encoding="utf-8"))

    def test_declared_languages_have_a_name(self) -> None:
        for language in i18n.available_languages():
            self.assertIn(language, i18n.LANGUAGE_NAMES)

    def test_expected_languages_are_present(self) -> None:
        self.assertEqual({"en", "sr", "fr", "de"}, set(i18n.available_languages()))


class LookupTest(unittest.TestCase):
    def setUp(self) -> None:
        i18n.reload_catalogues()
        i18n.set_language("en")

    def test_translation(self) -> None:
        i18n.set_language("sr")
        self.assertEqual("Formatiraj", i18n.t("format.run"))

    def test_parameters_are_substituted(self) -> None:
        self.assertEqual("Saved: ameu", i18n.t("save.saved", id="ameu"))

    def test_unknown_key_returns_the_key(self) -> None:
        """Visible in the UI as a bare key, rather than a crash."""
        self.assertEqual("no.such.key", i18n.t("no.such.key"))

    def test_missing_translation_falls_back_to_english(self) -> None:
        original = dict(i18n._catalogue("sr"))
        try:
            i18n._catalogue("sr").pop("format.run", None)
            i18n.set_language("sr")
            self.assertEqual("Format", i18n.t("format.run"))
        finally:
            i18n._catalogue("sr").clear()
            i18n._catalogue("sr").update(original)

    def test_bad_placeholder_does_not_raise(self) -> None:
        self.assertIsInstance(i18n.t("save.saved", wrong_name="x"), str)

    def test_unknown_language_falls_back_to_default(self) -> None:
        self.assertEqual("en", i18n.set_language("xx"))
        self.assertEqual("en", i18n.get_language())


class NegotiateTest(unittest.TestCase):
    def setUp(self) -> None:
        i18n.reload_catalogues()

    def test_exact_match(self) -> None:
        self.assertEqual("de", i18n.negotiate("de"))

    def test_region_subtag_is_ignored(self) -> None:
        self.assertEqual("sr", i18n.negotiate("sr-Latn-RS,sr;q=0.9"))

    def test_quality_decides(self) -> None:
        self.assertEqual("de", i18n.negotiate("fr;q=0.5,de;q=0.9"))

    def test_unsupported_language_falls_back(self) -> None:
        self.assertEqual("en", i18n.negotiate("ja-JP,ja;q=0.9"))

    def test_missing_header_falls_back(self) -> None:
        self.assertEqual("en", i18n.negotiate(None))
        self.assertEqual("en", i18n.negotiate(""))

    def test_malformed_quality_does_not_raise(self) -> None:
        self.assertIn(i18n.negotiate("de;q=abc,fr"), {"de", "fr"})


class NoHardcodedStringsTest(unittest.TestCase):
    """The UI must not carry text that the catalogues cannot reach."""

    def test_no_serbian_literals_in_user_facing_modules(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        modules = [
            root / "app.py",
            root / "docformat" / "identity.py",
            root / "docformat" / "report.py",
        ]
        # Serbian-specific letters inside a string literal; comments and
        # docstrings are allowed to stay in Serbian.
        literal = re.compile(r'(?<!\w)"[^"\n]*[čćžšđČĆŽŠĐ][^"\n]*"')

        for module in modules:
            source = module.read_text(encoding="utf-8")
            without_docstrings = re.sub(r'"""(?:.|\n)*?"""', "", source)
            without_comments = re.sub(r"#.*", "", without_docstrings)
            found = literal.findall(without_comments)
            with self.subTest(module=module.name):
                self.assertEqual([], found, f"untranslated literals in {module.name}")


if __name__ == "__main__":
    unittest.main()
