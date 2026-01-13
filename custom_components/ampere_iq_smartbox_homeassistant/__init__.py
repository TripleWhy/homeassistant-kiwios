"""The Ampere.IQ integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import aiohttp
import aiohttp_socks

from homeassistant.components.http import URL
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)

from .kiwi_os_api import KiwiOsApi, KiwiOsApiItems
from .kiwi_os_parser import KiwiOsParser

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sensor import (
        KiwiOsDataUpdateCoordinator,
        KiwiOsSensorEntity,
        KiwiOsTimestampSensorEntity,
    )

# from kiwi_os_api import KiwiOsApi, KiwiOsApiItems
# from kiwi_os_parser import KiwiOsParser

_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    # Platform.BINARY_SENSOR,
    # Platform.NUMBER,
    # Platform.SWITCH,
    # Platform.BUTTON,
    # Platform.SELECT,
    # Platform.UPDATE,
]
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


async def async_setup_entry(hass: HomeAssistant, entry: KiwiOsConfigEntry) -> bool:
    """Set up from a config entry."""
    url: URL = URL(entry.data[CONF_URL])
    password: str = entry.data[CONF_PASSWORD]
    kiwisessionid: str = entry.data.get("kiwisessionid", "")

    # session = aiohttp_client.async_create_clientsession(
    #     hass,
    #     cookie_jar=aiohttp.CookieJar(unsafe=True),
    #     timeout=aiohttp.ClientTimeout(
    #         total=60, connect=30, sock_connect=10, sock_read=30
    #     ),
    #     auto_cleanup=True,
    # )
    session = aiohttp.ClientSession(
        connector=aiohttp_socks.ProxyConnector.from_url("socks5://192.168.178.62:8889"),
        cookie_jar=aiohttp.CookieJar(unsafe=True),
        timeout=aiohttp.ClientTimeout(
            total=60, connect=30, sock_connect=10, sock_read=30
        ),
    )

    async def async_update_data() -> None:
        print("async_update_data")
        json_items: Any = await api.get_items()
        items: KiwiOsApiItems = parser.map_json_items(json_items)
        parser.parse_item_values(items)

    coordinator: KiwiOsDataUpdateCoordinator = DataUpdateCoordinator[Any](
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

    api: KiwiOsApi = KiwiOsApi(
        url=url,
        session=session,
        password=password,
        kiwisessionid=kiwisessionid,
    )

    parser: KiwiOsParser = KiwiOsParser()
    json_things: Any = await api.get_things()
    json_items: Any = await api.get_items()
    items: KiwiOsApiItems = parser.map_json_items(json_items)
    value_sensors: list[KiwiOsSensorEntity] = parser.parse_things(
        json_things, coordinator
    )
    parser.create_entities(items, value_sensors)
    parser.guess_item_types(items, value_sensors)

    # First fetch to initialize coordinator
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        _LOGGER.error("Failed to fetch initial data from AmpereIQ")
        return False

    entry.runtime_data = KiwiOsData(coordinator=coordinator, api=api, parser=parser)

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: KiwiOsConfigEntry) -> bool:
    """Unload a config entry."""
    # api = entry.runtime_data
    # await api.close()
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
