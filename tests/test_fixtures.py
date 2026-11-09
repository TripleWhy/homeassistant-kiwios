"""Guard the captured payloads that ship with the tests."""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any

# Serial numbers of the form HSR + 16 upper case characters, as printed on the
# device. The fixtures must only contain the anonymised placeholder.
SERIAL_PATTERN = r"HSR[A-Z0-9]{16}"
PLACEHOLDER_SERIAL = "HSR" + "0" * 16
IPV4_PATTERN = r"\b\d{1,3}(?:\.\d{1,3}){3}\b"
# RFC 5737 documentation range, used for the anonymised device address.
DOCUMENTATION_NETWORK = ipaddress.ip_network("192.0.2.0/24")
VERSION_KEY_PATTERN = re.compile("version", re.IGNORECASE)
# Real node identifiers are random UUIDs; the fixtures only carry placeholders.
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
PLACEHOLDER_UUID_PREFIX = "00000000-0000-4000-8000-"
# The location of the installation is personal data.
LOCATION_PLACEHOLDERS = {"city": "Musterstadt", "postalCode": "00000"}


def _string_values(node: Any, *, in_version: bool = False) -> list[str]:
    """Return every string value, skipping the contents of version fields.

    Firmware versions such as ``10.26.32.2`` are dotted quads that look exactly
    like a private address, so the address check has to ignore them.
    """
    if isinstance(node, dict):
        return [
            value
            for key, child in node.items()
            for value in _string_values(
                child, in_version=in_version or bool(VERSION_KEY_PATTERN.search(key))
            )
        ]
    if isinstance(node, list):
        return [
            value
            for child in node
            for value in _string_values(child, in_version=in_version)
        ]
    if isinstance(node, str) and not in_version:
        return [node]
    return []


def _location_values(payloads: list[Any]) -> dict[str, Any]:
    """Return the location fields of every thing, as recorded."""
    return {
        key: value
        for payload in payloads
        for thing in payload
        if isinstance(thing, dict)
        for key, value in (thing.get("config") or {}).items()
        if key in LOCATION_PLACEHOLDERS
    }


def test_captured_payloads_are_anonymised(
    things: list[dict[str, Any]],
    json_items: list[dict[str, Any]],
    edge_things: list[dict[str, Any]],
    edge_gateway_info: dict[str, Any],
    edge_energy_overview: dict[str, Any],
    edge_power_indicators: list[dict[str, Any]],
    edge_pv_plants: list[dict[str, Any]],
) -> None:
    """The recorded API responses contain no real serials or LAN addresses."""
    blob = json.dumps(
        [
            things,
            json_items,
            edge_things,
            edge_gateway_info,
            edge_energy_overview,
            edge_power_indicators,
            edge_pv_plants,
        ]
    )

    assert set(re.findall(SERIAL_PATTERN, blob)) == {PLACEHOLDER_SERIAL}

    values = [
        value
        for payload in (
            things,
            json_items,
            edge_things,
            edge_gateway_info,
            edge_energy_overview,
            edge_power_indicators,
            edge_pv_plants,
        )
        for value in _string_values(payload)
    ]

    assert all(
        uuid.startswith(PLACEHOLDER_UUID_PREFIX)
        for uuid in re.findall(UUID_PATTERN, blob)
    ), "captured payload contains a real node identifier"

    for address in set(re.findall(IPV4_PATTERN, " ".join(values))):
        parsed = ipaddress.ip_address(address)
        assert (
            parsed in DOCUMENTATION_NETWORK or not parsed.is_private
        ), f"captured payload contains the private address {address}"
