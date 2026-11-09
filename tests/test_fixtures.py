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


def test_captured_payloads_are_anonymised(
    things: list[dict[str, Any]], json_items: list[dict[str, Any]]
) -> None:
    """The recorded API responses contain no real serials or LAN addresses."""
    blob = json.dumps([things, json_items])

    assert set(re.findall(SERIAL_PATTERN, blob)) == {PLACEHOLDER_SERIAL}

    for address in set(re.findall(IPV4_PATTERN, blob)):
        parsed = ipaddress.ip_address(address)
        assert parsed in DOCUMENTATION_NETWORK or not parsed.is_private, (
            f"captured payload contains the private address {address}"
        )
