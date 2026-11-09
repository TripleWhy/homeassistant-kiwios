"""Tests for the integration manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from custom_components.kiwios.const import DOMAIN

from homeassistant.core import HomeAssistant
from homeassistant import loader

COMPONENTS_DIR = Path(__file__).parent.parent / "custom_components"
ALIAS_DOMAIN = "ampere_iq_smartbox"


def load_manifest(domain: str) -> dict[str, Any]:
    """Return the manifest of a bundled integration."""
    return json.loads((COMPONENTS_DIR / domain / "manifest.json").read_text())


def test_kiwios_manifest() -> None:
    """The real integration is named after the software it talks to."""
    manifest = load_manifest(DOMAIN)

    assert DOMAIN == "kiwios"
    assert manifest["domain"] == DOMAIN
    assert manifest["name"] == "KiwiOS"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_polling"


def test_ampere_iq_smartbox_is_a_virtual_integration() -> None:
    """The product name is a code-less alias for the KiwiOS integration."""
    manifest = load_manifest(ALIAS_DOMAIN)

    assert manifest["domain"] == ALIAS_DOMAIN
    assert manifest["name"] == "EKD Ampere.IQ Smartbox"
    assert manifest["integration_type"] == "virtual"
    assert manifest["supported_by"] == DOMAIN
    # Home Assistant refuses to load a custom integration without a version,
    # virtual integrations included.
    assert manifest["version"]

    # A virtual integration is only a manifest, so it must not ship any code.
    assert [path.name for path in (COMPONENTS_DIR / ALIAS_DOMAIN).iterdir()] == [
        "manifest.json"
    ]


async def test_alias_is_loadable_by_home_assistant(hass: HomeAssistant) -> None:
    """Home Assistant resolves the alias manifest without a custom integration."""
    integration = await loader.async_get_integration(hass, ALIAS_DOMAIN)

    assert integration.domain == ALIAS_DOMAIN
    assert integration.integration_type == "virtual"
    assert integration.manifest["supported_by"] == DOMAIN
    assert integration.config_flow is False


def test_virtual_integration_points_at_a_bundled_integration() -> None:
    """The alias must not point at a domain that is not installed."""
    supported_by = load_manifest(ALIAS_DOMAIN)["supported_by"]

    assert (COMPONENTS_DIR / supported_by / "manifest.json").is_file()
    assert load_manifest(supported_by)["domain"] == supported_by
