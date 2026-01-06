"""Platform for sensor integration."""

from __future__ import annotations
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    AddEntitiesCallback,
)
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .__init__ import KiwiOsConfigEntry, KiwiOsData
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KiwiOsConfigEntry,
    # async_add_entities: AddEntitiesCallback,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform from a config entry."""
    data: KiwiOsData = entry.runtime_data
    coordinator: DataUpdateCoordinator = data.coordinator
    things = data.things

    entities = []
    allLabels: set[str] = set()
    duplicateLabels: set[str] = set()
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
            if label in allLabels:
                duplicateLabels.add(label)
            allLabels.add(label)
            entities.append(
                KiwiOsSensorEntity(
                    coordinator=coordinator,
                    item_name=linked_items[0],
                    item_id=channel["id"],
                    _attr_device_info=device_info,
                    _attr_name=label,
                    _attr_unique_id=channel["uid"],
                )
            )

    for entity in entities:
        if entity._attr_name in duplicateLabels:
            entity._attr_name = f"{entity._attr_name} ({entity.item_id})"

    async_add_entities(entities)


class KiwiOsSensorEntity(CoordinatorEntity[DataUpdateCoordinator[Any]], SensorEntity):
    """Representation of a single KiwiOs sensor entity."""

    _attr_has_entity_name = True

    # TODO
    # _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    # _attr_device_class = SensorDeviceClass.TEMPERATURE
    # _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[Any],
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
        self.item_name = item_name
        self.item_id = item_id

    # async def async_update(self) -> None:
    #     print("KiwiOsSensorEntity.async_update", self.item_name)
    #     self._attr_native_value = 23

    @property
    def native_value(self):
        """Return the state of this sensor."""
        # print("KiwiOsSensorEntity.native_value", self.item_name)
        items = self.coordinator.data
        if not items:
            return None
        for item in items:
            if item["name"] == self.item_name:
                return item.get("state")
        return None
