"""Tests changes to common module."""

import json

from pytest_homeassistant_custom_component.common import load_fixture


def test_load_fixture():
    """Test load fixture."""
    data = json.loads(load_fixture("test_data.json"))
    assert data == {"test_key": "test_value"}
