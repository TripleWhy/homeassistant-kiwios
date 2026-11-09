"""Config flow for the Ampere IQ SmartBox integration.

This module implements the UI configuration flow used to set up the Ampere
integration, prompting for the device URL and optional password and handling
authentication and initial API validation.
"""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from yarl import URL

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_URL
from homeassistant.helpers import aiohttp_client

from .const import CONF_KIWISESSIONID, DOMAIN, SESSION_TIMEOUT
from .kiwi_os_api import KiwiOsApi, PasswordInvalidException, PasswordRequiredException

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
    }
)


def _normalize_url(raw_url: str) -> URL:
    """Normalize user input into a device base URL."""
    url_str = raw_url.rstrip("/")
    if "://" not in url_str:
        url_str = f"http://{url_str}"
    return URL(url_str)


class AmpereConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Ampere PV integration."""

    VERSION = 1

    def _create_session(self) -> aiohttp.ClientSession:
        """Create the temporary session used to validate the device."""
        return aiohttp_client.async_create_clientsession(
            self.hass,
            cookie_jar=aiohttp.CookieJar(unsafe=True),
            timeout=SESSION_TIMEOUT,
            auto_cleanup=False,
        )

    async def _validate_input(
        self, session: aiohttp.ClientSession, user_input: dict[str, Any]
    ) -> tuple[URL, str, str]:
        """Validate the device and return URL, password and session id."""
        url = _normalize_url(user_input[CONF_URL])
        password = user_input.get(CONF_PASSWORD, "")

        api = KiwiOsApi(
            url=url,
            session=session,
            password=password,
        )
        if password:
            await api.login()
        await api.get_rest()
        return url, password, api.get_kiwisessionid()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the user step in the configuration flow."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}
        session = self._create_session()
        try:
            url, password, kiwisessionid = await self._validate_input(
                session, user_input
            )
            return self.async_create_entry(
                title=str(url),
                data={
                    CONF_URL: str(url),
                    CONF_PASSWORD: password,
                    CONF_KIWISESSIONID: kiwisessionid,
                },
            )
        except PasswordRequiredException:
            errors["password"] = "required"
        except PasswordInvalidException:
            errors["password"] = "invalid_password"
        except aiohttp.ClientResponseError as error:
            errors["base"] = "unexpected_response"
            description_placeholders["error_detail"] = str(error)
        except TimeoutError:
            errors["base"] = "timeout"
        except aiohttp.ClientConnectorError:
            errors["base"] = "cannot_connect"
        except aiohttp.ClientError as error:
            errors["base"] = "unexpected_error"
            description_placeholders["error_detail"] = str(error)
        finally:
            session.detach()

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
            description_placeholders=description_placeholders,
        )
