"""Fixtures for testing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "test_data"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    return


@pytest.fixture
def things() -> list[dict[str, Any]]:
    """Return the captured /rest/things payload."""
    return json.loads((FIXTURES_DIR / "things.json").read_text())


@pytest.fixture
def json_items() -> list[dict[str, Any]]:
    """Return the captured /rest/items payload."""
    return json.loads((FIXTURES_DIR / "items.json").read_text())
