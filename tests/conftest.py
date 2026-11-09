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


@pytest.fixture
def edge_things() -> list[dict[str, Any]]:
    """Return the captured /rest/hems-configurator/things payload."""
    return json.loads((FIXTURES_DIR / "edge_things.json").read_text())


@pytest.fixture
def edge_gateway_info() -> dict[str, Any]:
    """Return the captured /rest/hems-configurator/public/gateway/info payload."""
    return json.loads((FIXTURES_DIR / "edge_gateway_info.json").read_text())


@pytest.fixture
def edge_energy_overview() -> dict[str, Any]:
    """Return the captured /rest/hems-configurator/energy-overview payload."""
    return json.loads((FIXTURES_DIR / "edge_energy_overview.json").read_text())


@pytest.fixture
def edge_power_indicators() -> list[dict[str, Any]]:
    """Return the captured /rest/hems-configurator/power-indicator payload."""
    return json.loads((FIXTURES_DIR / "edge_power_indicators.json").read_text())


@pytest.fixture
def edge_pv_plants() -> list[dict[str, Any]]:
    """Return the captured /rest/hems-configurator/pv-plants payload."""
    return json.loads((FIXTURES_DIR / "edge_pv_plants.json").read_text())
