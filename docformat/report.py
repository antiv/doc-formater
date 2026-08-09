"""Izveštaj o primenjenim izmenama.

Bez ovoga korisnik nema način da proveri rezultat osim ručnim pregledom sto
strana. Brisanja se vode odvojeno od stilskih izmena jer su jedina nepovratna
operacija u lancu.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

ChangeKind = Literal["style", "delete", "insert"]


@dataclass
class Change:
    kind: ChangeKind
    rule_path: str
    paragraph_index: int | None = None
    section: str | None = None
    role: str | None = None
    before: object = None
    after: object = None
    detail: str = ""

    def describe(self) -> str:
        if self.kind == "delete":
            return f"[{self.paragraph_index}] obrisano: {self.detail or self.rule_path}"
        if self.kind == "insert":
            return f"ubačeno: {self.detail or self.rule_path}"
        return f"[{self.paragraph_index}] {self.rule_path}: {self.before!r} → {self.after!r}"


@dataclass
class RuleSummary:
    rule_path: str
    role: str | None
    count: int
    transitions: list[tuple[object, object, int]]

    @property
    def label(self) -> str:
        return f"{self.role or '—'} / {self.rule_path}"

    def describe_transitions(self, limit: int = 3) -> str:
        parts = [f"{before!r}→{after!r} ({n}×)" for before, after, n in self.transitions[:limit]]
        if len(self.transitions) > limit:
            parts.append(f"… +{len(self.transitions) - limit}")
        return ", ".join(parts)


@dataclass
class Report:
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False

    def add(self, change: Change) -> None:
        self.changes.append(change)

    def extend(self, changes: list[Change]) -> None:
        self.changes.extend(changes)

    # -- pogledi ---------------------------------------------------------

    @property
    def style_changes(self) -> list[Change]:
        return [c for c in self.changes if c.kind == "style"]

    @property
    def deletions(self) -> list[Change]:
        return [c for c in self.changes if c.kind == "delete"]

    @property
    def insertions(self) -> list[Change]:
        return [c for c in self.changes if c.kind == "insert"]

    def by_rule(self) -> list[RuleSummary]:
        """Stilske izmene grupisane po (uloga, pravilo).

        Grupisanje samo po pravilu spaja telo teksta, naslove i natpise u jedan
        red, pa broj izmena ne govori ništa o tome šta se s čim dogodilo --
        uloga je ono što taj broj čini čitljivim.
        """
        buckets: dict[tuple[str | None, str], list[Change]] = {}
        for change in self.style_changes:
            buckets.setdefault((change.role, change.rule_path), []).append(change)

        summaries: list[RuleSummary] = []
        for (role, path), items in buckets.items():
            counter = Counter((c.before, c.after) for c in items)
            transitions = [
                (before, after, count) for (before, after), count in counter.most_common()
            ]
            summaries.append(
                RuleSummary(rule_path=path, role=role, count=len(items), transitions=transitions)
            )
        return sorted(summaries, key=lambda s: (-s.count, s.label))

    def deletion_counts(self) -> dict[str, int]:
        return dict(Counter(c.rule_path for c in self.deletions))

    # -- ispis -----------------------------------------------------------

    def to_text(self, max_deletions: int = 20) -> str:
        lines: list[str] = []
        if self.dry_run:
            lines.append("*** PROBNI PROLAZ — dokument nije izmenjen ***\n")

        lines.append(f"Stilske izmene: {len(self.style_changes)}")
        for summary in self.by_rule():
            lines.append(
                f"  {summary.label:52} {summary.count:5}×   {summary.describe_transitions()}"
            )

        if self.deletions:
            lines.append(f"\nBrisanja: {len(self.deletions)}")
            for path, count in sorted(self.deletion_counts().items()):
                lines.append(f"  {path:42} {count:5}×")
            lines.append("  detalji:")
            for change in self.deletions[:max_deletions]:
                lines.append(f"    {change.describe()}")
            if len(self.deletions) > max_deletions:
                lines.append(f"    … i još {len(self.deletions) - max_deletions}")

        if self.insertions:
            lines.append(f"\nDodato: {len(self.insertions)}")
            for change in self.insertions:
                lines.append(f"  {change.describe()}")

        if self.warnings:
            lines.append("\nUpozorenja:")
            for warning in self.warnings:
                lines.append(f"  ! {warning}")

        if not self.changes:
            lines.append("\nNijedna izmena nije bila potrebna.")

        return "\n".join(lines)
