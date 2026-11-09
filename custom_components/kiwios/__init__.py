"""The KiwiOS integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from yarl import URL

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client, device_registry as dr
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_KIWISESSIONID, SESSION_TIMEOUT
from .kiwi_os_api import KiwiOsApi, KiwiOsApiItems
from .kiwi_os_edge_parser import KiwiOsEdgeParser
from .kiwi_os_parser import KiwiOsParser

if TYPE_CHECKING:
    from .sensor import KiwiOsSensorEntity

_PLATFORMS: list[Platform] = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = 60  # seconds
REQUEST_REFRESH_DELAY = 0.5

type KiwiOsConfigEntry = ConfigEntry[KiwiOsData]
type KiwiOsDataUpdateCoordinator = DataUpdateCoordinator[KiwiOsApiItems]
type KiwiOsAnyParser = KiwiOsParser | KiwiOsEdgeParser


@dataclass
class KiwiOsData:
    """Data for the KiwiOS integration."""

    coordinator: KiwiOsDataUpdateCoordinator
    api: KiwiOsApi
    parser: KiwiOsAnyParser


def _create_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    """Create the HTTP session used to talk to the device."""
    return aiohttp_client.async_create_clientsession(
        hass,
        cookie_jar=aiohttp.CookieJar(unsafe=True),
        timeout=SESSION_TIMEOUT,
        auto_cleanup=True,
    )


async def async_setup_entry(hass: HomeAssistant, entry: KiwiOsConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    session = _create_session(hass)

    def update_kiwisessionid(kiwisessionid: str) -> None:
        """Persist a rotated session cookie in the config entry."""
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_KIWISESSIONID: kiwisessionid}
        )

    api = KiwiOsApi(
        url=URL(entry.data[CONF_URL]),
        session=session,
        password=entry.data[CONF_PASSWORD],
        kiwisessionid=entry.data.get(CONF_KIWISESSIONID, ""),
        kiwisessionid_changed_callback=update_kiwisessionid,
    )
    # The current API is asked for first, so a device running it does not
    # spend a request to find out which API it has.
    gateway_info = await api.get_edge_gateway_info_if_present()
    parser: KiwiOsAnyParser = (
        KiwiOsParser() if gateway_info is None else KiwiOsEdgeParser()
    )

    async def async_update_data() -> None:
        """Poll the device and refresh every parsed value."""
        if isinstance(parser, KiwiOsEdgeParser):
            await parser.async_refresh(api)
            return
        parser.parse_item_values(parser.map_json_items(await api.get_items()))

    coordinator: KiwiOsDataUpdateCoordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="kiwios",
        update_method=async_update_data,
        update_interval=timedelta(seconds=UPDATE_INTERVAL),
        request_refresh_debouncer=Debouncer(
            hass, _LOGGER, cooldown=REQUEST_REFRESH_DELAY, immediate=False
        ),
    )

    if isinstance(parser, KiwiOsEdgeParser):
        # Every value needed at setup is fetched once and used, so no initial
        # refresh is needed on top, unlike the per-channel API below.
        try:
            await _async_create_edge_entities(
                hass, entry, api, parser, coordinator, gateway_info
            )
        except (TimeoutError, aiohttp.ClientError):
            _LOGGER.exception("Failed to fetch initial data from KiwiOS")
            return False
    else:
        await _async_create_legacy_entities(api, parser, coordinator)
        # The first refresh initializes the coordinator before entities are
        # added.
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            _LOGGER.error("Failed to fetch initial data from KiwiOS")
            return False

    entry.runtime_data = KiwiOsData(coordinator=coordinator, api=api, parser=parser)
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def _async_create_legacy_entities(
    api: KiwiOsApi,
    parser: KiwiOsParser,
    coordinator: KiwiOsDataUpdateCoordinator,
) -> None:
    """Create the entities of the per-channel API."""
    json_things: Any = await api.get_things()
    items: KiwiOsApiItems = parser.map_json_items(await api.get_items())
    value_sensors: list[KiwiOsSensorEntity] = parser.parse_things(
        json_things, coordinator
    )
    parser.create_entities(items, value_sensors)
    parser.guess_item_types(items, value_sensors)


async def _async_create_edge_entities(
    hass: HomeAssistant,
    entry: KiwiOsConfigEntry,
    api: KiwiOsApi,
    parser: KiwiOsEdgeParser,
    coordinator: KiwiOsDataUpdateCoordinator,
    gateway_info: dict[str, Any],
) -> None:
    """Create the entities of the aggregated KiwiOS Edge API."""
    gateway_device = parser.parse_gateway(gateway_info, coordinator)
    # The gateway has to exist in the registry before the devices it connects
    # can reference it as their parent.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **gateway_device
    )
    gateway_device_id = dr.async_get_device_id_by_identifier(
        hass, parser.gateway_identifier, config_entry_id=entry.entry_id
    )

    devices = parser.parse_things(
        await api.get_edge_things(), coordinator, gateway_device_id
    )
    parser.parse_power_indicators(
        await api.get_edge_power_indicators(), coordinator, devices
    )
    parser.parse_pv_plants(
        await api.get_edge_pv_plants(), coordinator, gateway_device_id
    )
    parser.parse_energy_overview(await api.get_edge_energy_overview(), coordinator)
    # The setup already applied every value, so the coordinator starts healthy
    # without fetching anything again.
    coordinator.async_set_updated_data({})


async def async_unload_entry(hass: HomeAssistant, entry: KiwiOsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
