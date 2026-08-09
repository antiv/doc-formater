"""Translations for everything a user reads.

Catalogues live as JSON in `locales/`, one file per language, so adding a
language means adding a file — no code change. `en.json` is the source of
truth; a key missing from another catalogue falls back to English rather than
raising, so a half-finished translation degrades instead of breaking the app.

The active language is a `ContextVar`, not a module global. Streamlit runs each
browser session's script in its own thread, so a global would let one visitor's
language choice leak into another's page.
"""

from __future__ import annotations

import json
import re
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

DEFAULT_LANGUAGE = "en"

# Native names, shown in the language picker. A user who lands on a page in a
# language they do not read still has to recognise their own.
LANGUAGE_NAMES = {
    "en": "English",
    "sr": "Srpski",
    "fr": "Français",
    "de": "Deutsch",
}

_current: ContextVar[str] = ContextVar("language", default=DEFAULT_LANGUAGE)


@lru_cache(maxsize=None)
def _catalogue(language: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{language}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A broken catalogue must not take the app down; English still works.
        return {}


@lru_cache(maxsize=1)
def available_languages() -> tuple[str, ...]:
    """Languages with a catalogue on disk, English first."""
    found = {p.stem for p in LOCALES_DIR.glob("*.json")}
    ordered = [DEFAULT_LANGUAGE] + sorted(found - {DEFAULT_LANGUAGE})
    return tuple(code for code in ordered if code in found or code == DEFAULT_LANGUAGE)


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


# --------------------------------------------------------------------------
# Active language
# --------------------------------------------------------------------------


def set_language(code: str) -> str:
    """Set the language for the current session; returns what was applied."""
    resolved = code if code in available_languages() else DEFAULT_LANGUAGE
    _current.set(resolved)
    return resolved


def get_language() -> str:
    return _current.get()


def negotiate(accept_language: str | None) -> str:
    """Best match for an HTTP `Accept-Language` header.

    Only the primary subtag is compared (`sr-Latn-RS` → `sr`), which is enough
    for the languages offered here, and quality values are honoured so that a
    browser preferring German over English gets German.
    """
    if not accept_language:
        return DEFAULT_LANGUAGE

    candidates: list[tuple[float, str]] = []
    for part in accept_language.split(","):
        piece = part.strip()
        if not piece:
            continue
        tag, _, params = piece.partition(";")
        quality = 1.0
        match = re.search(r"q\s*=\s*([0-9.]+)", params)
        if match:
            try:
                quality = float(match.group(1))
            except ValueError:
                quality = 0.0
        primary = tag.strip().split("-")[0].lower()
        if primary in available_languages():
            candidates.append((quality, primary))

    if not candidates:
        return DEFAULT_LANGUAGE
    # `max` keeps the first of equal-quality entries, which is header order.
    return max(candidates, key=lambda item: item[0])[1]


# --------------------------------------------------------------------------
# Lookup
# --------------------------------------------------------------------------


def t(key: str, /, **params) -> str:
    """Translate `key` into the active language.

    Falls back to English, then to the key itself, so a missing translation is
    visible in the UI as a bare key rather than a crash. Placeholders use
    `str.format`; a mismatched placeholder returns the unformatted text instead
    of raising, for the same reason.
    """
    language = get_language()
    template = _catalogue(language).get(key)
    if template is None:
        template = _catalogue(DEFAULT_LANGUAGE).get(key, key)
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


def missing_keys(language: str) -> list[str]:
    """Keys present in English but absent from `language` — used by tests."""
    english = set(_catalogue(DEFAULT_LANGUAGE))
    return sorted(english - set(_catalogue(language)))


def extra_keys(language: str) -> list[str]:
    """Keys in `language` that English does not have — stale after a rename."""
    english = set(_catalogue(DEFAULT_LANGUAGE))
    return sorted(set(_catalogue(language)) - english)


def reload_catalogues() -> None:
    """Drop caches; for tests and for editing locales without a restart."""
    _catalogue.cache_clear()
    available_languages.cache_clear()
