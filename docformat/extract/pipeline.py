"""Orkestracija ekstrakcije: Mate -> validacija -> verifikacija citata -> fallback.

Ekstrakcija je najnepouzdaniji korak u lancu, pa svaki izlaz nosi oznaku
porekla (`Evidence.source`) i pouzdanosti, a UI ih prikazuje pre primene.
Ništa se ne primenjuje na dokument bez korisnikove potvrde.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from ..library import RuleLibrary, new_rule_set, suggest_display_name
from ..rules import (
    Evidence,
    FormattingRules,
    Institution,
    RuleSet,
    get_by_path,
    set_by_path,
)
from . import heuristic
from .mate_client import MateClient, MateError, MateSession
from .prompt import build_extract_payload, build_identify_payload, build_repair_payload
from .source import RulesDocument

# Udeo reči citata koje moraju postojati u izvoru da bi pravilo preživelo.
_WEAK_QUOTE_THRESHOLD = 0.60
_STRONG_QUOTE_THRESHOLD = 0.90


@dataclass
class ExtractionOutcome:
    rule_set: RuleSet
    source: str  # "mate" | "heuristic" | "empty"
    warnings: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Parsiranje odgovora
# --------------------------------------------------------------------------


def parse_json_reply(reply: str) -> dict:
    """JSON iz odgovora agenta, tolerantno na ograde i propratni tekst.

    Instrukcija traži čist JSON, ali modeli kroz 50+ provajdera različito
    poštuju tu obavezu, pa se ovde čisti umesto da poziv padne.
    """
    text = reply.strip()

    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Odgovor nije ispravan JSON: {exc}") from exc

    raise ValueError("Odgovor ne sadrži JSON objekat.")


# --------------------------------------------------------------------------
# Verifikacija citata
# --------------------------------------------------------------------------


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_quote(quote: str, source_normalized: str) -> str:
    """`"strong"` | `"weak"` | `"missing"`.

    Doslovno poklapanje je jedini pouzdan signal, ali PDF ekstrakcija prelama
    redove drugačije nego što ih model prepiše, pa bi binarna provera odbacila
    i tačna pravila. Zato se delimično poklapanje po rečima zadržava sa
    sniženom pouzdanošću, a odbacuje tek ono što izgleda izmišljeno.
    """
    normalized = _normalize_ws(quote)
    if not normalized:
        return "missing"
    if normalized in source_normalized:
        return "strong"

    words = [w for w in re.findall(r"\w+", normalized) if len(w) > 3]
    if not words:
        return "missing"
    present = sum(1 for w in words if w in source_normalized) / len(words)
    if present >= _STRONG_QUOTE_THRESHOLD:
        return "weak"
    if present >= _WEAK_QUOTE_THRESHOLD:
        return "weak"
    return "missing"


def apply_quote_verification(
    rules: FormattingRules,
    evidence: list[Evidence],
    document: RulesDocument,
) -> tuple[list[Evidence], list[str]]:
    """Obara polja čiji citat ne postoji u izvoru; vraća (dokazi, odbačeni)."""
    source_normalized = _normalize_ws(document.plain_text)
    kept: list[Evidence] = []
    rejected: list[str] = []

    for item in evidence:
        verdict = verify_quote(item.quote, source_normalized)
        if verdict == "missing":
            rejected.append(item.field_path)
            try:
                if get_by_path(rules, item.field_path) is not None:
                    set_by_path(rules, item.field_path, None)
            except AttributeError:
                # Putanja koja ne postoji u modelu (npr. "headings") -- dokaz se
                # odbacuje, ali vrednost se ne dira jer nije skalarno polje.
                pass
            continue
        if verdict == "weak" and item.confidence == "high":
            item.confidence = "medium"
        kept.append(item)

    return kept, rejected


# --------------------------------------------------------------------------
# Koraci
# --------------------------------------------------------------------------


def identify_institution(
    document: RulesDocument,
    client: MateClient | None = None,
) -> tuple[Institution, str]:
    """(institucija, poreklo). Nikad ne baca -- pada na heuristiku."""
    if client is not None:
        try:
            session = MateSession(client, discriminator=f"identify::{document.filename}")
            reply = session.send(build_identify_payload(document))
            data = parse_json_reply(reply)
            institution = Institution.model_validate(data.get("institution", data))
            if any(institution.model_dump().values()):
                return institution, "mate"
        except (MateError, ValueError, Exception):
            pass
    return heuristic.extract_institution(document.head(pages=2).plain_text), "heuristic"


def _extract_via_mate(
    document: RulesDocument,
    client: MateClient,
    on_progress: Callable[[str], None],
) -> tuple[FormattingRules, list[Evidence], list[str]]:
    session = MateSession(client, discriminator=f"extract::{document.filename}")

    on_progress("Šaljem pravilnik Mate agentu…")
    reply = session.send(build_extract_payload(document))

    for attempt in (1, 2):
        try:
            data = parse_json_reply(reply)
            rules = FormattingRules.model_validate(data.get("rules", {}))
            evidence = [Evidence.model_validate(e) for e in data.get("evidence", [])]
            for item in evidence:
                item.source = "mate"
            unresolved = [str(u) for u in data.get("unresolved", [])]
            return rules, evidence, unresolved
        except Exception as exc:
            if attempt == 2:
                raise MateError(f"Agent nije vratio upotrebljiv JSON: {exc}") from exc
            on_progress("Odgovor nije prošao validaciju — tražim ispravku…")
            reply = session.send(build_repair_payload(str(exc)))

    raise MateError("Ekstrakcija nije uspela.")  # pragma: no cover


def extract_rule_set(
    document: RulesDocument,
    client: MateClient | None = None,
    library: RuleLibrary | None = None,
    display_name: str | None = None,
    institution: Institution | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> ExtractionOutcome:
    """Pun lanac ekstrakcije nad jednim pravilnikom."""
    progress = on_progress or (lambda _msg: None)
    warnings: list[str] = []

    if institution is None:
        institution, origin = identify_institution(document, client)
        if origin == "heuristic" and client is not None:
            warnings.append("Instituciju je prepoznala heuristika, ne agent.")

    rules: FormattingRules
    evidence: list[Evidence]
    unresolved: list[str]
    source = "empty"

    if client is not None:
        try:
            rules, evidence, unresolved = _extract_via_mate(document, client, progress)
            source = "mate"
        except MateError as exc:
            warnings.append(f"Mate nije upotrebljen: {exc}")
            progress("Prelazim na regex heuristiku…")
            rules, evidence, unresolved = heuristic.extract_rules(document.plain_text)
            source = "heuristic"
    else:
        progress("Mate nije konfigurisan — koristim regex heuristiku…")
        rules, evidence, unresolved = heuristic.extract_rules(document.plain_text)
        source = "heuristic"

    rejected: list[str] = []
    if source == "mate":
        evidence, rejected = apply_quote_verification(rules, evidence, document)
        if rejected:
            warnings.append(
                f"Odbačeno {len(rejected)} pravila jer im se citat ne nalazi u pravilniku: "
                + ", ".join(rejected)
            )
            unresolved = sorted(set(unresolved) | set(rejected))

    rule_set = new_rule_set(
        display_name=display_name or suggest_display_name(institution),
        institution=institution,
        library=library,
        origin="extracted",
        source_filename=document.filename,
    )
    rule_set.rules = rules
    rule_set.evidence = evidence
    rule_set.unresolved = unresolved

    progress("Ekstrakcija završena.")
    return ExtractionOutcome(
        rule_set=rule_set, source=source, warnings=warnings, rejected=rejected
    )
