"""Tests for the Ampere.IQ sensor platform."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import HomeAssistant

from custom_components.kiwios import (
    KiwiOsData,
    sensor as sensor_platform,
)
from custom_components.kiwios.sensor import (
    KiwiOsSensorEntity,
    KiwiOsTimestampSensorEntity,
)

def make_value_sensor(
    *,
    name: str = "Power",
    unique_id: str = "unique-1",
    coordinator: Mock | None = None,
) -> KiwiOsSensorEntity:
    """Build a value sensor."""
    return KiwiOsSensorEntity(
        coordinator=coordinator,
        item_name="item_1",
        item_id="chan#1",
        _attr_name=name,
        _attr_unique_id=unique_id,
        _attr_device_info={"identifiers": {("ampere", "thing")}},
    )


async def test_setup_entry_adds_parser_entities(hass: HomeAssistant) -> None:
    """The platform forwards every entity prepared by the parser."""
    entity = Mock()
    parser = Mock()
    parser.get_entities.return_value = [entity]
    entry = Mock()
    entry.runtime_data = KiwiOsData(coordinator=Mock(), api=Mock(), parser=parser)
    add_entities = Mock()

    await sensor_platform.async_setup_entry(hass, entry, add_entities)

    add_entities.assert_called_once_with([entity])
    parser.get_entities.assert_called_once_with()


def test_sensor_entity_initialization() -> None:
    """The entity stores its identifiers and starts with empty state."""
    entity = make_value_sensor(coordinator=None)

    assert entity.coordinator is None
    assert entity.item_name == "item_1"
    assert entity.item_id == "chan#1"
    assert entity.expected_unit_string == ""
    assert entity.conversion_factor is None
    assert entity.timestamp_sensor is None
    assert entity._attr_name == "Power"
    assert entity._attr_unique_id == "unique-1"
    assert entity._attr_has_entity_name is True


def test_sensor_entity_rejects_unknown_attribute() -> None:
    """Passing an unknown keyword argument is an error."""
    with pytest.raises(
        AttributeError, match="'not_an_attribute' is not a valid attribute"
    ):
        KiwiOsSensorEntity(
            coordinator=None,
            item_name="item_1",
            item_id="chan#1",
            not_an_attribute=1,
        )


def test_timestamp_sensor_initialization() -> None:
    """The timestamp sensor mirrors its value sensor."""
    value_sensor = make_value_sensor(name="Power", unique_id="unique-1")

    timestamp_sensor = KiwiOsTimestampSensorEntity(value_sensor)

    assert timestamp_sensor.value_sensor is value_sensor
    assert timestamp_sensor.coordinator is value_sensor.coordinator
    assert timestamp_sensor._attr_name == "Power Timestamp"
    assert timestamp_sensor._attr_unique_id == "unique-1_timestamp"
    assert timestamp_sensor._attr_device_info == value_sensor.device_info
    assert timestamp_sensor._attr_device_class == SensorDeviceClass.TIMESTAMP
    assert timestamp_sensor._attr_state_class is None
    assert timestamp_sensor._attr_native_unit_of_measurement is None
    assert timestamp_sensor._attr_has_entity_name is True
    assert timestamp_sensor.entity_registry_enabled_default is False
