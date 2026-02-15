"""Config flow for the Ampere IQ SmartBox Home Assistant integration.

This module implements the UI configuration flow used to set up the Ampere
integration, prompting for the device URL and optional password and handling
authentication and initial API validation.
"""

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.http import URL
from homeassistant.const import CONF_PASSWORD, CONF_URL
from homeassistant.helpers import aiohttp_client

from .const import DOMAIN
from .kiwi_os_api import KiwiOsApi, PasswordInvalidException, PasswordRequiredException

# import aiohttp_socks

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
    }
)


class AmpereConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Ampere PV integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Handle the user step in the configuration flow.

        Parameters
        ----------
        user_input : dict, optional
            The input provided by the user during the configuration step.

        Returns:
        -------
        dict
            The result of the configuration step.
        """
        errors = {}
        description_placeholders = {}
        if user_input is not None:
            # session = aiohttp.ClientSession(
            #     connector=aiohttp_socks.ProxyConnector.from_url(
            #         "socks5://192.168.178.62:8889"
            #     ),
            #     cookie_jar=aiohttp.CookieJar(unsafe=True),
            #     timeout=aiohttp.ClientTimeout(
            #         total=60, connect=30, sock_connect=10, sock_read=30
            #     ),
            # )
            session = aiohttp_client.async_create_clientsession(
                self.hass,
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                timeout=aiohttp.ClientTimeout(
                    total=60, connect=30, sock_connect=10, sock_read=30
                ),
                auto_cleanup=False,
            )
            try:
                url_str = user_input[CONF_URL].rstrip("/")
                if "://" not in url_str:
                    url_str = "http://" + url_str
                url = URL(url_str)
                password = user_input.get(CONF_PASSWORD, "")

                api = KiwiOsApi(
                    url=url,
                    session=session,
                    password=password,
                )
                if password:
                    await api.login()
                await api.get_rest()

                return self.async_create_entry(
                    title=str(url),
                    data={
                        CONF_URL: str(url),
                        CONF_PASSWORD: password,
                        "kiwisessionid": api.get_kiwisessionid(),
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

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)
