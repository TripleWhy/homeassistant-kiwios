"""Tests for the Ampere.IQ payload parser."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

import pytest

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
    UnitOfTemperature,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)

from custom_components.kiwios.const import DOMAIN
from custom_components.kiwios.kiwi_os_parser import (
    ALWAYS_INCLUDE_ID_IN_NAME,
    KiwiOsParser,
)
from custom_components.kiwios.sensor import (
    KiwiOsSensorEntity,
    KiwiOsTimestampSensorEntity,
)

def make_channel(
    *,
    uid: str = "thing:1:chan#1",
    channel_id: str = "chan#1",
    label: str = "Power",
    linked_items: tuple[str, ...] = ("item_1",),
) -> dict[str, Any]:
    """Build a channel structure as returned by /rest/things."""
    return {
        "uid": uid,
        "id": channel_id,
        "label": label,
        "linkedItems": list(linked_items),
    }


def make_thing(
    *,
    uid: str = "thing:1",
    label: str | None = "Thing",
    channels: list[dict[str, Any]] | None = None,
    configuration: dict[str, Any] | None = None,
    properties: dict[str, Any] | None = None,
    include_channels: bool = True,
) -> dict[str, Any]:
    """Build a thing structure as returned by /rest/things."""
    thing: dict[str, Any] = {"UID": uid}
    if label is not None:
        thing["label"] = label
    if include_channels:
        thing["channels"] = channels if channels is not None else []
    if configuration is not None:
        thing["configuration"] = configuration
    if properties is not None:
        thing["properties"] = properties
    return thing


def make_sensor(
    item_name: str = "item_1",
    *,
    item_id: str = "chan#1",
    name: str = "Sensor",
    unique_id: str = "unique-1",
    coordinator: Any = None,
) -> KiwiOsSensorEntity:
    """Build a value sensor for parser unit tests."""
    return KiwiOsSensorEntity(
        coordinator=coordinator,
        item_name=item_name,
        item_id=item_id,
        _attr_name=name,
        _attr_unique_id=unique_id,
    )


def make_item(
    name: str = "item_1",
    state: str = "1 W",
    item_type: str = "Number:Power",
) -> dict[str, Any]:
    """Build an item structure as returned by /rest/items."""
    return {"name": name, "state": state, "type": item_type}


def make_timestamp_sensor(
    value_sensor: KiwiOsSensorEntity,
) -> KiwiOsTimestampSensorEntity:
    """Attach (and return) a timestamp sensor for a value sensor."""
    timestamp_sensor = KiwiOsTimestampSensorEntity(value_sensor)
    value_sensor.timestamp_sensor = timestamp_sensor
    return timestamp_sensor


# ---------------------------------------------------------------------------
# parse_things
# ---------------------------------------------------------------------------


def test_parse_things_from_capture(things: list[dict[str, Any]]) -> None:
    """The captured payload produces one sensor per linked channel."""
    parser = KiwiOsParser()
    sensors = parser.parse_things(things, None)

    assert len(sensors) == 99
    assert parser._value_sensors is sensors
    assert all(isinstance(sensor, KiwiOsSensorEntity) for sensor in sensors)

    for sensor in sensors:
        # ALWAYS_INCLUDE_ID_IN_NAME is enabled by default.
        assert sensor._attr_name.endswith(f" ({sensor.item_id})")
        assert sensor._attr_unique_id
        assert sensor.expected_unit_string == ""
        assert sensor.conversion_factor is None
        assert sensor.timestamp_sensor is None

    # The bridge thing has no channels and must not produce sensors.
    assert all(
        sensor._attr_unique_id.find("sajhybrid:hybrid:e4ea3ad870f0") == -1
        for sensor in sensors
    )


def test_parse_things_device_info(things: list[dict[str, Any]]) -> None:
    """Device information is derived from the thing metadata."""
    parser = KiwiOsParser()
    sensors = parser.parse_things(things, None)

    sensor = next(
        item
        for item in sensors
        if item._attr_unique_id.startswith("sajhybrid:powermeter:")
    )
    device_info = sensor.device_info
    assert device_info["identifiers"] == {
        (DOMAIN, "sajhybrid:powermeter:94-HSR2103J2344E27920")
    }
    assert device_info["manufacturer"] == "AMPERE"
    assert device_info["model"] == "HS2"
    assert device_info["model_id"] == "94"
    assert device_info["name"] == ("AMPERE.StoragePro Meter A (HSR2103J2344E27920)")
    assert device_info["serial_number"] == "HSR2103J2344E27920"
    assert device_info["sw_version"] == "2.532"
    assert device_info["hw_version"] == "1.100"
    assert device_info["created_at"] == ""


def test_parse_things_uses_defaults_for_missing_metadata() -> None:
    """Missing label, configuration and properties fall back to defaults."""
    parser = KiwiOsParser()
    thing = make_thing(uid="thing:2", label=None)
    thing["channels"] = [
        make_channel(uid="u1", channel_id="c1", label="Keep"),
    ]

    sensors = parser.parse_things([thing], None)

    assert len(sensors) == 1
    assert sensors[0]._attr_name == "Keep (c1)"
    device_info = sensors[0].device_info
    assert device_info["name"] == "thing:2"
    assert device_info["manufacturer"] == ""
    assert device_info["model"] == ""
    assert device_info["model_id"] == ""
    assert device_info["serial_number"] == ""
    assert device_info["sw_version"] == ""
    assert device_info["hw_version"] == ""
    assert device_info["created_at"] == ""


def test_parse_things_reads_configuration_installation_date() -> None:
    """An installation date in the configuration is exposed on the device."""
    parser = KiwiOsParser()
    thing = make_thing(
        configuration={"dateInstallation": "2024-01-02"},
        channels=[make_channel()],
    )

    sensor = parser.parse_things([thing], None)[0]

    assert sensor.device_info["created_at"] == "2024-01-02"


def test_parse_things_skips_channels_without_linked_items() -> None:
    """Channels without linked items, or without the key, are ignored."""
    parser = KiwiOsParser()
    thing = make_thing(
        channels=[
            make_channel(uid="u1", channel_id="c1", label="Keep"),
            make_channel(
                uid="u2",
                channel_id="c2",
                label="Empty",
                linked_items=(),
            ),
            {"uid": "u3", "id": "c3", "label": "MissingKey"},
        ]
    )

    sensors = parser.parse_things([thing], None)

    assert [sensor._attr_name for sensor in sensors] == ["Keep (c1)"]


def test_parse_things_skips_things_without_channels() -> None:
    """A thing without a channels key produces no sensors."""
    parser = KiwiOsParser()

    assert parser.parse_things([make_thing(include_channels=False)], None) == []


def test_parse_things_unique_label_without_forced_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ALWAYS_INCLUDE_ID_IN_NAME a unique label is kept as-is."""
    monkeypatch.setattr(
        "custom_components.kiwios.kiwi_os_parser."
        "ALWAYS_INCLUDE_ID_IN_NAME",
        False,
    )
    parser = KiwiOsParser()
    thing = make_thing(channels=[make_channel(label="Power")])

    sensors = parser.parse_things([thing], None)

    assert sensors[0]._attr_name == "Power"


def test_parse_things_duplicate_label_gets_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without forced ids, duplicate labels are disambiguated with the id."""
    monkeypatch.setattr(
        "custom_components.kiwios.kiwi_os_parser."
        "ALWAYS_INCLUDE_ID_IN_NAME",
        False,
    )
    parser = KiwiOsParser()
    thing = make_thing(
        channels=[
            make_channel(uid="u1", channel_id="c1", label="Power"),
            make_channel(uid="u2", channel_id="c2", label="Power"),
        ]
    )

    sensors = parser.parse_things([thing], None)

    assert [sensor._attr_name for sensor in sensors] == [
        "Power (c1)",
        "Power (c2)",
    ]


# ---------------------------------------------------------------------------
# map_json_items / entities
# ---------------------------------------------------------------------------


def test_map_json_items_indexes_by_name() -> None:
    """Items are indexed by their name."""
    parser = KiwiOsParser()
    items = parser.map_json_items(
        [
            make_item("a"),
            make_item("b", state="2 W"),
        ]
    )

    assert set(items) == {"a", "b"}
    assert items["b"]["state"] == "2 W"


def test_create_entities_adds_timestamp_sensor_for_pipe_state() -> None:
    """A state containing a timestamp separator yields two entities."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    entities = parser.create_entities(
        {"item_1": make_item(state="1700000000000|5 W")}, [value_sensor]
    )

    assert entities == [value_sensor, value_sensor.timestamp_sensor]
    assert isinstance(value_sensor.timestamp_sensor, KiwiOsTimestampSensorEntity)
    assert parser.get_entities() is entities


def test_create_entities_without_pipe_state() -> None:
    """A plain state yields only the value sensor."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    entities = parser.create_entities({"item_1": make_item()}, [value_sensor])

    assert entities == [value_sensor]
    assert value_sensor.timestamp_sensor is None


def test_create_entities_missing_item_has_empty_state() -> None:
    """A missing item is treated as having an empty state."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    entities = parser.create_entities({}, [value_sensor])

    assert entities == [value_sensor]
    assert value_sensor.timestamp_sensor is None


def test_create_entities_uses_stored_value_sensors() -> None:
    """Value sensors default to the ones remembered from parse_things."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    parser._value_sensors = [value_sensor]

    entities = parser.create_entities({"item_1": make_item()})

    assert entities == [value_sensor]


# ---------------------------------------------------------------------------
# guess_item_type
# ---------------------------------------------------------------------------


def test_guess_item_types_uses_stored_value_sensors() -> None:
    """Value sensors default to the ones remembered from parse_things."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    parser._value_sensors = [value_sensor]

    parser.guess_item_types({"item_1": make_item(state="5 W")})

    assert value_sensor.expected_unit_string == " W"
    assert value_sensor._attr_native_unit_of_measurement == UnitOfPower.WATT


def test_guess_item_types_accepts_explicit_value_sensors() -> None:
    """An explicit value sensor list is used when given."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    parser.guess_item_types({"item_1": make_item(state="5 W")}, [value_sensor])

    assert value_sensor.expected_unit_string == " W"


@pytest.mark.parametrize(
    ("item_type", "expected_unit", "native_unit", "device_class", "state_class"),
    [
        (
            "Number:Power",
            " W",
            UnitOfPower.WATT,
            SensorDeviceClass.POWER,
            SensorStateClass.MEASUREMENT,
        ),
        (
            "Number:Temperature",
            " °C",
            UnitOfTemperature.CELSIUS,
            SensorDeviceClass.TEMPERATURE,
            SensorStateClass.MEASUREMENT,
        ),
        (
            "Number:Energy",
            " Ws",
            UnitOfEnergy.KILO_WATT_HOUR,
            SensorDeviceClass.ENERGY,
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            "Number:ElectricPotential",
            " V",
            UnitOfElectricPotential.VOLT,
            SensorDeviceClass.VOLTAGE,
            SensorStateClass.MEASUREMENT,
        ),
        (
            "Number:ElectricCurrent",
            " A",
            UnitOfElectricCurrent.AMPERE,
            SensorDeviceClass.CURRENT,
            SensorStateClass.MEASUREMENT,
        ),
        (
            "Number:Dimensionless",
            " %",
            PERCENTAGE,
            None,
            SensorStateClass.MEASUREMENT,
        ),
    ],
)
def test_guess_item_type_undefined_state_uses_item_type(
    item_type: str,
    expected_unit: str,
    native_unit: str,
    device_class: SensorDeviceClass | None,
    state_class: SensorStateClass,
) -> None:
    """An UNDEF state is typed from the item type."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    parser.guess_item_type(make_item(state="UNDEF", item_type=item_type), value_sensor)

    assert value_sensor.expected_unit_string == expected_unit
    assert value_sensor._attr_native_unit_of_measurement == native_unit
    assert value_sensor._attr_device_class == device_class
    assert value_sensor._attr_state_class == state_class
    assert value_sensor.conversion_factor == pytest.approx(
        1.0 / (60 * 60 * 1000) if expected_unit == " Ws" else 1.0
    )


@pytest.mark.parametrize(
    ("state", "expected_unit", "native_unit", "device_class", "state_class", "factor"),
    [
        (
            "1157 W",
            " W",
            UnitOfPower.WATT,
            SensorDeviceClass.POWER,
            SensorStateClass.MEASUREMENT,
            1.0,
        ),
        (
            "21 °C",
            " °C",
            UnitOfTemperature.CELSIUS,
            SensorDeviceClass.TEMPERATURE,
            SensorStateClass.MEASUREMENT,
            1.0,
        ),
        (
            "8912.5 Ws",
            " Ws",
            UnitOfEnergy.KILO_WATT_HOUR,
            SensorDeviceClass.ENERGY,
            SensorStateClass.TOTAL_INCREASING,
            1.0 / (60 * 60 * 1000),
        ),
        (
            "500 Wh",
            " Wh",
            UnitOfEnergy.KILO_WATT_HOUR,
            SensorDeviceClass.ENERGY,
            SensorStateClass.TOTAL_INCREASING,
            1.0 / 1000,
        ),
        (
            "0.5 kWh",
            " kWh",
            UnitOfEnergy.KILO_WATT_HOUR,
            SensorDeviceClass.ENERGY,
            SensorStateClass.TOTAL_INCREASING,
            1.0,
        ),
        (
            "230 V",
            " V",
            UnitOfElectricPotential.VOLT,
            SensorDeviceClass.VOLTAGE,
            SensorStateClass.MEASUREMENT,
            1.0,
        ),
        (
            "13 A",
            " A",
            UnitOfElectricCurrent.AMPERE,
            SensorDeviceClass.CURRENT,
            SensorStateClass.MEASUREMENT,
            1.0,
        ),
    ],
)
def test_guess_item_type_unit_from_state(
    state: str,
    expected_unit: str,
    native_unit: str,
    device_class: SensorDeviceClass | None,
    state_class: SensorStateClass,
    factor: float,
) -> None:
    """The unit suffix of a state selects the sensor metadata."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    parser.guess_item_type(make_item(state=state), value_sensor)

    assert value_sensor.expected_unit_string == expected_unit
    assert value_sensor._attr_native_unit_of_measurement == native_unit
    assert value_sensor._attr_device_class == device_class
    assert value_sensor._attr_state_class == state_class
    assert value_sensor.conversion_factor == pytest.approx(factor)


def test_guess_item_type_percentage_battery() -> None:
    """A percentage item whose name mentions battery is a battery sensor."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    parser.guess_item_type(make_item(name="battery_level", state="50 %"), value_sensor)

    assert value_sensor._attr_native_unit_of_measurement == PERCENTAGE
    assert value_sensor._attr_device_class == SensorDeviceClass.BATTERY
    assert value_sensor._attr_state_class == SensorStateClass.MEASUREMENT


def test_guess_item_type_percentage_non_battery() -> None:
    """Other percentage items have no device class."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    parser.guess_item_type(
        make_item(name="state_of_charge", state="50 %"), value_sensor
    )

    assert value_sensor._attr_native_unit_of_measurement == PERCENTAGE
    assert value_sensor._attr_device_class is None


def test_guess_item_type_unknown_unit_string_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unfamiliar unit is kept without device or state class."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    with caplog.at_level(logging.WARNING):
        parser.guess_item_type(make_item(state="5 lux"), value_sensor)

    assert value_sensor.expected_unit_string == " lux"
    assert value_sensor._attr_native_unit_of_measurement == "lux"
    assert value_sensor._attr_device_class is None
    assert value_sensor._attr_state_class is None
    assert value_sensor.conversion_factor == 1.0
    assert "Unknown unit string" in caplog.text


def test_guess_item_type_unknown_undefined_type_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unknown item type with UNDEF state is reported but tolerated."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    # Simulate an entity that already had a state class assigned.
    value_sensor._attr_state_class = None

    with caplog.at_level(logging.WARNING):
        parser.guess_item_type(
            make_item(state="UNDEF", item_type="Number:Weird"), value_sensor
        )

    assert "Unknown type" in caplog.text
    assert "Cannot guess type" in caplog.text
    assert value_sensor.expected_unit_string == ""


def test_guess_item_type_number_without_unit() -> None:
    """A plain Number item has a unit-less measurement state."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    parser.guess_item_type(make_item(state="", item_type="Number"), value_sensor)

    assert value_sensor.expected_unit_string == ""
    assert value_sensor.conversion_factor == 1.0
    assert value_sensor._attr_native_unit_of_measurement is None
    assert value_sensor._attr_state_class == SensorStateClass.MEASUREMENT
    assert value_sensor._attr_device_class is None


def test_guess_item_type_string_without_unit() -> None:
    """A plain String item keeps its raw value and has no conversion."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    parser.guess_item_type(make_item(state="", item_type="String"), value_sensor)

    assert value_sensor.expected_unit_string == ""
    assert value_sensor.conversion_factor is None
    assert value_sensor._attr_native_unit_of_measurement is None
    assert value_sensor._attr_state_class == SensorStateClass.MEASUREMENT
    assert value_sensor._attr_device_class is None


def test_guess_item_type_mode_becomes_enum() -> None:
    """A String item whose name mentions mode is an enum sensor."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    parser.guess_item_type(
        make_item(name="operating_mode", state="", item_type="String"),
        value_sensor,
    )

    assert value_sensor._attr_device_class == SensorDeviceClass.ENUM


def test_guess_item_type_number_mode_becomes_enum() -> None:
    """A Number item whose name mentions mode is an enum sensor."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    parser.guess_item_type(
        make_item(name="MODE_setting", state="", item_type="Number"),
        value_sensor,
    )

    assert value_sensor._attr_device_class == SensorDeviceClass.ENUM


def test_guess_item_type_cannot_guess_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unsupported combination is reported and leaves metadata alone."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor._attr_state_class = None

    with caplog.at_level(logging.WARNING):
        parser.guess_item_type(make_item(state="ON", item_type="Switch"), value_sensor)

    assert "Cannot guess type" in caplog.text


def test_guess_item_type_state_without_space_and_unknown_type_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A unit-less non-String state cannot be typed."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor._attr_state_class = None

    with caplog.at_level(logging.WARNING):
        parser.guess_item_type(
            make_item(state="5Wh", item_type="Number:Energy"), value_sensor
        )

    assert "Cannot guess type" in caplog.text


def test_guess_item_type_total_from_item_name() -> None:
    """A measurement whose item name mentions total becomes TOTAL."""
    parser = KiwiOsParser()
    value_sensor = make_sensor(name="Sensor")

    parser.guess_item_type(make_item(name="total_power", state="5 W"), value_sensor)

    assert value_sensor._attr_state_class == SensorStateClass.TOTAL


def test_guess_item_type_total_from_entity_name() -> None:
    """A measurement whose entity name mentions total becomes TOTAL."""
    parser = KiwiOsParser()
    value_sensor = make_sensor(name="Total Power")

    parser.guess_item_type(make_item(name="power", state="5 W"), value_sensor)

    assert value_sensor._attr_state_class == SensorStateClass.TOTAL


def test_guess_item_type_measurement_without_total() -> None:
    """A regular measurement stays MEASUREMENT."""
    parser = KiwiOsParser()
    value_sensor = make_sensor(name="Power")

    parser.guess_item_type(make_item(name="power", state="5 W"), value_sensor)

    assert value_sensor._attr_state_class == SensorStateClass.MEASUREMENT


# ---------------------------------------------------------------------------
# parse_item_value
# ---------------------------------------------------------------------------


def test_parse_item_values_uses_stored_value_sensors() -> None:
    """Value sensors default to the ones remembered from parse_things."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor.expected_unit_string = " W"
    value_sensor.conversion_factor = 1.0
    parser._value_sensors = [value_sensor]

    parser.parse_item_values({"item_1": make_item(state="5 W")})

    assert value_sensor._attr_native_value == 5.0


def test_parse_item_values_accepts_explicit_value_sensors() -> None:
    """An explicit value sensor list is used when given."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor.expected_unit_string = " W"
    value_sensor.conversion_factor = 1.0

    parser.parse_item_values({"item_1": make_item(state="5 W")}, [value_sensor])

    assert value_sensor._attr_native_value == 5.0


def test_parse_item_value_undefined_clears_value_and_timestamp() -> None:
    """UNDEF clears the value and resets any timestamp sensor."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    timestamp_sensor = make_timestamp_sensor(value_sensor)
    timestamp_sensor._attr_native_value = datetime(2024, 1, 1, tzinfo=UTC)

    parser.parse_item_value(
        make_item(state="UNDEF", item_type="Number:Power"), value_sensor
    )

    assert value_sensor._attr_native_value is None
    assert timestamp_sensor._attr_native_value is None


def test_parse_item_value_guesses_unit_from_state() -> None:
    """A unit-less entity learns the unit from a state that has one."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()

    parser.parse_item_value(make_item(state="42 W"), value_sensor)

    assert value_sensor.expected_unit_string == " W"
    assert value_sensor._attr_native_unit_of_measurement == UnitOfPower.WATT
    assert value_sensor._attr_device_class == SensorDeviceClass.POWER
    assert value_sensor._attr_native_value == 42.0


def test_parse_item_value_reguesses_on_unit_mismatch() -> None:
    """A state with a different unit re-guesses the sensor metadata."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor.expected_unit_string = " W"
    value_sensor.conversion_factor = 1.0

    parser.parse_item_value(make_item(state="42 °C"), value_sensor)

    assert value_sensor.expected_unit_string == " °C"
    assert value_sensor._attr_device_class == SensorDeviceClass.TEMPERATURE
    assert value_sensor._attr_native_value == 42.0


def test_parse_item_value_keeps_plain_string() -> None:
    """A String entity without a unit keeps the raw value."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor.expected_unit_string = ""
    value_sensor.conversion_factor = None

    parser.parse_item_value(make_item(state="hello"), value_sensor)

    assert value_sensor._attr_native_value == "hello"
    assert value_sensor.expected_unit_string == ""


def test_parse_item_value_parses_matching_unit() -> None:
    """A matching unit is stripped and the number is scaled."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor.expected_unit_string = " W"
    value_sensor.conversion_factor = 2.0

    parser.parse_item_value(make_item(state="21 W"), value_sensor)

    assert value_sensor._attr_native_value == 42.0


def test_parse_item_value_strips_surrounding_whitespace() -> None:
    """Whitespace left after removing the unit is stripped."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor.expected_unit_string = " W"
    value_sensor.conversion_factor = 1.0

    parser.parse_item_value(make_item(state=" 5 W"), value_sensor)

    assert value_sensor._attr_native_value == 5.0


def test_parse_item_value_parses_timestamp_pipe() -> None:
    """The leading timestamp is converted to a UTC datetime."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor.expected_unit_string = " Ws"
    value_sensor.conversion_factor = 1.0 / (60 * 60 * 1000)
    timestamp_sensor = make_timestamp_sensor(value_sensor)

    parser.parse_item_value(make_item(state="1760711100000|8912.5 Ws"), value_sensor)

    assert timestamp_sensor._attr_native_value == datetime.fromtimestamp(
        1760711100, tz=UTC
    )
    assert value_sensor._attr_native_value == pytest.approx(8912.5 / (60 * 60 * 1000))


def test_parse_item_value_invalid_timestamp_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unparsable timestamp is logged and leaves the timestamp unset."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor.expected_unit_string = " Ws"
    value_sensor.conversion_factor = 1.0 / (60 * 60 * 1000)
    timestamp_sensor = make_timestamp_sensor(value_sensor)

    with caplog.at_level(logging.ERROR):
        parser.parse_item_value(make_item(state="not-a-number|5 Ws"), value_sensor)

    assert timestamp_sensor._attr_native_value is None
    assert value_sensor._attr_native_value == pytest.approx(5 / (60 * 60 * 1000))
    assert "Cannot convert timestamp string to int" in caplog.text


def test_parse_item_value_invalid_number_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unparsable number is logged and kept as a string."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor.expected_unit_string = " W"
    value_sensor.conversion_factor = 1.0

    with caplog.at_level(logging.WARNING):
        parser.parse_item_value(make_item(state="abc W"), value_sensor)

    assert value_sensor._attr_native_value == "abc"
    assert "Cannot convert value string to float" in caplog.text


def test_parse_item_value_without_timestamp_sensor() -> None:
    """A value without a timestamp sensor is parsed normally."""
    parser = KiwiOsParser()
    value_sensor = make_sensor()
    value_sensor.expected_unit_string = " W"
    value_sensor.conversion_factor = 1.0

    parser.parse_item_value(make_item(state="7 W"), value_sensor)

    assert value_sensor._attr_native_value == 7.0
    assert value_sensor.timestamp_sensor is None


def test_always_include_id_is_enabled_by_default() -> None:
    """The module-level naming switch keeps its documented default."""
    assert ALWAYS_INCLUDE_ID_IN_NAME is True
