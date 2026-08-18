"""Low-level rad nad run-ovima, fontovima i svojstvima pasusa.

Ovde su sabrane sve zamke python-docx-a koje inače tiho proizvedu pogrešan
rezultat:

* `paragraph.runs` **ne** obuhvata run-ove unutar `w:hyperlink`, pa linkovi u
  literaturi ostanu u fontu koji im je zatekao dokument.
* `run.font.name` postavlja samo `w:ascii` i `w:hAnsi`; `w:cs` ostaje netaknut,
  što se vidi na ćirilici i drugim kompleksnim pismima.
* Veliko slovo se dobija `w:caps` svojstvom, ne prepisivanjem teksta -- tekst
  dokumenta se u ovoj aplikaciji nikad ne menja.
"""

from __future__ import annotations

import re
from typing import Iterator

from docx.oxml.ns import qn
from docx.shared import Cm, Length, Pt
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from ..report import Change
from ..rules import Alignment, Casing

_WD_ALIGNMENT = {
    Alignment.LEFT: 0,
    Alignment.CENTER: 1,
    Alignment.RIGHT: 2,
    Alignment.JUSTIFY: 3,
}

_ALIGNMENT_NAME = {value: key.value for key, value in _WD_ALIGNMENT.items()}

_URL_PATTERN = re.compile(r"https?://|www\.|doi\.org|doi:", re.IGNORECASE)


# --------------------------------------------------------------------------
# Run-ovi
# --------------------------------------------------------------------------


def iter_runs(paragraph: Paragraph) -> Iterator[Run]:
    """Svi run-ovi pasusa, uključujući one unutar hyperlink-ova."""
    yield from paragraph.runs
    for hyperlink in paragraph.hyperlinks:
        yield from hyperlink.runs


def is_link_run(run: Run) -> bool:
    """Run koji nosi URL ili DOI.

    Zabrana kurziva u telu teksta ne odnosi se na bibliografske linkove -- oni
    su često kurzivni po citatnom stilu, a ne po formatiranju pasusa.
    """
    return bool(_URL_PATTERN.search(run.text or ""))


def set_complex_script_font(run: Run, name: str) -> None:
    """`w:cs` uz `w:ascii`/`w:hAnsi` koje postavlja `run.font.name`."""
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = r_pr.makeelement(qn("w:rFonts"), {})
        r_pr.append(r_fonts)
    r_fonts.set(qn("w:cs"), name)


def get_caps(run: Run) -> bool | None:
    r_pr = run._element.rPr
    if r_pr is None:
        return None
    caps = r_pr.find(qn("w:caps"))
    if caps is None:
        return None
    value = caps.get(qn("w:val"))
    return value not in ("0", "false")


def set_caps(run: Run, value: bool) -> None:
    """Veliko slovo kao svojstvo prikaza, bez diranja karaktera."""
    run.font.all_caps = value


# --------------------------------------------------------------------------
# Primena vrednosti uz beleženje izmene
# --------------------------------------------------------------------------


def _pt_value(value: Length | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Length):
        return round(value.pt, 2)
    return round(float(value), 2)


def _cm_value(value: Length | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Length):
        return round(value.cm, 3)
    return round(float(value), 3)


def apply_run_format(
    run: Run,
    *,
    font_name: str | None = None,
    size_pt: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    caps: bool | None = None,
    context: dict | None = None,
) -> list[Change]:
    """Postavlja samo ono što je zadato; `None` znači "ne diraj"."""
    changes: list[Change] = []
    ctx = context or {}

    def record(path: str, before, after) -> None:
        if before == after:
            return
        changes.append(Change(kind="style", rule_path=path, before=before, after=after, **ctx))

    if font_name is not None:
        record("font.name", run.font.name, font_name)
        run.font.name = font_name
        set_complex_script_font(run, font_name)

    if size_pt is not None:
        record("font.size_pt", _pt_value(run.font.size), round(float(size_pt), 2))
        run.font.size = Pt(float(size_pt))

    if bold is not None:
        record("font.bold", run.font.bold, bold)
        run.font.bold = bold

    if italic is not None:
        record("font.italic", run.font.italic, italic)
        run.font.italic = italic

    if caps is not None:
        record("font.all_caps", get_caps(run), caps)
        set_caps(run, caps)

    return changes


def apply_paragraph_format(
    paragraph: Paragraph,
    *,
    alignment: Alignment | None = None,
    line_spacing: float | None = None,
    space_before_pt: float | None = None,
    space_after_pt: float | None = None,
    first_line_indent_cm: float | None = None,
    left_indent_cm: float | None = None,
    hanging_indent_cm: float | None = None,
    page_break_before: bool | None = None,
    keep_with_next: bool | None = None,
    context: dict | None = None,
) -> list[Change]:
    changes: list[Change] = []
    fmt = paragraph.paragraph_format
    ctx = context or {}

    def record(path: str, before, after) -> None:
        if before == after:
            return
        changes.append(Change(kind="style", rule_path=path, before=before, after=after, **ctx))

    if alignment is not None:
        target = _WD_ALIGNMENT[alignment]
        current = int(fmt.alignment) if fmt.alignment is not None else None
        if current != target:
            # Poređenje ide po numeričkoj vrednosti (WD_ALIGN_PARAGRAPH), a
            # zapis po imenu -- da izveštaj bude čitljiv.
            record("paragraph.alignment", _ALIGNMENT_NAME.get(current), alignment.value)
            fmt.alignment = target

    if line_spacing is not None:
        current = fmt.line_spacing
        current_value = _pt_value(current) if isinstance(current, Length) else current
        record("paragraph.line_spacing", current_value, line_spacing)
        fmt.line_spacing = line_spacing

    if space_before_pt is not None:
        record("paragraph.space_before_pt", _pt_value(fmt.space_before), round(float(space_before_pt), 2))
        fmt.space_before = Pt(float(space_before_pt))

    if space_after_pt is not None:
        record("paragraph.space_after_pt", _pt_value(fmt.space_after), round(float(space_after_pt), 2))
        fmt.space_after = Pt(float(space_after_pt))

    if first_line_indent_cm is not None:
        record("paragraph.first_line_indent_cm", _cm_value(fmt.first_line_indent), round(float(first_line_indent_cm), 3))
        fmt.first_line_indent = Cm(float(first_line_indent_cm))

    if hanging_indent_cm is not None:
        # Viseći uvlak: levi uvlak pomeren udesno, prvi red vraćen ulevo.
        record("paragraph.left_indent_cm", _cm_value(fmt.left_indent), round(float(hanging_indent_cm), 3))
        fmt.left_indent = Cm(float(hanging_indent_cm))
        fmt.first_line_indent = Cm(float(-hanging_indent_cm))
    elif left_indent_cm is not None:
        record("paragraph.left_indent_cm", _cm_value(fmt.left_indent), round(float(left_indent_cm), 3))
        fmt.left_indent = Cm(float(left_indent_cm))

    if page_break_before is not None:
        record("paragraph.page_break_before", fmt.page_break_before, page_break_before)
        fmt.page_break_before = page_break_before

    if keep_with_next is not None:
        record("paragraph.keep_with_next", fmt.keep_with_next, keep_with_next)
        fmt.keep_with_next = keep_with_next

    return changes


def caps_for(casing: Casing | None) -> bool | None:
    """Prevod `casing` pravila u `w:caps`.

    `SENTENCE` se namerno ne prevodi ni u šta: napisati rečenično veliko slovo
    značilo bi prepisati tekst, a to je izvan onoga što ova aplikacija radi.
    """
    if casing is Casing.UPPERCASE:
        return True
    if casing is Casing.AS_IS:
        return False
    return None


# --------------------------------------------------------------------------
# Sekcije
# --------------------------------------------------------------------------


def enable_mirror_margins(section) -> bool:
    """`w:mirrorMargins` -- python-docx za ovo nema API."""
    sect_pr = section._sectPr
    if sect_pr.find(qn("w:mirrorMargins")) is not None:
        return False
    element = sect_pr.makeelement(qn("w:mirrorMargins"), {})
    sect_pr.append(element)
    return True


def has_mirror_margins(section) -> bool:
    return section._sectPr.find(qn("w:mirrorMargins")) is not None
