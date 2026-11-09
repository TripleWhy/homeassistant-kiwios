"""The Ampere.IQ integration."""

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
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_KIWISESSIONID, SESSION_TIMEOUT
from .kiwi_os_api import KiwiOsApi, KiwiOsApiItems
from .kiwi_os_parser import KiwiOsParser

if TYPE_CHECKING:
    from .sensor import KiwiOsSensorEntity

_PLATFORMS: list[Platform] = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = 60  # seconds
REQUEST_REFRESH_DELAY = 0.5

type KiwiOsConfigEntry = ConfigEntry[KiwiOsData]
type KiwiOsDataUpdateCoordinator = DataUpdateCoordinator[KiwiOsApiItems]


@dataclass
class KiwiOsData:
    """Data for the Ampere.IQ integration."""

    coordinator: KiwiOsDataUpdateCoordinator
    api: KiwiOsApi
    parser: KiwiOsParser


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
    parser = KiwiOsParser()

    async def async_update_data() -> None:
        """Poll the device and refresh every parsed value."""
        items = parser.map_json_items(await api.get_items())
        parser.parse_item_values(items)

    coordinator: KiwiOsDataUpdateCoordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="ampereiq",
        update_method=async_update_data,
        update_interval=timedelta(seconds=UPDATE_INTERVAL),
        request_refresh_debouncer=Debouncer(
            hass, _LOGGER, cooldown=REQUEST_REFRESH_DELAY, immediate=False
        ),
    )

    json_things: Any = await api.get_things()
    items: KiwiOsApiItems = parser.map_json_items(await api.get_items())
    value_sensors: list[KiwiOsSensorEntity] = parser.parse_things(
        json_things, coordinator
    )
    parser.create_entities(items, value_sensors)
    parser.guess_item_types(items, value_sensors)

    # The first refresh initializes the coordinator before entities are added.
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        _LOGGER.error("Failed to fetch initial data from AmpereIQ")
        return False

    entry.runtime_data = KiwiOsData(coordinator=coordinator, api=api, parser=parser)
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: KiwiOsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
