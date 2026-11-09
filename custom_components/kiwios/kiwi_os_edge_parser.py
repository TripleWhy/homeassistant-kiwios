"""Parser that turns KiwiOS Edge REST payloads into sensor entities.

Firmware running KiwiOS Edge (10.x, EM.setup 4.x) no longer exposes the
per-channel items of the OpenHAB style API.  What is left are a few aggregated
endpoints: the instantaneous power of the installation, the power of every
device, the reachability of every device and the PV plant configuration.
"""

from __future__ import annotations

from datetime import date
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.components.sensor import SensorEntity

    from .kiwi_os_api import KiwiOsApi
    from .sensor import KiwiOsDataUpdateCoordinator, KiwiOsSensorEntity

_LOGGER = logging.getLogger(__name__)

MANUFACTURER = "EKD"

# Keys of /energy-overview, with the label used for the sensor.
_ENERGY_OVERVIEW_SENSORS: dict[str, str] = {
    "production": "Production",
    "feedIn": "Feed-in",
    "feedOut": "Feed-out",
    "householdConsumption": "Household consumption",
    "storagePowerIn": "Storage power in",
    "storagePowerOut": "Storage power out",
}

# Types of /power-indicator, with the label used for the sensor.
_POWER_INDICATOR_SENSORS: dict[str, str] = {
    "PURCHASE": "Purchase power",
    "PRODUCTION": "Production power",
    "CONSUMPTION": "Consumption power",
}


def _as_float(value: Any) -> float | None:
    """Return the value as a float, or None when the device sent nothing."""
    if value is None:
        return None
    return float(value)


def _as_date(value: Any) -> date | None:
    """Return an ISO date string as a date, or None when it is missing."""
    if not value:
        return None
    return date.fromisoformat(value)


class KiwiOsEdgeParser:
    """Build and update the sensors of the aggregated KiwiOS Edge API."""

    def __init__(self) -> None:
        """Initialize an empty parser."""
        self._entities: list[SensorEntity] = []
        self._energy_sensors: dict[str, KiwiOsSensorEntity] = {}
        self._power_sensors: dict[tuple[str, str], KiwiOsSensorEntity] = {}
        self._status_sensors: dict[str, KiwiOsSensorEntity] = {}
        self._gateway_id: str = DOMAIN
        self._gateway_device_info: DeviceInfo | None = None

    def get_entities(self) -> list[SensorEntity]:
        """Return every entity created so far."""
        return self._entities

    @property
    def gateway_identifier(self) -> tuple[str, str]:
        """Return the device identifier of the gateway."""
        return (DOMAIN, self._gateway_id)

    # -- entity helpers -------------------------------------------------

    @staticmethod
    def _sensor(
        coordinator: KiwiOsDataUpdateCoordinator,
        *,
        name: str,
        unique_id: str,
        device_info: DeviceInfo,
        native_unit: str | None = None,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
    ) -> KiwiOsSensorEntity:
        """Create a value sensor that is filled in by the parser."""
        # Imported lazily to avoid a circular import with sensor.py.
        from .sensor import KiwiOsSensorEntity

        sensor = KiwiOsSensorEntity(
            coordinator=coordinator, item_name=unique_id, item_id=unique_id
        )
        sensor._attr_name = name
        sensor._attr_unique_id = unique_id
        sensor._attr_device_info = device_info
        sensor._attr_native_unit_of_measurement = native_unit
        sensor._attr_device_class = device_class
        sensor._attr_state_class = state_class
        return sensor

    # -- setup ----------------------------------------------------------

    def parse_gateway(
        self, gateway_info: dict[str, Any], coordinator: KiwiOsDataUpdateCoordinator
    ) -> DeviceInfo:
        """Create the description of the gateway itself."""
        serial_number = gateway_info.get("serialNumber", "")
        self._gateway_id = serial_number or DOMAIN
        device_info = DeviceInfo(
            identifiers={(DOMAIN, self._gateway_id)},
            manufacturer=MANUFACTURER,
            model="Ampere.IQ Smartbox",
            name="KiwiOS Gateway",
            serial_number=serial_number or None,
            sw_version=gateway_info.get("emSetupFeatureVersion") or None,
        )

        version_sensor = self._sensor(
            coordinator,
            name="KiwiOS Edge version",
            unique_id=f"{self._gateway_id}_edge_version",
            device_info=device_info,
        )
        version_sensor._attr_entity_category = EntityCategory.DIAGNOSTIC
        version_sensor._attr_native_value = gateway_info.get("kiwiOsEdgeVersion")
        self._entities.append(version_sensor)
        self._gateway_device_info = device_info
        return device_info

    def parse_energy_overview(
        self, energy_overview: dict[str, Any], coordinator: KiwiOsDataUpdateCoordinator
    ) -> None:
        """Create the sensors of the aggregated power flows and fill them in."""
        device_info = self._gateway_device()
        for key, label in _ENERGY_OVERVIEW_SENSORS.items():
            sensor = self._sensor(
                coordinator,
                name=label,
                unique_id=f"{self._gateway_id}_energy_overview_{key}",
                device_info=device_info,
                native_unit=UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
            )
            self._energy_sensors[key] = sensor
            self._entities.append(sensor)
        self.apply_energy_overview(energy_overview)

    def parse_things(
        self,
        things: list[dict[str, Any]],
        coordinator: KiwiOsDataUpdateCoordinator,
        gateway_device_id: str,
    ) -> dict[str, DeviceInfo]:
        """Create one device and one status sensor per configured device."""
        devices: dict[str, DeviceInfo] = {}
        for thing in things:
            thing_id: str = thing["id"]
            device_info = DeviceInfo(
                identifiers={(DOMAIN, thing_id)},
                manufacturer=MANUFACTURER,
                model=thing.get("thingType", {}).get("title"),
                name=thing.get("label", thing_id),
                serial_number=thing.get("serialNumber") or None,
                via_device_id=gateway_device_id,
            )
            devices[thing_id] = device_info

            status_sensor = self._sensor(
                coordinator,
                name="Status",
                unique_id=f"{thing_id}_status",
                device_info=device_info,
            )
            status_sensor._attr_entity_category = EntityCategory.DIAGNOSTIC
            status_sensor._attr_native_value = self._status(thing)
            self._status_sensors[thing_id] = status_sensor
            self._entities.append(status_sensor)
        return devices

    def parse_power_indicators(
        self,
        power_indicators: list[dict[str, Any]],
        coordinator: KiwiOsDataUpdateCoordinator,
        devices: dict[str, DeviceInfo],
    ) -> None:
        """Create one power sensor per reported power of a device."""
        for indicator in power_indicators:
            thing_id: str = indicator["thingId"]
            indicator_type: str = indicator["type"]
            device_info = devices.get(thing_id)
            if device_info is None:
                _LOGGER.debug(
                    "Ignoring power indicator of the unknown device %s", thing_id
                )
                continue

            sensor = self._sensor(
                coordinator,
                name=_POWER_INDICATOR_SENSORS.get(
                    indicator_type, indicator_type.title()
                ),
                unique_id=f"{thing_id}_{indicator_type.lower()}_power",
                device_info=device_info,
                native_unit=UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
            )
            sensor._attr_native_value = _as_float(indicator.get("value"))
            self._power_sensors[(thing_id, indicator_type)] = sensor
            self._entities.append(sensor)

    def parse_pv_plants(
        self,
        pv_plants: list[dict[str, Any]],
        coordinator: KiwiOsDataUpdateCoordinator,
        gateway_device_id: str,
    ) -> None:
        """Create the configuration sensors of every PV plant."""
        for pv_plant in pv_plants:
            plant_id: str = pv_plant["pvPlantUuid"]
            config: dict[str, Any] = pv_plant.get("config") or {}
            device_info = DeviceInfo(
                identifiers={(DOMAIN, plant_id)},
                manufacturer=MANUFACTURER,
                model="PV plant",
                name=config.get("label") or plant_id,
                via_device_id=gateway_device_id,
            )

            peak_power = self._sensor(
                coordinator,
                name="Peak power",
                unique_id=f"{plant_id}_peak_power",
                device_info=device_info,
                native_unit=UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
            )
            peak_power._attr_native_value = _as_float(config.get("peakPower"))

            curtailment = self._sensor(
                coordinator,
                name="Curtailment",
                unique_id=f"{plant_id}_curtailment",
                device_info=device_info,
                native_unit=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            )
            curtailment._attr_native_value = _as_float(
                config.get("curtailmentPercentage")
            )

            installation_date = self._sensor(
                coordinator,
                name="Installation date",
                unique_id=f"{plant_id}_installation_date",
                device_info=device_info,
                device_class=SensorDeviceClass.DATE,
            )
            installation_date._attr_native_value = _as_date(
                config.get("installationDate")
            )

            self._entities.extend([peak_power, curtailment, installation_date])

    # -- updates --------------------------------------------------------

    async def async_refresh(self, api: KiwiOsApi) -> None:
        """Poll every endpoint that reports a changing value."""
        self.apply_energy_overview(await api.get_edge_energy_overview())
        self.apply_power_indicators(await api.get_edge_power_indicators())
        self.apply_things(await api.get_edge_things())

    def apply_energy_overview(self, energy_overview: dict[str, Any]) -> None:
        """Apply the aggregated power flows to their sensors."""
        for key, sensor in self._energy_sensors.items():
            sensor._attr_native_value = _as_float(energy_overview.get(key))

    def apply_power_indicators(self, power_indicators: list[dict[str, Any]]) -> None:
        """Apply the device powers to their sensors."""
        for indicator in power_indicators:
            sensor = self._power_sensors.get((indicator["thingId"], indicator["type"]))
            if sensor is not None:
                sensor._attr_native_value = _as_float(indicator.get("value"))

    def apply_things(self, things: list[dict[str, Any]]) -> None:
        """Apply the device statuses to their sensors."""
        for thing in things:
            sensor = self._status_sensors.get(thing["id"])
            if sensor is not None:
                sensor._attr_native_value = self._status(thing)

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _status(thing: dict[str, Any]) -> str | None:
        """Return the status string of a device."""
        return thing.get("statusInfo", {}).get("status")

    def _gateway_device(self) -> DeviceInfo:
        """Return the device information of the gateway."""
        assert self._gateway_device_info is not None
        return self._gateway_device_info
