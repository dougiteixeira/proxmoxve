# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests that localized strings stay consistent with the English reference."""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

TRANSLATIONS_DIR = (
    Path(__file__).parent.parent / "custom_components" / "proxmoxve" / "translations"
)
PLACEHOLDER = re.compile(r"{([a-zA-Z0-9_]+)}")


def _flatten(data, prefix="") -> Iterator[tuple[str, str]]:
    """Yield (dotted key, string value) for every string in a translation file."""
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _flatten(value, name)
        elif isinstance(value, str):
            yield name, value


def _load(language) -> dict[str, str]:
    """Load a translation file as a flat mapping."""
    path = TRANSLATIONS_DIR / f"{language}.json"
    return dict(_flatten(json.loads(path.read_text(encoding="utf-8"))))


LANGUAGES = sorted(
    path.stem for path in TRANSLATIONS_DIR.glob("*.json") if path.stem != "en"
)


@pytest.mark.parametrize("language", LANGUAGES)
def test_placeholders_match_english(language):
    """Home Assistant drops a localized string whose placeholders differ from en."""
    english = _load("en")
    mismatches = {
        key: (
            sorted(PLACEHOLDER.findall(value)),
            sorted(PLACEHOLDER.findall(english[key])),
        )
        for key, value in _load(language).items()
        if key in english
        and set(PLACEHOLDER.findall(value)) != set(PLACEHOLDER.findall(english[key]))
    }
    assert not mismatches


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_unknown_keys(language):
    """A key absent from en.json is a typo: it can never be looked up."""
    english = _load("en")
    assert not [key for key in _load(language) if key not in english]
