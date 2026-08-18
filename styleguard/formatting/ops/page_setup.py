"""Postavke strane: format, margine, zrcalni robovi, numeracija."""

from __future__ import annotations

from docx.document import Document as DocxDocument
from docx.enum.section import WD_SECTION_START
from docx.shared import Cm

from ...report import Change
from ...rules import FormattingRules
from ..runs import enable_mirror_margins, has_mirror_margins

# ISO 216 A4, u centimetrima.
_A4_CM = (21.0, 29.7)
_LETTER_CM = (21.59, 27.94)


def apply(document: DocxDocument, infos, rules: FormattingRules) -> list[Change]:
    setup = rules.page_setup
    changes: list[Change] = []

    for index, section in enumerate(document.sections):
        ctx = {"paragraph_index": None, "section": f"sekcija {index + 1}"}

        if setup.paper_size is not None:
            width_cm, height_cm = _A4_CM if setup.paper_size == "A4" else _LETTER_CM
            _set_length(section, "page_width", Cm(width_cm), "page_setup.page_width_cm", changes, ctx)
            _set_length(section, "page_height", Cm(height_cm), "page_setup.page_height_cm", changes, ctx)

        margins = setup.margins_cm
        # Kod zrcalnih robova Word i dalje čita `left` kao unutrašnji i `right`
        # kao spoljašnji rob; `w:mirrorMargins` samo menja njihovo tumačenje na
        # parnim stranama.
        _set_length(section, "top_margin", _cm(margins.top), "page_setup.margins_cm.top", changes, ctx)
        _set_length(section, "bottom_margin", _cm(margins.bottom), "page_setup.margins_cm.bottom", changes, ctx)
        _set_length(section, "left_margin", _cm(margins.inside), "page_setup.margins_cm.inside", changes, ctx)
        _set_length(section, "right_margin", _cm(margins.outside), "page_setup.margins_cm.outside", changes, ctx)

        if setup.mirror_margins is True and not has_mirror_margins(section):
            enable_mirror_margins(section)
            changes.append(
                Change(kind="style", rule_path="page_setup.mirror_margins",
                       before=False, after=True, **ctx)
            )

        if setup.different_first_page is not None:
            current = bool(section.different_first_page_header_footer)
            if current != setup.different_first_page:
                section.different_first_page_header_footer = setup.different_first_page
                changes.append(
                    Change(kind="style", rule_path="page_setup.different_first_page",
                           before=current, after=setup.different_first_page, **ctx)
                )

    return changes


def _cm(value: float | None):
    return Cm(float(value)) if value is not None else None


def _read_cm(section, attribute: str) -> float | None:
    """Trenutna vrednost u centimetrima, ili None ako je nečitljiva.

    Dokumenti iz nekih generatora upisuju razlomljene twips vrednosti
    (`w:right="1699.1999999999998"`), na kojima python-docx puca pri čitanju.
    Nečitljiva zatečena vrednost nije razlog da formatiranje stane -- upisuje
    se ispravna i beleži da prethodna nije bila poznata.
    """
    try:
        current = getattr(section, attribute)
    except (ValueError, TypeError):
        return None
    return round(current.cm, 3) if current is not None else None


def _set_length(section, attribute: str, value, rule_path: str, changes: list[Change], ctx: dict) -> None:
    if value is None:
        return
    current_cm = _read_cm(section, attribute)
    target_cm = round(value.cm, 3)
    if current_cm == target_cm:
        return
    setattr(section, attribute, value)
    changes.append(
        Change(kind="style", rule_path=rule_path, before=current_cm, after=target_cm, **ctx)
    )
