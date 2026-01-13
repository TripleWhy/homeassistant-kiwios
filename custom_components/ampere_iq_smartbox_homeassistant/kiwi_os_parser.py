from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from typing import Any, cast

from homeassistant.components.sensor import (
    _LOGGER,
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
from typing import TYPE_CHECKING

# Import sensor classes lazily inside functions to avoid circular imports at module
# import time (sensor.py imports this parser). For typing only, import under
# TYPE_CHECKING.
if TYPE_CHECKING:
    from .sensor import (
        KiwiOsDataUpdateCoordinator,
        KiwiOsSensorEntity,
        KiwiOsTimestampSensorEntity,
    )

# from const import DOMAIN
# from sensor import (
#     KiwiOsApiItems,
#     KiwiOsDataUpdateCoordinator,
#     KiwiOsSensorEntity,
#     KiwiOsTimestampSensorEntity,
# )

ALWAYS_INCLUDE_ID_IN_NAME = True


class KiwiOsParser:
    """API Parser for Ampere IQ Smartbox."""

    def __init__(
        self,
    ) -> None:
        self._value_sensors: list[KiwiOsSensorEntity] = []
        self._entities: list[SensorEntity] = []
        pass

    def parse_things(
        self, things: Any, coordinator: KiwiOsDataUpdateCoordinator
    ) -> list[KiwiOsSensorEntity]:
        # Import here to avoid circular import at module import time
        from .sensor import KiwiOsSensorEntity

        value_sensors: list[KiwiOsSensorEntity] = []
        all_labels: set[str] = set()
        duplicate_labels: set[str] = set()
        for thing in things:
            thing_uid = thing["UID"]
            channels = thing.get("channels", [])
            configuration = thing.get("configuration", {})
            properties = thing.get("properties", {})

            device_info = DeviceInfo(
                created_at=configuration.get("dateInstallation", ""),
                identifiers={(DOMAIN, thing_uid)},
                manufacturer=properties.get("vendor", ""),
                model=properties.get("modelName", ""),
                model_id=properties.get("modelId", ""),
                name=thing.get("label", thing_uid),
                serial_number=properties.get("serialNumber", ""),
                sw_version=properties.get("displaySWVersion", ""),
                hw_version=properties.get("displayHWVersion", ""),
            )

            for channel in channels:
                linked_items = channel.get("linkedItems", [])
                if not linked_items:
                    continue

                label: str = channel["label"]
                if label in all_labels:
                    duplicate_labels.add(label)
                all_labels.add(label)
                value_sensor = KiwiOsSensorEntity(
                    coordinator=coordinator,
                    item_name=linked_items[0],
                    item_id=channel["id"],
                    _attr_device_info=device_info,
                    _attr_name=label,
                    _attr_unique_id=channel["uid"],
                )
                value_sensors.append(value_sensor)

        for value_sensor in value_sensors:
            if ALWAYS_INCLUDE_ID_IN_NAME or value_sensor._attr_name in duplicate_labels:
                value_sensor._attr_name = (
                    f"{value_sensor._attr_name} ({value_sensor.item_id})"
                )

        self._value_sensors = value_sensors
        return value_sensors

    def map_json_items(self, json_items: Any) -> KiwiOsApiItems:
        items: KiwiOsApiItems = {}
        for json_item in json_items:
            items[json_item["name"]] = json_item
        return items

    def create_entities(
        self,
        items: KiwiOsApiItems,
        value_sensors: list[KiwiOsSensorEntity] | None = None,
    ) -> list[SensorEntity]:
        if value_sensors is None:
            value_sensors = self._value_sensors
        entities: list[SensorEntity] = []
        # Import here to avoid circular import at module import time
        from .sensor import KiwiOsTimestampSensorEntity

        for value_sensor in value_sensors:
            entities.append(value_sensor)

            item = items.get(value_sensor.item_name)
            state = item.get("state", "") if item else ""
            if "|" not in state:
                continue

            timestamp_sensor = KiwiOsTimestampSensorEntity(value_sensor=value_sensor)
            value_sensor.timestamp_sensor = timestamp_sensor
            entities.append(timestamp_sensor)

        self._entities = entities
        return entities

    def get_entities(self) -> list[SensorEntity]:
        return self._entities

    def guess_item_types(
        self,
        items: KiwiOsApiItems,
        value_sensors: list[KiwiOsSensorEntity] | None = None,
    ) -> None:
        if value_sensors is None:
            value_sensors = self._value_sensors
        for entity in value_sensors:
            item = items.get(entity.item_name)
            self.guess_item_type(item, entity)

    def guess_item_type(self, item: Any, entity: KiwiOsSensorEntity) -> None:
        item_state: str = item["state"]
        item_type: str = item["type"]
        # pattern = item["stateDescription"]["pattern"]
        item_name: str = item["name"]

        unit_string: str | None = None
        if item_state == "UNDEF":
            if item_type == "Number:Power":
                unit_string = " W"
            elif item_type == "Number:Temperature":
                unit_string = " °C"
            elif item_type == "Number:Energy":
                unit_string = " Ws"  # " kWh" is also possible
            elif item_type == "Number:ElectricPotential":
                unit_string = " V"
            elif item_type == "Number:ElectricCurrent":
                unit_string = " A"
            elif item_type == "Number:Dimensionless":
                unit_string = " %"
            else:
                _LOGGER.warning(
                    f"Unknown type: {item_type!r} with state {item_state!r}"
                )
        elif item_state and " " in item_state:
            unit_string = item_state[item_state.rfind(" ") :]

        if unit_string is not None:
            entity.expected_unit_string = unit_string
            if unit_string == " W":
                entity.conversion_factor = 1.0
                entity._attr_native_unit_of_measurement = UnitOfPower.WATT
                entity._attr_device_class = SensorDeviceClass.POWER
                entity._attr_state_class = SensorStateClass.MEASUREMENT
            elif unit_string == " °C":
                entity.conversion_factor = 1.0
                entity._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
                entity._attr_device_class = SensorDeviceClass.TEMPERATURE
                entity._attr_state_class = SensorStateClass.MEASUREMENT
            elif unit_string == " Ws":
                entity.conversion_factor = 1.0 / (60 * 60 * 1000)
                entity._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
                entity._attr_device_class = SensorDeviceClass.ENERGY
                entity._attr_state_class = SensorStateClass.TOTAL_INCREASING
            elif unit_string == " Wh":
                entity.conversion_factor = 1.0 / 1000
                entity._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
                entity._attr_device_class = SensorDeviceClass.ENERGY
                entity._attr_state_class = SensorStateClass.TOTAL_INCREASING
            elif unit_string == " kWh":
                entity.conversion_factor = 1.0
                entity._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
                entity._attr_device_class = SensorDeviceClass.ENERGY
                entity._attr_state_class = SensorStateClass.TOTAL_INCREASING
            elif unit_string == " V":
                entity.conversion_factor = 1.0
                entity._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
                entity._attr_device_class = SensorDeviceClass.VOLTAGE
                entity._attr_state_class = SensorStateClass.MEASUREMENT
            elif unit_string == " A":
                entity.conversion_factor = 1.0
                entity._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
                entity._attr_device_class = SensorDeviceClass.CURRENT
                entity._attr_state_class = SensorStateClass.MEASUREMENT
            elif unit_string == " %":
                entity.conversion_factor = 1.0
                entity._attr_native_unit_of_measurement = PERCENTAGE
                if re.search("battery", item_name, re.IGNORECASE):
                    entity._attr_device_class = SensorDeviceClass.BATTERY
                else:
                    entity._attr_device_class = None
                entity._attr_state_class = SensorStateClass.MEASUREMENT
            else:
                _LOGGER.warning(
                    f"Unknown unit string: {unit_string!r} for state: {item_state!r} and type {item_type!r}"
                )
                entity.conversion_factor = 1.0
                entity._attr_native_unit_of_measurement = unit_string[1:]
                entity._attr_device_class = None
                entity._attr_state_class = None
        elif item_type in {"Number", "String"}:
            entity.expected_unit_string = ""
            if item_type == "Number":
                entity.conversion_factor = 1.0
            else:
                entity.conversion_factor = None
            entity._attr_native_unit_of_measurement = None
            entity._attr_state_class = SensorStateClass.MEASUREMENT
            if re.search("mode", item_name, re.IGNORECASE):
                entity._attr_device_class = SensorDeviceClass.ENUM
            else:
                entity._attr_device_class = None
        else:
            _LOGGER.warning(
                f"Cannot guess type for state: {item_state!r} and type {item_type!r}"
            )

        if entity._attr_state_class == SensorStateClass.MEASUREMENT and (
            re.search("total", item_name, re.IGNORECASE)
            or re.search("total", cast(str, entity._attr_name), re.IGNORECASE)
        ):
            entity._attr_state_class = SensorStateClass.TOTAL

    def parse_item_values(
        self,
        items: KiwiOsApiItems,
        value_sensors: list[KiwiOsSensorEntity] | None = None,
    ) -> None:
        if value_sensors is None:
            value_sensors = self._value_sensors
        for entity in value_sensors:
            item = items.get(entity.item_name)
            self.parse_item_value(item, entity)

    def parse_item_value(self, item: Any, entity: KiwiOsSensorEntity) -> None:
        if entity.timestamp_sensor is not None:
            entity.timestamp_sensor._attr_native_value = None

        item_state = item["state"]
        if item_state == "UNDEF":
            entity._attr_native_value = None
            return

        if entity.expected_unit_string == "":
            if " " in item_state:
                self.guess_item_type(entity, item)
        elif not item_state.endswith(entity.expected_unit_string):
            self.guess_item_type(entity, item)
        assert item_state.endswith(entity.expected_unit_string)

        value_str = item_state
        if entity.expected_unit_string != "":
            value_str = item_state[: -len(entity.expected_unit_string)]
        if "|" in value_str:
            assert entity.timestamp_sensor is not None
            split = value_str.split("|")
            value_str = split[-1]

            timestamp_str = split[0].strip()
            try:
                timestamp_ms = int(timestamp_str)
                dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
                # iso_string = dt.isoformat()
                entity.timestamp_sensor._attr_native_value = dt
            except ValueError:
                _LOGGER.error(
                    f"Cannot convert timestamp string to int: {timestamp_str!r} from state: {item_state!r}"
                )

        value_str = value_str.strip()

        if entity.conversion_factor is None:
            entity._attr_native_value = value_str
        else:
            try:
                entity._attr_native_value = float(value_str) * entity.conversion_factor
            except ValueError:
                _LOGGER.warning(
                    f"Cannot convert value string to float: {value_str!r} from state: {item_state!r}"
                )
                entity._attr_native_value = value_str


if __name__ == "__main__":
    parser = KiwiOsParser()
    things = json.loads(
        open(
            "/workspaces/home-assistant-core/ampere-iq-smartbox-homeassistant/test_data/things.json"
        ).read()
    )
    json_items = json.loads(
        open(
            "/workspaces/home-assistant-core/ampere-iq-smartbox-homeassistant/test_data/items.json"
        ).read()
    )
    items = parser.map_json_items(json_items)
    value_sensors = parser.parse_things(things, None)
    entities = parser.create_entities(items, value_sensors)
    parser.guess_item_types(items, value_sensors)
    parser.parse_item_values(items, value_sensors)

    print(
        f"Parsed {len(entities)} entities: {len(value_sensors)} value sensors, {len(entities) - len(value_sensors)} timestamp sensors"
    )
    # for entity in entities:
    #     state = None
    #     if isinstance(entity, KiwiOsSensorEntity):
    #         state = items.get(entity.item_name).get("state", "")
    #     print(
    #         f"{state!r}: {entity._attr_native_value!r}, {entity._attr_native_unit_of_measurement!r}, {entity._attr_device_class!r}, {entity._attr_state_class!r}, {entity._attr_name!r}"
    #     )
