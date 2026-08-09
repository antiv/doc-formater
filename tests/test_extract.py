"""Testovi ekstrakcije pravila: parsiranje, verifikacija citata, fallback."""

from __future__ import annotations

import unittest

from docformat.extract import heuristic
from docformat.extract.mate_client import MateClient, MateConfig, MateError, MateSession
from docformat.extract.pipeline import (
    apply_quote_verification,
    extract_rule_set,
    parse_json_reply,
    verify_quote,
    _normalize_ws,
)
from docformat.extract.source import RulesDocument, TextBlock
from docformat.rules import Alignment, Evidence, FormattingRules

PRAVILNIK = """\
UNIVERZA ALMA MATER EUROPAEA
AKADEMIJA ZA PLES
Oddelek za balet
Diplomsko delo visokošolskega strokovnega programa

2 NAVODILA ZA OBLIKOVANJE
Besedilo naj bo napisano s pisavo Times New Roman, velikost 12 pt.
Razmik med vrsticami je 1,15.
Besedilo mora biti obojestransko poravnano.
Robovi strani: zgoraj 2,5 cm, spodaj 2,5 cm, notranji rob 3 cm, zunanji rob 2,5 cm.
Naslovi prvega nivoja so pisani z velikimi tiskanimi črkami, krepko, velikost 14 pt.
"""


def _document(text: str = PRAVILNIK) -> RulesDocument:
    blocks = [TextBlock(line, page=1) for line in text.splitlines() if line.strip()]
    return RulesDocument(blocks, "pravilnik.pdf")


class ParseReplyTest(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual({"a": 1}, parse_json_reply('{"a": 1}'))

    def test_fenced_json(self) -> None:
        self.assertEqual({"a": 1}, parse_json_reply('```json\n{"a": 1}\n```'))

    def test_json_with_surrounding_prose(self) -> None:
        self.assertEqual({"a": 1}, parse_json_reply('Evo rezultata:\n{"a": 1}\nHvala.'))

    def test_no_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_json_reply("nema ovde nikakvog objekta")


class QuoteVerificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _normalize_ws(PRAVILNIK)

    def test_verbatim_quote_is_strong(self) -> None:
        self.assertEqual("strong", verify_quote("velikost 12 pt", self.source))

    def test_line_break_differences_are_tolerated(self) -> None:
        """PDF prelama redove drugačije nego što ih model prepiše."""
        self.assertEqual(
            "strong",
            verify_quote("Besedilo naj bo napisano\ns pisavo Times New Roman", self.source),
        )

    def test_paraphrase_is_weak(self) -> None:
        self.assertEqual("weak", verify_quote("besedilo pisava Times New Roman velikost", self.source))

    def test_invented_quote_is_missing(self) -> None:
        self.assertEqual(
            "missing", verify_quote("Naslovi morajo biti obarvani modro", self.source)
        )

    def test_hallucinated_field_is_nulled(self) -> None:
        rules = FormattingRules()
        rules.body.size_pt = 12.0
        rules.body.first_line_indent_cm = 1.25

        evidence = [
            Evidence(field_path="body.size_pt", quote="velikost 12 pt", source="mate"),
            Evidence(
                field_path="body.first_line_indent_cm",
                quote="prva vrstica zamaknjena za 1,25 cm",
                source="mate",
            ),
        ]
        kept, rejected = apply_quote_verification(rules, evidence, _document())

        self.assertEqual(["body.first_line_indent_cm"], rejected)
        self.assertEqual(12.0, rules.body.size_pt)
        self.assertIsNone(rules.body.first_line_indent_cm)
        self.assertEqual(["body.size_pt"], [e.field_path for e in kept])


class HeuristicTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rules, self.evidence, self.unresolved = heuristic.extract_rules(PRAVILNIK)

    def test_typography(self) -> None:
        self.assertEqual("Times New Roman", self.rules.typography.font_family)
        self.assertEqual(12.0, self.rules.body.size_pt)
        self.assertEqual(1.15, self.rules.body.line_spacing)
        self.assertEqual(Alignment.JUSTIFY, self.rules.body.alignment)

    def test_margins(self) -> None:
        margins = self.rules.page_setup.margins_cm
        self.assertEqual((2.5, 2.5, 3.0, 2.5), (margins.top, margins.bottom, margins.inside, margins.outside))

    def test_heading(self) -> None:
        self.assertEqual(14.0, self.rules.headings[0].size_pt)
        self.assertTrue(self.rules.headings[0].bold)

    def test_everything_is_marked_low_confidence(self) -> None:
        """Heuristika je most do korisnikovog pregleda, ne izvor istine."""
        for item in self.evidence:
            self.assertEqual("low", item.confidence)
            self.assertEqual("heuristic", item.source)

    def test_institution(self) -> None:
        institution = heuristic.extract_institution(PRAVILNIK)
        self.assertIn("ALMA MATER", (institution.university or "").upper())
        self.assertIn("AKADEMIJA", (institution.faculty or "").upper())

    def test_sentence_boundary_is_respected(self) -> None:
        rules, _, _ = heuristic.extract_rules("Naslovi so levo poravnani. Besedilo je 12 pt.")
        self.assertEqual([], rules.headings)
        self.assertEqual(12.0, rules.body.size_pt)


class PipelineFallbackTest(unittest.TestCase):
    def test_without_client_falls_back_to_heuristic(self) -> None:
        outcome = extract_rule_set(_document(), client=None)
        self.assertEqual("heuristic", outcome.source)
        self.assertEqual("Times New Roman", outcome.rule_set.rules.typography.font_family)

    def test_failing_client_falls_back_and_warns(self) -> None:
        class BrokenClient(MateClient):
            def complete(self, messages):  # type: ignore[override]
                raise MateError("Mate nije dostupan")

        outcome = extract_rule_set(
            _document(), client=BrokenClient(MateConfig(token="x"))
        )
        self.assertEqual("heuristic", outcome.source)
        self.assertTrue(any("not used" in w for w in outcome.warnings))

    def test_mate_reply_is_validated_and_verified(self) -> None:
        class StubClient(MateClient):
            def complete(self, messages):  # type: ignore[override]
                return (
                    '{"rules": {"typography": {"font_family": "Times New Roman"},'
                    ' "body": {"size_pt": 12, "first_line_indent_cm": 1.25}},'
                    ' "evidence": ['
                    '  {"field_path": "typography.font_family",'
                    '   "quote": "s pisavo Times New Roman", "page": 1, "confidence": "high"},'
                    '  {"field_path": "body.size_pt",'
                    '   "quote": "velikost 12 pt", "page": 1, "confidence": "high"},'
                    '  {"field_path": "body.first_line_indent_cm",'
                    '   "quote": "prva vrstica zamaknjena za 1,25 cm", "page": 3, "confidence": "high"}'
                    ' ], "unresolved": []}'
                )

        outcome = extract_rule_set(_document(), client=StubClient(MateConfig(token="x")))

        self.assertEqual("mate", outcome.source)
        self.assertEqual("Times New Roman", outcome.rule_set.rules.typography.font_family)
        self.assertEqual(12.0, outcome.rule_set.rules.body.size_pt)
        # Izmišljeno pravilo je oboreno i prijavljeno.
        self.assertIsNone(outcome.rule_set.rules.body.first_line_indent_cm)
        self.assertEqual(["body.first_line_indent_cm"], outcome.rejected)
        self.assertIn("body.first_line_indent_cm", outcome.rule_set.unresolved)

    def test_repair_round_is_attempted_once(self) -> None:
        class FlakyClient(MateClient):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.calls = 0

            def complete(self, messages):  # type: ignore[override]
                self.calls += 1
                if self.calls == 1:
                    return "Izvinjavam se, evo objašnjenja bez JSON-a."
                return '{"rules": {"body": {"size_pt": 12}}, "evidence": [], "unresolved": []}'

        client = FlakyClient(MateConfig(token="x"))
        outcome = extract_rule_set(_document(), client=client)

        self.assertEqual(2, client.calls, "repair krug nije pokušan tačno jednom")
        self.assertEqual("mate", outcome.source)


class MateSessionTest(unittest.TestCase):
    def test_first_message_stays_fixed(self) -> None:
        """Mate izvodi session_id iz prve poruke — ona se ne sme menjati."""
        sent: list[list[dict]] = []

        class RecordingClient(MateClient):
            def complete(self, messages):  # type: ignore[override]
                sent.append(messages)
                return "{}"

        session = MateSession(RecordingClient(MateConfig(token="x")), discriminator="doc-1")
        session.send("prva poruka")
        session.send("ispravka")

        self.assertEqual(1, len(sent[0]))
        self.assertEqual(2, len(sent[1]))
        self.assertEqual(sent[0][0]["content"], sent[1][0]["content"])
        self.assertIn("[session:", sent[0][0]["content"])

    def test_different_documents_get_different_sessions(self) -> None:
        sent: list[str] = []

        class RecordingClient(MateClient):
            def complete(self, messages):  # type: ignore[override]
                sent.append(messages[0]["content"])
                return "{}"

        client = RecordingClient(MateConfig(token="x"))
        MateSession(client, discriminator="doc-1").send("isti tekst")
        MateSession(client, discriminator="doc-2").send("isti tekst")

        self.assertNotEqual(sent[0], sent[1])


if __name__ == "__main__":
    unittest.main()
