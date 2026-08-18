"""Modeli pravila formatiranja.

Centralno pravilo ovog modula: `None` znači "pravilnik o ovome ne govori --
ne diraj". To nije isto što i `0`. Engine sme da menja isključivo ona svojstva
koja su u pravilima eksplicitno postavljena, pa `Optional[...] = None` nije
lenjost nego nosilac značenja.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import types
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field


class Alignment(str, Enum):
    LEFT = "LEFT"
    CENTER = "CENTER"
    RIGHT = "RIGHT"
    JUSTIFY = "JUSTIFY"


class Casing(str, Enum):
    UPPERCASE = "UPPERCASE"
    SENTENCE = "SENTENCE"
    AS_IS = "AS_IS"


class CaptionPosition(str, Enum):
    ABOVE = "ABOVE"
    BELOW = "BELOW"


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", use_enum_values=False, validate_assignment=True)


# --------------------------------------------------------------------------
# Identitet seta pravila
# --------------------------------------------------------------------------


class Institution(_Model):
    """Nosilac pravilnika. Vozi matchovanje u biblioteci."""

    university: str | None = None
    faculty: str | None = None
    department: str | None = None
    organization: str | None = None
    document_type: str | None = None
    language: str | None = None


class RuleSetMeta(_Model):
    id: str
    display_name: str
    institution: Institution = Field(default_factory=Institution)
    source_filename: str | None = None
    # Email vlasnika. `None` znači set bez vlasnika -- ugrađeni preset ili set
    # nastao pre uvođenja vlasništva; takve menja samo admin.
    owner: str | None = None
    owner_name: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    origin: Literal["extracted", "manual", "copied"] = "manual"
    copied_from: str | None = None


# --------------------------------------------------------------------------
# Pravila formatiranja
# --------------------------------------------------------------------------


class MarginsCm(_Model):
    top: float | None = None
    bottom: float | None = None
    inside: float | None = None
    outside: float | None = None


class PageNumbering(_Model):
    position: Literal["bottom_center", "bottom_right", "bottom_left", "top_center", "top_right"] | None = None
    start_at_section: str | None = None


class PageSetup(_Model):
    paper_size: Literal["A4", "Letter"] | None = None
    mirror_margins: bool | None = None
    margins_cm: MarginsCm = Field(default_factory=MarginsCm)
    different_first_page: bool | None = None
    page_numbering: PageNumbering = Field(default_factory=PageNumbering)


class Typography(_Model):
    font_family: str | None = None
    fallback_fonts: list[str] = Field(default_factory=list)


class BodyText(_Model):
    size_pt: float | None = None
    line_spacing: float | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    alignment: Alignment | None = None
    first_line_indent_cm: float | None = None
    allow_italic: bool | None = None
    allow_empty_paragraphs: bool | None = None


class HeadingLevel(_Model):
    level: int
    size_pt: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    casing: Casing | None = None
    alignment: Alignment | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    page_break_before: bool | None = None
    keep_with_next: bool | None = None


class CaptionRule(_Model):
    position: CaptionPosition | None = None
    alignment: Alignment | None = None
    size_pt: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    keep_with_next: bool | None = None


class Captions(_Model):
    figure: CaptionRule = Field(default_factory=CaptionRule)
    table: CaptionRule = Field(default_factory=CaptionRule)
    source_line: CaptionRule = Field(default_factory=CaptionRule)


class Bibliography(_Model):
    title: str | None = None
    size_pt: float | None = None
    line_spacing: float | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    hanging_indent_cm: float | None = None
    alignment: Alignment | None = None
    page_break_before: bool | None = None


class TableOfContents(_Model):
    title: str | None = None
    insert_field: bool | None = None
    levels: int | None = None


class Tables(_Model):
    alignment: Alignment | None = None
    header_row_bold: bool | None = None
    header_row_repeat: bool | None = None
    cell_size_pt: float | None = None
    cell_line_spacing: float | None = None
    cell_space_before_pt: float | None = None
    cell_space_after_pt: float | None = None


class SectionKeywords(_Model):
    """Naslovi poglavlja onako kako ih pravilnik imenuje.

    Ovo vozi klasifikaciju sekcija u `analyze.structure`. Bez ovoga detekcija
    pada na Word outline i numeraciju.
    """

    front_matter: list[str] = Field(default_factory=list)
    body_start: list[str] = Field(default_factory=list)
    bibliography: list[str] = Field(default_factory=list)
    appendix: list[str] = Field(default_factory=list)


class StructureProfile(_Model):
    language: str | None = None
    section_keywords: SectionKeywords = Field(default_factory=SectionKeywords)
    figure_caption_prefixes: list[str] = Field(default_factory=list)
    table_caption_prefixes: list[str] = Field(default_factory=list)
    source_line_prefixes: list[str] = Field(default_factory=list)


class FormattingRules(_Model):
    page_setup: PageSetup = Field(default_factory=PageSetup)
    typography: Typography = Field(default_factory=Typography)
    body: BodyText = Field(default_factory=BodyText)
    headings: list[HeadingLevel] = Field(default_factory=list)
    captions: Captions = Field(default_factory=Captions)
    bibliography: Bibliography = Field(default_factory=Bibliography)
    toc: TableOfContents = Field(default_factory=TableOfContents)
    tables: Tables = Field(default_factory=Tables)
    structure_profile: StructureProfile = Field(default_factory=StructureProfile)

    def heading(self, level: int) -> HeadingLevel | None:
        """Pravilo za dati nivo naslova, uz pad na najdublji definisani nivo.

        Pravilnici tipično definišu nivoe 1-3 pa kažu "i niže isto"; bez ovog
        pada naslov 2.1.1.1 ostao bi neformatiran.
        """
        exact = [h for h in self.headings if h.level == level]
        if exact:
            return exact[0]
        lower = [h for h in self.headings if h.level < level]
        return max(lower, key=lambda h: h.level) if lower else None


# --------------------------------------------------------------------------
# Dokazi
# --------------------------------------------------------------------------


class Evidence(_Model):
    """Poreklo jednog pravila.

    Drži se odvojeno od `FormattingRules` da bi engine radio sa čistim
    objektom, a UI imao čime da opravda svaku vrednost pred korisnikom.
    """

    field_path: str
    quote: str = ""
    page: int | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    source: Literal["mate", "heuristic", "manual", "preset"] = "manual"


class RuleSet(_Model):
    """Ono što se snima u biblioteku i prosleđuje engine-u."""

    meta: RuleSetMeta
    rules: FormattingRules = Field(default_factory=FormattingRules)
    evidence: list[Evidence] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

    def evidence_for(self, field_path: str) -> Evidence | None:
        for e in self.evidence:
            if e.field_path == field_path:
                return e
        return None


# --------------------------------------------------------------------------
# Pomoćne funkcije
# --------------------------------------------------------------------------


def slugify(value: str) -> str:
    """Stabilan ASCII slug -- koristi se kao id seta i ime fajla."""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    ascii_only = (
        ascii_only.replace("đ", "dj").replace("Đ", "Dj").replace("ð", "dj")
    )
    ascii_only = ascii_only.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "rule-set"


def iter_field_paths(model: BaseModel, prefix: str = "") -> list[tuple[str, Any]]:
    """Ravna lista `(dotted.path, vrednost)` za uređiva polja modela.

    Ugnežđeni modeli se razlažu; liste prostih vrednosti se vraćaju kao celina.
    Liste modela (npr. `headings`) se **izostavljaju** -- generički editor bi ih
    prikazao kao tekst i pri upisu zamenio stringovima, pa im treba namenski
    prikaz.
    """
    out: list[tuple[str, Any]] = []
    for name, value in model.__dict__.items():
        path = f"{prefix}{name}"
        if isinstance(value, BaseModel):
            out.extend(iter_field_paths(value, prefix=f"{path}."))
        elif _is_model_list(type(model), name):
            continue
        else:
            out.append((path, value))
    return out


def _is_model_list(model_type: type[BaseModel], field_name: str) -> bool:
    """Da li je polje lista ugnežđenih modela.

    Gleda se anotacija, a ne sadržaj: prazna `headings` lista je i dalje lista
    modela i ne sme da završi u generičkom editoru.
    """
    field = model_type.model_fields.get(field_name)
    if field is None:
        return False
    return any(
        isinstance(arg, type) and issubclass(arg, BaseModel)
        for arg in get_args(field.annotation)
    )


def field_type_for_path(model: BaseModel, path: str) -> type | None:
    """Osnovni tip polja na datoj putanji (float, bool, str, Enum, list...), ili None.

    Čita se iz anotacije modela, tako da radi i kada je trenutna vrednost None.
    """
    parts = path.split(".")
    current: type[BaseModel] = type(model)
    for part in parts[:-1]:
        field = current.model_fields.get(part)
        if field is None:
            return None
        candidates = [field.annotation, *get_args(field.annotation)]
        submodel = next(
            (
                c for c in candidates
                if isinstance(c, type) and c is not type(None) and issubclass(c, BaseModel)
            ),
            None,
        )
        if submodel is None:
            return None
        current = submodel

    field = current.model_fields.get(parts[-1])
    if field is None:
        return None

    raw = field.annotation
    union_types = (Union, getattr(types, "UnionType", None))
    union_types = tuple(u for u in union_types if u is not None)

    origin = get_origin(raw)
    if origin is not None and origin not in union_types:
        return origin if isinstance(origin, type) else type(origin)

    args = get_args(raw)
    type_candidates = list(args) if args else [raw]

    for candidate in type_candidates:
        if candidate is type(None):
            continue
        cand_origin = get_origin(candidate)
        if cand_origin is not None and cand_origin not in union_types and isinstance(cand_origin, type):
            return cand_origin
        if isinstance(candidate, type):
            try:
                if issubclass(candidate, type(None)):
                    continue
            except TypeError:
                pass
            return candidate
    return None


def enum_type_for_path(model: BaseModel, path: str) -> type[Enum] | None:
    """Enum tip polja na datoj putanji, ili None.

    Čita se iz anotacije, a ne iz trenutne vrednosti: polje koje je `None`
    (jer ga pravilnik ne propisuje) i dalje mora da se prikaže kao izbor, a ne
    kao slobodan tekst -- inače se enum vrati kao string i validacija pukne.
    """
    ftype = field_type_for_path(model, path)
    if ftype is not None and isinstance(ftype, type) and issubclass(ftype, Enum):
        return ftype
    return None


def get_by_path(model: BaseModel, path: str) -> Any:
    current: Any = model
    for part in path.split("."):
        if current is None:
            return None
        current = getattr(current, part, None)
    return current


def set_by_path(model: BaseModel, path: str, value: Any) -> None:
    parts = path.split(".")
    current: Any = model
    for part in parts[:-1]:
        current = getattr(current, part)
    setattr(current, parts[-1], value)


def load_rule_set(path: str | Path) -> RuleSet:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return RuleSet.model_validate(data)


def dump_rule_set(rule_set: RuleSet, path: str | Path) -> None:
    Path(path).write_text(
        rule_set.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )
