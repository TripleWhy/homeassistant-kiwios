"""Platform for sensor integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .__init__ import KiwiOsConfigEntry, KiwiOsData, KiwiOsDataUpdateCoordinator
    from .kiwi_os_parser import KiwiOsParser
from .kiwi_os_api import KiwiOsApi, KiwiOsApiItems

# from __init__ import KiwiOsConfigEntry, KiwiOsData, KiwiOsDataUpdateCoordinator
# from const import DOMAIN
# from kiwi_os_api import KiwiOsApi, KiwiOsApiItems
# from kiwi_os_parser import KiwiOsParser


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KiwiOsConfigEntry,
    # async_add_entities: AddEntitiesCallback,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform from a config entry."""
    data: KiwiOsData = entry.runtime_data
    api: KiwiOsApi = data.api
    coordinator: DataUpdateCoordinator = data.coordinator
    parser: KiwiOsParser = data.parser

    async_add_entities(parser.get_entities())


class KiwiOsSensorEntity(CoordinatorEntity, SensorEntity):
    """Representation of a single KiwiOs sensor entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KiwiOsDataUpdateCoordinator,
        item_name: str,
        item_id: str,
        **kwargs,
    ) -> None:
        """Initialize a city with a name and population."""
        super().__init__(coordinator)
        for name, value in kwargs.items():
            if hasattr(self, name) or hasattr(type(self), name):
                setattr(self, name, value)
            else:
                raise AttributeError(f"{name!r} is not a valid attribute")
        self.item_name: str = item_name
        self.item_id: str = item_id
        self.expected_unit_string: str = ""
        self.conversion_factor: float | None = None
        self.timestamp_sensor: KiwiOsTimestampSensorEntity | None = None

    # async def async_update(self) -> None:
    #     print("KiwiOsSensorEntity.async_update", self.item_name)
    #     self._attr_native_value = 23

    # @property
    # def native_value(self):
    #     """Return the state of this sensor."""
    #     # print("KiwiOsSensorEntity.native_value", self.item_name)
    #     items: KiwiOsApiItems = self.coordinator.data
    #     if not items:
    #         return None
    #     item = items.get(self.item_name)
    #     if not item:
    #         return None
    #     return item.get("state")


class KiwiOsTimestampSensorEntity(CoordinatorEntity, SensorEntity):
    """Representation of a single KiwiOs timestamp sensor entity."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = None
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        value_sensor: KiwiOsSensorEntity,
    ) -> None:
        """Initialize a city with a name and population."""
        super().__init__(value_sensor.coordinator)
        self.valueSensor: KiwiOsSensorEntity = value_sensor
        self._attr_device_info = value_sensor.device_info
        self._attr_name = f"{value_sensor._attr_name} Timestamp"
        self._attr_unique_id = f"{value_sensor._attr_unique_id}_timestamp"
