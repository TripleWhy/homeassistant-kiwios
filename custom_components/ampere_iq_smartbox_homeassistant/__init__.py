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
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, timedelta

from .kiwi_os_api import KiwiOsApi

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


@dataclass
class KiwiOsData:
    """Data for the Ampere.IQ integration."""

    coordinator: DataUpdateCoordinator
    api: KiwiOsApi
    things: Any


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

    api = KiwiOsApi(
        url=url,
        session=session,
        password=password,
        kiwisessionid=kiwisessionid,
    )
    things = await api.get_things()

    async def async_update_data():
        print("async_update_data")
        return await api.get_items()

    coordinator = DataUpdateCoordinator(
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

    # First fetch to initialize coordinator
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        _LOGGER.error("Failed to fetch initial data from AmpereIQ")
        return False

    entry.runtime_data = KiwiOsData(coordinator=coordinator, api=api, things=things)

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: KiwiOsConfigEntry) -> bool:
    """Unload a config entry."""
    # api = entry.runtime_data
    # await api.close()
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
