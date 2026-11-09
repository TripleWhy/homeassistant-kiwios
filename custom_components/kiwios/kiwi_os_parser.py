"""Parser that turns KiwiOS REST payloads into sensor entities."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
import re
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
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
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .kiwi_os_api import KiwiOsApiItems

if TYPE_CHECKING:
    from .sensor import KiwiOsDataUpdateCoordinator, KiwiOsSensorEntity

_LOGGER = logging.getLogger(__name__)

ALWAYS_INCLUDE_ID_IN_NAME = True

_UNIT_SPECS: dict[str, tuple[float, str, SensorDeviceClass, SensorStateClass]] = {
    " W": (
        1.0,
        UnitOfPower.WATT,
        SensorDeviceClass.POWER,
        SensorStateClass.MEASUREMENT,
    ),
    " °C": (
        1.0,
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
    ),
    " Ws": (
        1.0 / (60 * 60 * 1000),
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
    ),
    " Wh": (
        1.0 / 1000,
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
    ),
    " kWh": (
        1.0,
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
    ),
    " V": (
        1.0,
        UnitOfElectricPotential.VOLT,
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
    ),
    " A": (
        1.0,
        UnitOfElectricCurrent.AMPERE,
        SensorDeviceClass.CURRENT,
        SensorStateClass.MEASUREMENT,
    ),
}

# Units implied by an item type whose state is still "UNDEF".
_UNDEFINED_STATE_UNITS: dict[str, str] = {
    "Number:Power": " W",
    "Number:Temperature": " °C",
    "Number:Energy": " Ws",  # " kWh" is also possible
    "Number:ElectricPotential": " V",
    "Number:ElectricCurrent": " A",
    "Number:Dimensionless": " %",
}


class KiwiOsParser:
    """API Parser for KiwiOS devices."""

    def __init__(self) -> None:
        """Initialize an empty parser."""
        self._value_sensors: list[KiwiOsSensorEntity] = []
        self._entities: list[SensorEntity] = []

    # -- things ---------------------------------------------------------

    @staticmethod
    def _device_info(thing: dict[str, Any]) -> DeviceInfo:
        """Build the Home Assistant device information for a thing."""
        configuration = thing.get("configuration", {})
        properties = thing.get("properties", {})
        return DeviceInfo(
            created_at=configuration.get("dateInstallation", ""),
            identifiers={(DOMAIN, thing["UID"])},
            manufacturer=properties.get("vendor", ""),
            model=properties.get("modelName", ""),
            model_id=properties.get("modelId", ""),
            name=thing.get("label", thing["UID"]),
            serial_number=properties.get("serialNumber", ""),
            sw_version=properties.get("displaySWVersion", ""),
            hw_version=properties.get("displayHWVersion", ""),
        )

    def parse_things(
        self, things: Any, coordinator: KiwiOsDataUpdateCoordinator
    ) -> list[KiwiOsSensorEntity]:
        """Create one value sensor for every channel that links an item."""
        # Imported lazily to avoid a circular import with sensor.py.
        from .sensor import KiwiOsSensorEntity

        value_sensors: list[KiwiOsSensorEntity] = []
        labels: set[str] = set()
        duplicate_labels: set[str] = set()

        for thing in things:
            device_info = self._device_info(thing)
            for channel in thing.get("channels", []):
                linked_items = channel.get("linkedItems", [])
                if not linked_items:
                    continue

                label = channel["label"]
                if label in labels:
                    duplicate_labels.add(label)
                labels.add(label)

                value_sensors.append(
                    KiwiOsSensorEntity(
                        coordinator=coordinator,
                        item_name=linked_items[0],
                        item_id=channel["id"],
                        _attr_device_info=device_info,
                        _attr_name=label,
                        _attr_unique_id=channel["uid"],
                    )
                )

        for value_sensor in value_sensors:
            name = value_sensor._attr_name
            if ALWAYS_INCLUDE_ID_IN_NAME or name in duplicate_labels:
                value_sensor._attr_name = f"{name} ({value_sensor.item_id})"

        self._value_sensors = value_sensors
        return value_sensors

    # -- items ----------------------------------------------------------

    @staticmethod
    def map_json_items(json_items: Any) -> KiwiOsApiItems:
        """Index the raw item list by item name."""
        return {json_item["name"]: json_item for json_item in json_items}

    def create_entities(
        self,
        items: KiwiOsApiItems,
        value_sensors: list[KiwiOsSensorEntity] | None = None,
    ) -> list[SensorEntity]:
        """Pair every value sensor with an optional timestamp sensor."""
        if value_sensors is None:
            value_sensors = self._value_sensors

        # Imported lazily to avoid a circular import with sensor.py.
        from .sensor import KiwiOsTimestampSensorEntity

        entities: list[SensorEntity] = []
        for value_sensor in value_sensors:
            entities.append(value_sensor)

            item = items.get(value_sensor.item_name)
            state = item.get("state", "") if item else ""
            if "|" not in state:
                continue

            timestamp_sensor = KiwiOsTimestampSensorEntity(value_sensor)
            value_sensor.timestamp_sensor = timestamp_sensor
            entities.append(timestamp_sensor)

        self._entities = entities
        return entities

    def get_entities(self) -> list[SensorEntity]:
        """Return the entities created by :meth:`create_entities`."""
        return self._entities

    # -- typing ---------------------------------------------------------

    def guess_item_types(
        self,
        items: KiwiOsApiItems,
        value_sensors: list[KiwiOsSensorEntity] | None = None,
    ) -> None:
        """Derive unit and state metadata for every value sensor."""
        if value_sensors is None:
            value_sensors = self._value_sensors
        for entity in value_sensors:
            self.guess_item_type(items.get(entity.item_name), entity)

    @staticmethod
    def _guess_unit(item_state: str, item_type: str) -> str | None:
        """Return the unit implied by a state or, for UNDEF, by the type."""
        if item_state == "UNDEF":
            unit = _UNDEFINED_STATE_UNITS.get(item_type)
            if unit is None:
                _LOGGER.warning("Unknown type: %r with state %r", item_type, item_state)
            return unit
        if " " in item_state:
            return item_state[item_state.rfind(" ") :]
        return None

    @staticmethod
    def _apply_unit(
        entity: KiwiOsSensorEntity, unit_string: str, item_name: str
    ) -> None:
        """Attach the metadata for a known or unknown unit string."""
        entity.expected_unit_string = unit_string

        if spec := _UNIT_SPECS.get(unit_string):
            factor, native_unit, device_class, state_class = spec
            entity.conversion_factor = factor
            entity._attr_native_unit_of_measurement = native_unit
            entity._attr_device_class = device_class
            entity._attr_state_class = state_class
            return

        if unit_string == " %":
            entity.conversion_factor = 1.0
            entity._attr_native_unit_of_measurement = PERCENTAGE
            entity._attr_device_class = (
                SensorDeviceClass.BATTERY
                if re.search("battery", item_name, re.IGNORECASE)
                else None
            )
            entity._attr_state_class = SensorStateClass.MEASUREMENT
            return

        _LOGGER.warning("Unknown unit string: %r for item %r", unit_string, item_name)
        entity.conversion_factor = 1.0
        entity._attr_native_unit_of_measurement = unit_string[1:]
        entity._attr_device_class = None
        entity._attr_state_class = None

    @staticmethod
    def _apply_unitless_type(
        entity: KiwiOsSensorEntity, item_type: str, item_name: str
    ) -> None:
        """Attach metadata for a unit-less Number or String item."""
        if item_type not in {"Number", "String"}:
            _LOGGER.warning("Cannot guess type for item %r", item_name)
            return

        entity.expected_unit_string = ""
        entity.conversion_factor = 1.0 if item_type == "Number" else None
        entity._attr_native_unit_of_measurement = None
        entity._attr_state_class = SensorStateClass.MEASUREMENT
        entity._attr_device_class = (
            SensorDeviceClass.ENUM
            if re.search("mode", item_name, re.IGNORECASE)
            else None
        )

    def guess_item_type(self, item: Any, entity: KiwiOsSensorEntity) -> None:
        """Derive unit, device class and state class from an item."""
        item_state: str = item["state"]
        item_type: str = item["type"]
        item_name: str = item["name"]

        unit_string = self._guess_unit(item_state, item_type)
        if unit_string is None:
            self._apply_unitless_type(entity, item_type, item_name)
        else:
            self._apply_unit(entity, unit_string, item_name)

        if entity._attr_state_class == SensorStateClass.MEASUREMENT and (
            re.search("total", item_name, re.IGNORECASE)
            or re.search("total", cast(str, entity._attr_name), re.IGNORECASE)
        ):
            entity._attr_state_class = SensorStateClass.TOTAL

    # -- values ---------------------------------------------------------

    def parse_item_values(
        self,
        items: KiwiOsApiItems,
        value_sensors: list[KiwiOsSensorEntity] | None = None,
    ) -> None:
        """Update every value sensor from the current item values."""
        if value_sensors is None:
            value_sensors = self._value_sensors
        for entity in value_sensors:
            self.parse_item_value(items.get(entity.item_name), entity)

    @staticmethod
    def _parse_timestamp(
        timestamp_str: str,
        item_state: str,
        entity: KiwiOsSensorEntity,
    ) -> None:
        """Store the leading pipe-separated timestamp on the timestamp sensor."""
        try:
            timestamp_ms = int(timestamp_str)
        except ValueError:
            _LOGGER.error(
                "Cannot convert timestamp string to int: %r from state: %r",
                timestamp_str,
                item_state,
            )
            return

        assert entity.timestamp_sensor is not None
        entity.timestamp_sensor._attr_native_value = datetime.fromtimestamp(
            timestamp_ms / 1000, tz=UTC
        )

    def parse_item_value(self, item: Any, entity: KiwiOsSensorEntity) -> None:
        """Apply one item's state to a value sensor."""
        if entity.timestamp_sensor is not None:
            entity.timestamp_sensor._attr_native_value = None

        item_state: str = item["state"]
        if item_state == "UNDEF":
            entity._attr_native_value = None
            return

        if entity.expected_unit_string == "":
            if " " in item_state:
                self.guess_item_type(item, entity)
        elif not item_state.endswith(entity.expected_unit_string):
            self.guess_item_type(item, entity)
        assert item_state.endswith(entity.expected_unit_string)

        value_str = item_state
        if entity.expected_unit_string != "":
            value_str = item_state[: -len(entity.expected_unit_string)]
        if "|" in value_str:
            split = value_str.split("|")
            value_str = split[-1]
            self._parse_timestamp(split[0].strip(), item_state, entity)

        value_str = value_str.strip()

        if entity.conversion_factor is None:
            entity._attr_native_value = value_str
            return

        try:
            entity._attr_native_value = float(value_str) * entity.conversion_factor
        except ValueError:
            _LOGGER.warning(
                "Cannot convert value string to float: %r from state: %r",
                value_str,
                item_state,
            )
            entity._attr_native_value = value_str
