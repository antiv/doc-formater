"""Biblioteka snimljenih setova pravila.

Fajl-bazirana: jedan JSON po setu u `rules_library/`. Bez baze -- setova je
red veličine desetine, a JSON na disku je i backup i format za razmenu.

Glavna vrednost biblioteke je `find_matches`: ekstrakcija pravilnika je
najskuplji i najnepouzdaniji korak u celom lancu, pa se radi jednom po
instituciji i posle prepoznaje po nazivu.
"""

from __future__ import annotations

import difflib
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .rules import Institution, RuleSet, RuleSetMeta, dump_rule_set, load_rule_set, slugify

_PROJECT_LIBRARY_DIR = Path(__file__).resolve().parent.parent / "rules_library"


def default_library_dir() -> Path:
    """Gde žive sačuvani setovi pravila.

    U kontejneru se montira volume i putanja se zadaje kroz
    `RULES_LIBRARY_DIR` -- bez toga bi svaki redeploy obrisao biblioteku, koja
    je jedini trajni podatak aplikacije.
    """
    configured = os.getenv("RULES_LIBRARY_DIR", "").strip()
    return Path(configured) if configured else _PROJECT_LIBRARY_DIR

# Reči koje nose nula informacije pri poređenju naziva -- gotovo svaki
# pravilnik ih ima, pa bi bez izbacivanja svi setovi ličili jedan na drugi.
_STOPWORDS = {
    "univerza", "univerzitet", "univerziteta", "university", "univ",
    "fakultet", "fakulteta", "faculty", "akademija", "academy",
    "visoka", "visoko", "sola", "skola", "school", "college",
    "odsek", "odsjek", "department", "katedra",
    "doo", "d o o", "ltd", "inc", "institut", "institute",
    "za", "of", "the", "and", "i",
}


def _normalize(value: str | None) -> str:
    """Naziv sveden na uporedivo jezgro: bez dijakritike, bez stop-reči."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    ascii_only = ascii_only.replace("đ", "dj").replace("Đ", "dj")
    ascii_only = ascii_only.encode("ascii", "ignore").decode("ascii").lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", ascii_only) if t]
    kept = [t for t in tokens if t not in _STOPWORDS]
    # Ako od naziva ne ostane ništa (npr. "Fakultet"), vrati sve tokene --
    # bolje slabo poređenje nego prazan string koji se poklapa sa svime.
    return " ".join(kept or tokens)


def _similarity(a: str | None, b: str | None) -> float | None:
    """Sličnost dva naziva, ili None ako jedan nedostaje."""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return None
    return difflib.SequenceMatcher(None, na, nb).ratio()


@dataclass
class Match:
    rule_set: RuleSet
    score: float
    detail: dict[str, float]

    @property
    def is_strong(self) -> bool:
        return self.score >= 0.90

    @property
    def is_suggestion(self) -> bool:
        return 0.70 <= self.score < 0.90


class RuleLibrary:
    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory else default_library_dir()
        self.directory.mkdir(parents=True, exist_ok=True)

    # -- CRUD ------------------------------------------------------------

    def path_for(self, rule_set_id: str) -> Path:
        return self.directory / f"{rule_set_id}.json"

    def list(self) -> list[RuleSet]:
        out: list[RuleSet] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                out.append(load_rule_set(path))
            except Exception:
                # Neispravan fajl ne sme da obori celu biblioteku.
                continue
        return sorted(out, key=lambda rs: rs.meta.updated_at, reverse=True)

    def load(self, rule_set_id: str) -> RuleSet:
        path = self.path_for(rule_set_id)
        if not path.exists():
            raise KeyError(f"Set pravila '{rule_set_id}' ne postoji u {self.directory}")
        return load_rule_set(path)

    def exists(self, rule_set_id: str) -> bool:
        return self.path_for(rule_set_id).exists()

    def save(self, rule_set: RuleSet) -> RuleSet:
        rule_set.meta.updated_at = datetime.now(timezone.utc)
        dump_rule_set(rule_set, self.path_for(rule_set.meta.id))
        return rule_set

    def delete(self, rule_set_id: str) -> None:
        self.path_for(rule_set_id).unlink(missing_ok=True)

    def duplicate(self, rule_set_id: str, new_name: str | None = None) -> RuleSet:
        """Nezavisna kopija -- za "isti fakultet, drugi tip rada"."""
        original = self.load(rule_set_id)
        copy = original.model_copy(deep=True)
        copy.meta.display_name = new_name or f"{original.meta.display_name} (kopija)"
        copy.meta.id = self.unique_id(copy.meta.display_name)
        copy.meta.origin = "copied"
        copy.meta.copied_from = original.meta.id
        copy.meta.created_at = datetime.now(timezone.utc)
        return self.save(copy)

    def unique_id(self, display_name: str) -> str:
        base = slugify(display_name)
        candidate, n = base, 2
        while self.exists(candidate):
            candidate = f"{base}-{n}"
            n += 1
        return candidate

    def import_(self, path: str | Path) -> RuleSet:
        rule_set = load_rule_set(path)
        if self.exists(rule_set.meta.id):
            rule_set.meta.id = self.unique_id(rule_set.meta.display_name)
        return self.save(rule_set)

    # -- Matchovanje -----------------------------------------------------

    def find_matches(self, institution: Institution, limit: int = 5) -> list[Match]:
        """Setovi iz biblioteke rangirani po poklapanju institucije.

        Težine: `faculty` nosi najviše jer razlikuje setove unutar istog
        univerziteta -- dva odseka istog fakulteta mogu imati različite
        pravilnike, pa se nikad ne bira automatski bez potvrde korisnika.
        """
        weights = {
            "university": 0.30,
            "faculty": 0.40,
            "department": 0.20,
            "organization": 0.10,
        }
        matches: list[Match] = []

        for candidate in self.list():
            other = candidate.meta.institution
            detail: dict[str, float] = {}
            weighted_sum = 0.0
            weight_total = 0.0

            for field, weight in weights.items():
                score = _similarity(getattr(institution, field), getattr(other, field))
                if score is None:
                    continue
                detail[field] = round(score, 3)
                weighted_sum += score * weight
                weight_total += weight

            if weight_total == 0.0:
                continue

            # Normalizacija po stvarno uporedivim poljima -- set koji ima samo
            # `faculty` popunjen ne sme da bude kažnjen zbog praznog `university`.
            overall = weighted_sum / weight_total

            # Tip dokumenta nije deo identiteta institucije, ali eksplicitno
            # neslaganje ("diplomski" vs "master") je jak signal da pravilnik
            # nije isti -- pa obara ocenu ispod praga automatskog izbora.
            doc_score = _similarity(institution.document_type, other.document_type)
            if doc_score is not None:
                detail["document_type"] = round(doc_score, 3)
                if doc_score < 0.5:
                    overall *= 0.85

            matches.append(Match(rule_set=candidate, score=round(overall, 3), detail=detail))

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]


def new_rule_set(
    display_name: str,
    institution: Institution | None = None,
    library: RuleLibrary | None = None,
    origin: str = "manual",
    source_filename: str | None = None,
) -> RuleSet:
    lib = library or RuleLibrary()
    return RuleSet(
        meta=RuleSetMeta(
            id=lib.unique_id(display_name),
            display_name=display_name,
            institution=institution or Institution(),
            origin=origin,  # type: ignore[arg-type]
            source_filename=source_filename,
        )
    )


def suggest_display_name(institution: Institution) -> str:
    parts = [
        institution.university,
        institution.faculty,
        institution.department,
        institution.organization,
    ]
    name = " — ".join(p for p in parts if p)
    if institution.document_type:
        name = f"{name} ({institution.document_type})" if name else institution.document_type
    return name or "Nov set pravila"
