"""Preseti su podaci koje aplikacija isporučuje, pa moraju da izdrže isto što i
korisnički set pravila.

Preset koji se ne učitava ili čiji `id` ne odgovara imenu fajla nije samo
neispravan -- on je nevidljiv: `--rules-id` ga traži po `id`, a `presets/` se
nabraja po imenu fajla, pa se razilaženje to dvoje vidi tek kad neko pokuša da
ga upotrebi.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from styleguard.rules import RuleSet, load_rule_set

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"
PRESETS = sorted(PRESETS_DIR.glob("*.json"))


class PresetTest(unittest.TestCase):
    def test_there_are_presets(self):
        self.assertTrue(PRESETS, "presets/ je prazan")

    def test_every_preset_loads(self):
        for path in PRESETS:
            with self.subTest(preset=path.name):
                self.assertIsInstance(load_rule_set(path), RuleSet)

    def test_reachable_by_filename_and_by_id(self):
        """`--rules-id` prihvata oba, pa oba moraju da vode do istog seta.

        Ne traži se da se poklapaju -- `ameu.json` nosi
        `ameu-akademija-za-ples` i to je u redu -- nego da nijedan od dva puta
        ne promaši.
        """
        import cli  # noqa: PLC0415 -- razrešavanje preseta živi u CLI-ju

        for path in PRESETS:
            with self.subTest(preset=path.name):
                by_stem = cli._find_preset(path.stem)
                by_id = cli._find_preset(load_rule_set(path).meta.id)
                self.assertIsNotNone(by_stem, "ime fajla ne razrešava preset")
                self.assertIsNotNone(by_id, "meta.id ne razrešava preset")
                self.assertEqual(by_stem.meta.id, by_id.meta.id)

    def test_ids_are_unique(self):
        ids = [json.loads(p.read_text(encoding="utf-8"))["meta"]["id"] for p in PRESETS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_institution_is_identifiable(self):
        """Bez institucije se preset ne može ponuditi kad se prepozna pravilnik."""
        for path in PRESETS:
            with self.subTest(preset=path.name):
                inst = json.loads(path.read_text(encoding="utf-8"))["meta"]["institution"]
                self.assertTrue(
                    inst.get("university") or inst.get("organization"),
                    "ni university ni organization nisu postavljeni",
                )

    def test_declared_language_is_consistent(self):
        """Jezik institucije i jezik strukturnog profila ne smeju da se razilaze."""
        for path in PRESETS:
            with self.subTest(preset=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                inst = data["meta"]["institution"].get("language")
                profile = (data["rules"].get("structure_profile") or {}).get("language")
                if inst and profile:
                    self.assertEqual(inst, profile)

    def test_evidence_paths_point_at_real_fields(self):
        """Citat zakačen za nepostojeće polje ne bi bio prikazan nigde."""
        for path in PRESETS:
            data = json.loads(path.read_text(encoding="utf-8"))
            rules = data["rules"]
            for item in data.get("evidence") or []:
                field_path = item["field_path"]
                with self.subTest(preset=path.name, field=field_path):
                    node = rules
                    for part in field_path.split("."):
                        if isinstance(node, list):
                            # "headings.1.size_pt" -- 1 je nivo naslova, ne indeks
                            match = [h for h in node if str(h.get("level")) == part]
                            self.assertTrue(match, f"nema naslova nivoa {part}")
                            node = match[0]
                            continue
                        self.assertIsInstance(node, dict)
                        self.assertIn(part, node)
                        node = node[part]

    def test_a_quoted_field_is_actually_set(self):
        """Dokaz bez vrednosti je obrnut od smisla: citat tvrdi da pravilo postoji."""
        for path in PRESETS:
            data = json.loads(path.read_text(encoding="utf-8"))
            rules = data["rules"]
            for item in data.get("evidence") or []:
                if not (item.get("quote") or "").strip():
                    continue  # prazan citat = preset bez izvora, dozvoljeno
                with self.subTest(preset=path.name, field=item["field_path"]):
                    node = rules
                    for part in item["field_path"].split("."):
                        if isinstance(node, list):
                            node = [h for h in node if str(h.get("level")) == part][0]
                            continue
                        node = node[part]
                    self.assertIsNotNone(node, "citirano polje je None")


if __name__ == "__main__":
    unittest.main()
