"""Test component setup."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_URL, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from homeassistant.setup import async_setup_component

from custom_components.ampere_iq_smartbox_homeassistant import (
    _PLATFORMS,
    REQUEST_REFRESH_DELAY,
    UPDATE_INTERVAL,
    KiwiOsData,
    async_unload_entry,
)
from custom_components.ampere_iq_smartbox_homeassistant.const import DOMAIN
from custom_components.ampere_iq_smartbox_homeassistant.kiwi_os_api import KiwiOsApi

from .fakes import FakeSession

ENTRY_DATA = {
    CONF_URL: "http://box.local/",
    CONF_PASSWORD: "secret",
}


@pytest.fixture
async def session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    """Replace the aiohttp session with a fake one."""
    fake_session = FakeSession()
    monkeypatch.setattr(
        "custom_components.ampere_iq_smartbox_homeassistant.aiohttp_client."
        "async_create_clientsession",
        lambda *args, **kwargs: fake_session,
    )
    return fake_session


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, things, json_items) -> dict[str, Any]:
    """Return patched API methods for the setup flow."""
    get_things = AsyncMock(return_value=things)
    get_items = AsyncMock(return_value=json_items)
    monkeypatch.setattr(KiwiOsApi, "get_things", get_things)
    monkeypatch.setattr(KiwiOsApi, "get_items", get_items)
    return {"get_things": get_things, "get_items": get_items}


def make_entry(**data: Any) -> MockConfigEntry:
    """Create a config entry for the integration."""
    return MockConfigEntry(domain=DOMAIN, data={**ENTRY_DATA, **data})


async def test_async_setup(hass: HomeAssistant) -> None:
    """Test the component gets setup."""
    assert await async_setup_component(hass, DOMAIN, {}) is True


def test_setup_constants() -> None:
    """The polling constants and platforms keep their documented values."""
    assert UPDATE_INTERVAL == 60
    assert REQUEST_REFRESH_DELAY == 0.5
    assert _PLATFORMS == ["sensor"]


async def test_setup_entry(
    hass: HomeAssistant,
    session: FakeSession,
    api: dict[str, Any],
) -> None:
    """A successful setup stores runtime data and adds all sensors."""
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    data = entry.runtime_data
    assert isinstance(data, KiwiOsData)
    assert isinstance(data.api, KiwiOsApi)
    assert data.api.url == URL("http://box.local/")
    assert data.coordinator.last_update_success is True
    assert data.coordinator.update_interval == timedelta(seconds=UPDATE_INTERVAL)

    entities = data.parser.get_entities()
    assert len(entities) == 161
    # 99 value sensors and 62 embedded timestamp sensors.
    assert len(data.parser._value_sensors) == 99
    # Timestamp sensors are registered but hidden, so only the value sensors
    # have states.
    assert len(hass.states.async_entity_ids("sensor")) == 99

    # The initial fetch uses the coordinator's update method.
    assert api["get_things"].await_count == 1
    assert api["get_items"].await_count == 2


async def test_setup_entry_disables_timestamp_sensors(
    hass: HomeAssistant,
    session: FakeSession,
    api: dict[str, Any],
) -> None:
    """Timestamp sensors are registered, but only value sensors are enabled."""
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    registered = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(registered) == 161

    timestamp_entries = [
        item for item in registered if item.unique_id.endswith("_timestamp")
    ]
    value_entries = [
        item for item in registered if not item.unique_id.endswith("_timestamp")
    ]
    assert len(timestamp_entries) == 62
    assert len(value_entries) == 99

    for item in timestamp_entries:
        assert item.disabled_by is RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(item.entity_id) is None

    for item in value_entries:
        assert item.disabled_by is None
        assert hass.states.get(item.entity_id) is not None


async def test_setup_entry_session_options(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    api: dict[str, Any],
) -> None:
    """The client session is created with the device-friendly options."""
    session = FakeSession()
    created: dict[str, Any] = {}

    def create_session(*args: Any, **kwargs: Any) -> FakeSession:
        created.update(kwargs)
        return session

    monkeypatch.setattr(
        "custom_components.ampere_iq_smartbox_homeassistant.aiohttp_client."
        "async_create_clientsession",
        create_session,
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True

    assert isinstance(created["cookie_jar"], aiohttp.CookieJar)
    timeout = created["timeout"]
    assert isinstance(timeout, aiohttp.ClientTimeout)
    assert timeout.total == 60
    assert timeout.connect == 30
    assert timeout.sock_connect == 10
    assert timeout.sock_read == 30
    assert created["auto_cleanup"] is True


async def test_setup_entry_restores_session_id(
    hass: HomeAssistant,
    session: FakeSession,
    api: dict[str, Any],
) -> None:
    """A stored kiwisessionid is restored into the cookie jar."""
    entry = make_entry(kiwisessionid="stored-id")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True

    assert entry.runtime_data.api.get_kiwisessionid() == "stored-id"


async def test_setup_entry_persists_new_session_id(
    hass: HomeAssistant,
    session: FakeSession,
    api: dict[str, Any],
) -> None:
    """When the API rotates the cookie the config entry is updated."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True

    session.cookie_jar.update_cookies(
        {"kiwisessionid": "rotated"}, response_url=URL("http://box.local/")
    )
    entry.runtime_data.api._kiwisessionid_changed("rotated")

    assert entry.data["kiwisessionid"] == "rotated"


async def test_setup_entry_fails_when_initial_refresh_fails(
    hass: HomeAssistant,
    session: FakeSession,
    api: dict[str, Any],
) -> None:
    """A failing initial refresh aborts the setup."""
    api["get_items"].side_effect = [
        api["get_items"].return_value,
        aiohttp.ClientError("device gone"),
    ]
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is False
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert hass.states.async_entity_ids("sensor") == []


async def test_unload_entry(
    hass: HomeAssistant,
    session: FakeSession,
    api: dict[str, Any],
) -> None:
    """Unloading removes the platform and its entities."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    # Home Assistant keeps registry-backed entities as unavailable placeholders.
    assert all(
        hass.states.get(entity_id).state == STATE_UNAVAILABLE
        for entity_id in hass.states.async_entity_ids("sensor")
    )


async def test_unload_entry_returns_platform_result(
    hass: HomeAssistant,
    session: FakeSession,
    api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unload result of the platform is returned unchanged."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True

    monkeypatch.setattr(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=False),
    )

    assert await async_unload_entry(hass, entry) is False
