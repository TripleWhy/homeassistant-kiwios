import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_URL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import DOMAIN

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
    }
)


class AmpereConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Ampere PV integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            password = user_input.get(CONF_PASSWORD, "")

            # session = async_create_clientsession(self.hass)

            ### debug >>>
            import aiohttp_socks

            session = aiohttp.ClientSession(
                connector=aiohttp_socks.ProxyConnector.from_url(
                    "socks5://192.168.178.62:8889"
                )
            )
            ### debug <<<

            try:
                with async_timeout.timeout(10):
                    # Step 1: try GET /rest directly
                    response = await session.get(f"{url}/rest", allow_redirects=False)
                    if response.status == 200:
                        # direct json response assumed OK
                        content_type = response.headers.get("Content-Type", "")
                        if "application/json" in content_type:
                            # success without auth
                            # Save config without cookie (no authentication)
                            return self.async_create_entry(
                                title=url,
                                data={
                                    CONF_URL: url,
                                    CONF_PASSWORD: password,
                                    "kiwisessionid": None,
                                },
                            )
                        else:
                            errors["base"] = "unexpected_response"

                    elif 300 <= response.status < 400:
                        location = response.headers.get("Location", "")
                        if location.endswith("/logon.html"):
                            # Need to authenticate

                            if not password:
                                errors["password"] = "required"
                            else:
                                # Step 2: POST login with password
                                login_data = {
                                    "username": "installer",
                                    "url": "/rest",
                                    "password": password,
                                    "submit": "Login",
                                }
                                login_response = await session.post(
                                    f"{url}/auth/login",
                                    data=login_data,
                                    allow_redirects=False,
                                    headers={
                                        "Content-Type": "application/x-www-form-urlencoded"
                                    },
                                )
                                login_location = login_response.headers.get(
                                    "Location", ""
                                )
                                kiwisessionid = (
                                    login_response.cookies.get("kiwisessionid").value
                                    if login_response.cookies.get("kiwisessionid")
                                    else ""
                                )

                                if 200 <= login_response.status < 400:
                                    if kiwisessionid != "":
                                        # Success with authentication
                                        return self.async_create_entry(
                                            title=url,
                                            data={
                                                CONF_URL: url,
                                                CONF_PASSWORD: password,
                                                "kiwisessionid": kiwisessionid,
                                            },
                                        )
                                    if login_location.endswith("/logon-error.html"):
                                        errors["password"] = "invalid_password"
                                    else:
                                        errors["base"] = "unexpected_login_response"
                                else:
                                    errors["base"] = "unexpected_login_response"
                        else:
                            errors["base"] = "unexpected_redirect"

                    else:
                        errors["base"] = "unexpected_response"
            except TimeoutError:
                errors["base"] = "timeout"
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"

            return self.async_show_form(
                step_id="user", data_schema=DATA_SCHEMA, errors=errors
            )

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)
