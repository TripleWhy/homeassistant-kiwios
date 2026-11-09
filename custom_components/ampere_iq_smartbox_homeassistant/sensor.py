"""Platform for sensor integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from .__init__ import KiwiOsConfigEntry, KiwiOsDataUpdateCoordinator
    from .kiwi_os_parser import KiwiOsParser


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KiwiOsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform from a config entry."""
    parser: KiwiOsParser = entry.runtime_data.parser
    async_add_entities(parser.get_entities())


class KiwiOsSensorEntity(CoordinatorEntity, SensorEntity):
    """Representation of a single KiwiOs sensor entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KiwiOsDataUpdateCoordinator,
        item_name: str,
        item_id: str,
        **kwargs: Any,
    ) -> None:
        """Initialize the sensor and apply any ``_attr_*`` overrides."""
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


class KiwiOsTimestampSensorEntity(CoordinatorEntity, SensorEntity):
    """Timestamp accompanying a KiwiOs value sensor."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = None
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # Home Assistant requires timestamp sensors to have no state class.
    _attr_state_class = None

    def __init__(self, value_sensor: KiwiOsSensorEntity) -> None:
        """Initialize the timestamp sensor from its value sensor."""
        super().__init__(value_sensor.coordinator)
        self.value_sensor: KiwiOsSensorEntity = value_sensor
        self._attr_device_info = value_sensor.device_info
        self._attr_name = f"{value_sensor._attr_name} Timestamp"
        self._attr_unique_id = f"{value_sensor._attr_unique_id}_timestamp"
