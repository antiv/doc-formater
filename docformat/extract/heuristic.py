"""Regex fallback za slučaj kad Mate nije dostupan.

Namerno pokriva samo ono što se u pravilnicima piše stereotipno -- font,
veličinu, prored, margine, poravnanje. Sve pogođeno dobija
`confidence: "low"` i `source: "heuristic"`, da UI eksplicitno traži potvrdu
pre primene; heuristika je most do korisnikovog pregleda, ne zamena za
ekstrakciju.
"""

from __future__ import annotations

import re

from ..rules import Alignment, Evidence, FormattingRules, Institution

# Kontekstne reči po jezicima (sl / sr / hr / en) -- pravilnici mešaju forme.
_BODY_CTX = r"(?:besedil|tekst|telo|tijelo|odstav|pasus|body|paragraph|osnovn)"
_HEADING_CTX = r"(?:naslov|poglavj|heading|title)"
_FONT_NAMES = r"(?:Times New Roman|Arial|Calibri|Cambria|Garamond|Helvetica|Verdana)"


def _clean_quote(line: str, limit: int = 200) -> str:
    line = re.sub(r"\s+", " ", line).strip()
    return line[:limit]


def _num(value: str) -> float:
    return float(value.replace(",", "."))


def extract_institution(text: str) -> Institution:
    """Naziv institucije sa naslovne strane.

    Traži se u prvih nekoliko desetina linija jer naslovna strana skoro uvek
    nosi naziv, a dalje u tekstu se isti nazivi javljaju u citatima.
    """
    institution = Institution()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:80]

    patterns = {
        "university": r"(?:univerz\w*|university)\b",
        "faculty": r"(?:fakultet\w*|faculty|akademij\w*|academy|visok\w*\s+šol\w*|college)\b",
        "department": r"(?:odsek|odsjek|oddelek|katedra|department|smer|smjer)\b",
    }

    for line in lines:
        if len(line) > 120:
            continue
        for field_name, pattern in patterns.items():
            if getattr(institution, field_name):
                continue
            if re.search(pattern, line, re.IGNORECASE):
                setattr(institution, field_name, _clean_quote(line, 120))

    for line in lines:
        if re.search(r"\b(diplomsk\w+|magistrsk\w+|master|master's|doktorsk\w+|seminarsk\w+)\s+"
                     r"(rad|delo|nalog\w*|thesis)\b", line, re.IGNORECASE):
            institution.document_type = _clean_quote(line, 80)
            break

    return institution


def extract_rules(text: str) -> tuple[FormattingRules, list[Evidence], list[str]]:
    rules = FormattingRules()
    evidence: list[Evidence] = []

    def record(path: str, quote: str) -> None:
        evidence.append(
            Evidence(
                field_path=path,
                quote=_clean_quote(quote),
                page=None,
                confidence="low",
                source="heuristic",
            )
        )

    lines = text.splitlines()

    for line in lines:
        low = line.lower()

        # -- font ---------------------------------------------------------
        if rules.typography.font_family is None:
            match = re.search(_FONT_NAMES, line, re.IGNORECASE)
            if match and re.search(r"(?:pisav|font|črk|slova|typeface)", low):
                rules.typography.font_family = match.group(0)
                record("typography.font_family", line)

        # -- veličina tela teksta ------------------------------------------
        if rules.body.size_pt is None:
            match = re.search(
                rf"{_BODY_CTX}[^.\n]{{0,100}}?(\d{{1,2}})\s*(?:pt|tipk|točk|pik)",
                low,
            )
            if not match:
                match = re.search(
                    rf"(\d{{1,2}})\s*(?:pt|tipk|točk|pik)[^.\n]{{0,100}}?{_BODY_CTX}",
                    low,
                )
            if match:
                size = _num(match.group(1))
                if 6 <= size <= 20:
                    rules.body.size_pt = size
                    record("body.size_pt", line)

        # -- prored --------------------------------------------------------
        if rules.body.line_spacing is None:
            match = re.search(
                r"(?:razmi[kc]\w*|razmak|prored|line\s+spacing|medvrsti\w*)"
                r"[^.\n]{0,40}?(\d[.,]\d+|\d)",
                low,
            )
            if match:
                spacing = _num(match.group(1))
                if 0.8 <= spacing <= 3.0:
                    rules.body.line_spacing = spacing
                    record("body.line_spacing", line)
            elif re.search(r"(?:enojn\w*|single)\s+(?:razmi\w*|spacing)", low):
                rules.body.line_spacing = 1.0
                record("body.line_spacing", line)
            elif re.search(r"(?:dvojn\w*|double)\s+(?:razmi\w*|spacing)", low):
                rules.body.line_spacing = 2.0
                record("body.line_spacing", line)

        # -- poravnanje ----------------------------------------------------
        if rules.body.alignment is None and re.search(
            r"(?:obojestransk|obostran|obojstran|poravnan\w*\s+(?:s\s+)?obe|justif)", low
        ):
            rules.body.alignment = Alignment.JUSTIFY
            record("body.alignment", line)

        # -- margine -------------------------------------------------------
        if re.search(r"(?:rob\w*|margin\w*|odmik)", low) and re.search(r"\d", low):
            _apply_margins(line, low, rules, record)

        # -- veličina naslova nivoa 1 --------------------------------------
        if not rules.headings:
            match = re.search(
                rf"{_HEADING_CTX}[^.\n]{{0,100}}?(\d{{1,2}})\s*(?:pt|tipk|točk|pik)", low
            )
            if match:
                size = _num(match.group(1))
                if 8 <= size <= 24:
                    from ..rules import Casing, HeadingLevel

                    bold = bool(re.search(r"(?:krepk|bold|podebljan|masn)", low))
                    caps = bool(re.search(r"(?:velik\w*\s+(?:tiskan|štampan|slov)|uppercase|verzal)", low))
                    rules.headings = [
                        HeadingLevel(
                            level=1,
                            size_pt=size,
                            bold=bold or None,
                            casing=Casing.UPPERCASE if caps else None,
                        )
                    ]
                    record("headings", line)

    unresolved = _unresolved_paths(rules)
    return rules, evidence, unresolved


def _apply_margins(line: str, low: str, rules: FormattingRules, record) -> None:
    """Margine po stranama; podržava i 'sve strane X cm' oblik."""
    side_patterns = {
        "top": r"(?:zgoraj|gore|vrh|top|gornj)",
        "bottom": r"(?:spodaj|dole|dno|bottom|donj)",
        "inside": r"(?:notranj|unutra|inside|inner|lev\w*|left)",
        "outside": r"(?:zunanj|spolja|outside|outer|desn\w*|right)",
    }
    margins = rules.page_setup.margins_cm

    for side, pattern in side_patterns.items():
        if getattr(margins, side) is not None:
            continue
        match = re.search(rf"{pattern}[^.\n]{{0,30}}?(\d+(?:[.,]\d+)?)\s*cm", low)
        if not match:
            match = re.search(rf"(\d+(?:[.,]\d+)?)\s*cm[^.\n]{{0,30}}?{pattern}", low)
        if match:
            value = _num(match.group(1))
            if 0.5 <= value <= 6.0:
                setattr(margins, side, value)
                record(f"page_setup.margins_cm.{side}", line)

    if re.search(r"(?:vse\s+strani|sve\s+strane|all\s+(?:sides|margins))", low):
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*cm", low)
        if match:
            value = _num(match.group(1))
            if 0.5 <= value <= 6.0:
                for side in side_patterns:
                    if getattr(margins, side) is None:
                        setattr(margins, side, value)
                        record(f"page_setup.margins_cm.{side}", line)


def _unresolved_paths(rules: FormattingRules) -> list[str]:
    """Polja koja heuristika po prirodi ne pokriva -- da UI zna šta da traži."""
    candidates = [
        "typography.font_family",
        "body.size_pt",
        "body.line_spacing",
        "body.alignment",
        "body.space_after_pt",
        "body.first_line_indent_cm",
        "page_setup.margins_cm.top",
        "page_setup.margins_cm.bottom",
        "page_setup.margins_cm.inside",
        "page_setup.margins_cm.outside",
        "bibliography.title",
        "toc.title",
    ]
    from ..rules import get_by_path

    missing = [path for path in candidates if get_by_path(rules, path) is None]
    if not rules.headings:
        missing.append("headings")
    return missing
