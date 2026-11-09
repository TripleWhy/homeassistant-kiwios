"""Tests for the Ampere.IQ config flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import aiohttp
import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.kiwios import config_flow
from custom_components.kiwios.config_flow import (
    KiwiOsConfigFlow,
)
from custom_components.kiwios.const import DOMAIN
from custom_components.kiwios.kiwi_os_api import (
    PasswordInvalidException,
    PasswordRequiredException,
)

from .fakes import FakeSession

class FakeApi:
    """Stand-in for KiwiOsApi used by the config flow."""

    def __init__(
        self,
        *,
        login_error: Exception | None = None,
        rest_error: Exception | None = None,
        session_id: str = "test-session",
    ) -> None:
        """Store the behaviour the tests want to exercise."""
        self.login_error = login_error
        self.rest_error = rest_error
        self.session_id = session_id
        self.logged_in = False
        self.rest_called = False

    async def login(self) -> None:
        """Optionally raise, otherwise record the login."""
        self.logged_in = True
        if self.login_error is not None:
            raise self.login_error

    async def get_rest(self) -> Any:
        """Optionally raise, otherwise return a payload."""
        self.rest_called = True
        if self.rest_error is not None:
            raise self.rest_error
        return {"ok": True}

    def get_kiwisessionid(self) -> str:
        """Return the configured session id."""
        return self.session_id


def install_api(
    monkeypatch: pytest.MonkeyPatch, session: FakeSession, api: FakeApi
) -> dict[str, Any]:
    """Replace the API client and client session used by the flow."""
    captured: dict[str, Any] = {}

    def factory(**kwargs: Any) -> FakeApi:
        captured.update(kwargs)
        return api

    monkeypatch.setattr(config_flow, "KiwiOsApi", factory)
    monkeypatch.setattr(
        config_flow.aiohttp_client,
        "async_create_clientsession",
        lambda *args, **kwargs: session,
    )
    return captured


async def start_flow(hass: HomeAssistant) -> dict[str, Any]:
    """Start the user step and return the form result."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


def test_flow_version() -> None:
    """The config flow version is stable."""
    assert KiwiOsConfigFlow.VERSION == 1


async def test_user_step_shows_form(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first step renders the URL/password form."""
    result = await start_flow(hass)

    assert result["data_schema"] is config_flow.DATA_SCHEMA
    assert result.get("errors") is None
    assert result.get("description_placeholders") is None


async def test_user_step_creates_entry_with_password(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reachable device creates an entry and logs in."""
    session = FakeSession()
    api = FakeApi(session_id="abc123")
    captured = install_api(monkeypatch, session, api)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "http://box.local/", CONF_PASSWORD: "secret"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "http://box.local"
    assert result["data"] == {
        CONF_URL: "http://box.local",
        CONF_PASSWORD: "secret",
        "kiwisessionid": "abc123",
    }
    assert api.logged_in is True
    assert api.rest_called is True
    assert captured["password"] == "secret"
    assert captured["session"] is session
    assert session.detached is True


async def test_user_step_skips_login_without_password(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a password the login endpoint is not called."""
    session = FakeSession()
    api = FakeApi()
    captured = install_api(monkeypatch, session, api)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "http://box.local/"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PASSWORD] == ""
    assert api.logged_in is False
    assert api.rest_called is True
    assert captured["password"] == ""
    assert session.detached is True


async def test_user_step_adds_scheme_and_strips_slash(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare host gets http:// and trailing slashes are removed."""
    session = FakeSession()
    api = FakeApi()
    captured = install_api(monkeypatch, session, api)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "10.0.0.2/"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "http://10.0.0.2"
    assert captured["url"].scheme == "http"
    assert captured["url"].host == "10.0.0.2"
    assert str(captured["url"]) == "http://10.0.0.2"


async def test_user_step_password_required(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A device that requires a password reports the field error."""
    session = FakeSession()
    api = FakeApi(login_error=PasswordRequiredException())
    install_api(monkeypatch, session, api)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "http://box.local/", CONF_PASSWORD: "x"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"password": "required"}
    assert session.detached is True


async def test_user_step_password_invalid(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected password reports the field error."""
    session = FakeSession()
    api = FakeApi(login_error=PasswordInvalidException())
    install_api(monkeypatch, session, api)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "http://box.local/", CONF_PASSWORD: "x"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"password": "invalid_password"}


async def test_user_step_unexpected_response(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An HTTP error is surfaced with its detail."""
    error = aiohttp.ClientResponseError(
        Mock(), (), status=500, message="server exploded"
    )
    session = FakeSession()
    api = FakeApi(rest_error=error)
    install_api(monkeypatch, session, api)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "http://box.local/"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unexpected_response"}
    assert result["description_placeholders"] == {"error_detail": str(error)}


async def test_user_step_timeout(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout is reported as such."""
    session = FakeSession()
    api = FakeApi(rest_error=TimeoutError())
    install_api(monkeypatch, session, api)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "http://box.local/"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "timeout"}


async def test_user_step_cannot_connect(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connection error is reported as such."""
    error = aiohttp.ClientConnectorError(None, OSError("no route"))
    session = FakeSession()
    api = FakeApi(rest_error=error)
    install_api(monkeypatch, session, api)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "http://box.local/"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_step_generic_client_error(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any other client error is reported with its detail."""
    error = aiohttp.ClientError("boom")
    session = FakeSession()
    api = FakeApi(rest_error=error)
    install_api(monkeypatch, session, api)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "http://box.local/"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unexpected_error"}
    assert result["description_placeholders"] == {"error_detail": "boom"}
