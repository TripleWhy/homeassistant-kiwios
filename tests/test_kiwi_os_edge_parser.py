"""Tests for the parser of the aggregated KiwiOS Edge API."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock

import pytest

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower

from custom_components.kiwios.const import DOMAIN
from custom_components.kiwios.kiwi_os_edge_parser import KiwiOsEdgeParser

GATEWAY_SERIAL = "EHC01-000000000"
GATEWAY_DEVICE_ID = "gateway-device-id"


@pytest.fixture
def parser() -> KiwiOsEdgeParser:
    """Return an empty parser."""
    return KiwiOsEdgeParser()


def build(
    parser: KiwiOsEdgeParser,
    *,
    gateway_info: dict[str, Any],
    things: list[dict[str, Any]],
    energy_overview: dict[str, Any],
    power_indicators: list[dict[str, Any]],
    pv_plants: list[dict[str, Any]],
) -> None:
    """Create every entity the way the integration does at setup."""
    parser.parse_gateway(gateway_info, None)
    devices = parser.parse_things(things, None, GATEWAY_DEVICE_ID)
    parser.parse_power_indicators(power_indicators, None, devices)
    parser.parse_pv_plants(pv_plants, None, GATEWAY_DEVICE_ID)
    parser.parse_energy_overview(energy_overview, None)


def sensors_by_name(parser: KiwiOsEdgeParser) -> dict[str, Any]:
    """Index the created entities by name."""
    return {entity._attr_name: entity for entity in parser.get_entities()}


def test_gateway_device_describes_the_box(
    parser: KiwiOsEdgeParser, edge_gateway_info: dict[str, Any]
) -> None:
    """The gateway device carries serial and firmware versions."""
    device_info = parser.parse_gateway(edge_gateway_info, None)

    assert device_info["identifiers"] == {(DOMAIN, GATEWAY_SERIAL)}
    assert device_info["serial_number"] == GATEWAY_SERIAL
    assert device_info["sw_version"] == "4.69.0.51"
    assert device_info["manufacturer"] == "EKD"
    assert device_info["model"] == "Ampere.IQ Smartbox"

    (version_sensor,) = parser.get_entities()
    assert version_sensor._attr_name == "KiwiOS Edge version"
    assert version_sensor._attr_native_value == "10.26.32.2"
    assert version_sensor._attr_entity_category is EntityCategory.DIAGNOSTIC
    assert version_sensor._attr_unique_id == f"{GATEWAY_SERIAL}_edge_version"


def test_gateway_without_identity(parser: KiwiOsEdgeParser) -> None:
    """A device that reports nothing still gets a usable gateway."""
    device_info = parser.parse_gateway({}, None)

    assert device_info["identifiers"] == {(DOMAIN, DOMAIN)}
    assert device_info["serial_number"] is None
    assert device_info["sw_version"] is None

    (version_sensor,) = parser.get_entities()
    assert version_sensor._attr_native_value is None


def test_energy_overview_sensors(
    parser: KiwiOsEdgeParser,
    edge_gateway_info: dict[str, Any],
    edge_energy_overview: dict[str, Any],
) -> None:
    """Every aggregated power flow becomes a power measurement."""
    parser.parse_gateway(edge_gateway_info, None)
    parser.parse_energy_overview(edge_energy_overview, None)

    sensors = sensors_by_name(parser)
    assert "Production" in sensors
    assert "Household consumption" in sensors

    household = sensors["Household consumption"]
    assert household._attr_native_value == 511.0
    assert household._attr_native_unit_of_measurement == UnitOfPower.WATT
    assert household._attr_device_class == SensorDeviceClass.POWER
    assert household._attr_state_class == SensorStateClass.MEASUREMENT
    assert household._attr_unique_id == (
        f"{GATEWAY_SERIAL}_energy_overview_householdConsumption"
    )
    assert household._attr_device_info["identifiers"] == {(DOMAIN, GATEWAY_SERIAL)}


def test_energy_overview_missing_key_is_unknown(
    parser: KiwiOsEdgeParser, edge_gateway_info: dict[str, Any]
) -> None:
    """A power flow the device does not report is unknown, not zero."""
    parser.parse_gateway(edge_gateway_info, None)
    parser.parse_energy_overview({}, None)

    assert sensors_by_name(parser)["Production"]._attr_native_value is None


def test_things_become_devices_with_status(
    parser: KiwiOsEdgeParser,
    edge_gateway_info: dict[str, Any],
    edge_things: list[dict[str, Any]],
) -> None:
    """Every device of the gateway is created and reports its status."""
    parser.parse_gateway(edge_gateway_info, None)
    devices = parser.parse_things(edge_things, None, GATEWAY_DEVICE_ID)

    assert set(devices) == {thing["id"] for thing in edge_things}

    inverter_id = "sajhybrid:inverter:94-HSR0000000000000000"
    inverter = devices[inverter_id]
    assert inverter["name"] == "AMPERE.StoragePro Inverter (HSR0000000000000000)"
    assert inverter["model"] == "Inverter - AMPERE.StoragePro"
    assert inverter["serial_number"] == "HSR0000000000000000"
    assert inverter["via_device_id"] == GATEWAY_DEVICE_ID

    status_sensors = [e for e in parser.get_entities() if e._attr_name == "Status"]
    assert len(status_sensors) == len(edge_things)
    inverter_status = next(
        e for e in status_sensors if e._attr_unique_id == f"{inverter_id}_status"
    )
    assert inverter_status._attr_native_value == "ONLINE"
    assert inverter_status._attr_entity_category is EntityCategory.DIAGNOSTIC


def test_things_without_optional_fields(parser: KiwiOsEdgeParser) -> None:
    """Devices without serial, type or status still produce entities."""
    parser.parse_gateway({"serialNumber": GATEWAY_SERIAL}, None)
    devices = parser.parse_things([{"id": "thing:1"}], None, GATEWAY_DEVICE_ID)

    assert devices["thing:1"]["name"] == "thing:1"
    assert devices["thing:1"]["serial_number"] is None
    assert devices["thing:1"]["model"] is None

    status_sensor = next(
        e for e in parser.get_entities() if e._attr_unique_id == "thing:1_status"
    )
    assert status_sensor._attr_native_value is None


def test_power_indicators_attach_to_their_device(
    parser: KiwiOsEdgeParser,
    edge_gateway_info: dict[str, Any],
    edge_things: list[dict[str, Any]],
    edge_power_indicators: list[dict[str, Any]],
) -> None:
    """Each reported power becomes a sensor on the device it belongs to."""
    parser.parse_gateway(edge_gateway_info, None)
    devices = parser.parse_things(edge_things, None, GATEWAY_DEVICE_ID)
    parser.parse_power_indicators(edge_power_indicators, None, devices)

    meter_id = "sajhybrid:powermeter:94-HSR0000000000000000"
    purchase = next(
        e
        for e in parser.get_entities()
        if e._attr_unique_id == f"{meter_id}_purchase_power"
    )
    assert purchase._attr_name == "Purchase power"
    assert purchase._attr_native_value == 514.0
    assert purchase._attr_device_class == SensorDeviceClass.POWER
    assert purchase._attr_state_class == SensorStateClass.MEASUREMENT
    assert purchase._attr_device_info["identifiers"] == {(DOMAIN, meter_id)}


def test_power_indicator_of_unknown_device_is_ignored(
    parser: KiwiOsEdgeParser, caplog: pytest.LogCaptureFixture
) -> None:
    """A power for a device that is not configured creates no entity."""
    parser.parse_gateway({"serialNumber": GATEWAY_SERIAL}, None)

    parser.parse_power_indicators(
        [{"thingId": "missing:1", "type": "PURCHASE", "value": 1.0}], None, {}
    )

    assert [e._attr_name for e in parser.get_entities()] == ["KiwiOS Edge version"]
    assert "unknown device missing:1" in caplog.text


def test_unknown_power_indicator_type_keeps_its_name(
    parser: KiwiOsEdgeParser, edge_gateway_info: dict[str, Any]
) -> None:
    """A new power type from a firmware update still gets a sensor."""
    parser.parse_gateway(edge_gateway_info, None)
    devices = parser.parse_things([{"id": "thing:1"}], None, GATEWAY_DEVICE_ID)

    parser.parse_power_indicators(
        [{"thingId": "thing:1", "type": "REACTIVE"}], None, devices
    )

    reactive = next(
        e
        for e in parser.get_entities()
        if e._attr_unique_id == "thing:1_reactive_power"
    )
    assert reactive._attr_name == "Reactive"
    assert reactive._attr_native_value is None


def test_pv_plants_become_devices_with_configuration(
    parser: KiwiOsEdgeParser,
    edge_gateway_info: dict[str, Any],
    edge_pv_plants: list[dict[str, Any]],
) -> None:
    """A PV plant exposes its peak power, curtailment and install date."""
    parser.parse_gateway(edge_gateway_info, None)
    parser.parse_pv_plants(edge_pv_plants, None, GATEWAY_DEVICE_ID)

    sensors = sensors_by_name(parser)
    peak_power = sensors["Peak power"]
    assert peak_power._attr_native_value == 7200.0
    assert peak_power._attr_native_unit_of_measurement == UnitOfPower.WATT

    curtailment = sensors["Curtailment"]
    assert curtailment._attr_native_value == 100.0
    assert curtailment._attr_native_unit_of_measurement == PERCENTAGE
    assert curtailment._attr_state_class == SensorStateClass.MEASUREMENT

    installation_date = sensors["Installation date"]
    assert installation_date._attr_native_value == date(2021, 6, 1)
    assert installation_date._attr_device_class == SensorDeviceClass.DATE
    assert installation_date._attr_state_class is None


def test_pv_plant_without_configuration(parser: KiwiOsEdgeParser) -> None:
    """A plant without configuration falls back to its identifier."""
    parser.parse_gateway({"serialNumber": GATEWAY_SERIAL}, None)
    parser.parse_pv_plants(
        [{"pvPlantUuid": "pvplant:1", "config": None}], None, GATEWAY_DEVICE_ID
    )

    sensors = sensors_by_name(parser)
    assert sensors["Peak power"]._attr_native_value is None
    assert sensors["Curtailment"]._attr_native_value is None
    assert sensors["Installation date"]._attr_native_value is None
    assert sensors["Peak power"]._attr_device_info["name"] == "pvplant:1"


async def test_async_refresh_polls_the_changing_endpoints(
    parser: KiwiOsEdgeParser,
    edge_gateway_info: dict[str, Any],
    edge_things: list[dict[str, Any]],
    edge_energy_overview: dict[str, Any],
    edge_power_indicators: list[dict[str, Any]],
) -> None:
    """A refresh pulls energy, power and status and applies them."""
    build(
        parser,
        gateway_info=edge_gateway_info,
        things=edge_things,
        energy_overview={},
        power_indicators=edge_power_indicators,
        pv_plants=[],
    )

    api = AsyncMock()
    api.get_edge_energy_overview.return_value = edge_energy_overview
    api.get_edge_power_indicators.return_value = [
        {
            "thingId": "sajhybrid:powermeter:94-HSR0000000000000000",
            "type": "PURCHASE",
            "value": 42.0,
        }
    ]
    api.get_edge_things.return_value = [
        {"id": "sajhybrid:hybrid:00000000000a", "statusInfo": {"status": "OFFLINE"}}
    ]

    await parser.async_refresh(api)

    sensors = sensors_by_name(parser)
    assert sensors["Production"]._attr_native_value == 0.0
    assert sensors["Household consumption"]._attr_native_value == 511.0
    assert sensors["Purchase power"]._attr_native_value == 42.0

    statuses = {
        e._attr_unique_id: e._attr_native_value
        for e in parser.get_entities()
        if e._attr_name == "Status"
    }
    assert statuses["sajhybrid:hybrid:00000000000a_status"] == "OFFLINE"
    # Devices missing from the reply keep their last known status.
    assert statuses["sajhybrid:inverter:94-HSR0000000000000000_status"] == "ONLINE"


def test_apply_ignores_unknown_devices_and_keys(parser: KiwiOsEdgeParser) -> None:
    """Updates for entities that were never created are skipped."""
    parser.apply_energy_overview({"production": 5})
    parser.apply_power_indicators([{"thingId": "missing:1", "type": "PURCHASE"}])
    parser.apply_things([{"id": "missing:1", "statusInfo": {"status": "ONLINE"}}])

    assert parser.get_entities() == []
