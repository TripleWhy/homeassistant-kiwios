"""API client for interacting with KiwiOS devices.

This module provides an API wrapper for communicating with devices running
KiwiOS, such as the EKD Ampere.IQ Smartbox, handling authentication, session
management and HTTP requests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import aiohttp
from yarl import URL

from .const import CONF_KIWISESSIONID, EDGE_API_PATH

# The device does not reliably tag its JSON replies with the application/json
# content type, so response decoding must not validate it.
_JSON_CONTENT_TYPE: str | None = None

_LOGON_SUFFIX = "/logon.html"
_LOGON_ERROR_SUFFIX = "/logon-error.html"

type KiwiOsApiItems = dict[str, Any]


class PasswordRequiredException(Exception):
    """Exception raised when the device requires a password but none is provided."""

    def __init__(self, message: str | None = None) -> None:
        """Initialize the exception with an optional message."""
        super().__init__(message or "Invalid password")


class PasswordInvalidException(Exception):
    """Exception raised when the provided password for the device is invalid."""

    def __init__(self, message: str | None = None) -> None:
        """Initialize the exception with an optional message."""
        super().__init__(message or "Invalid password")


class KiwiOsApi:
    """API client for devices running KiwiOS.

    Handles HTTP requests, authentication (login) and session cookie
    management for communicating with devices running KiwiOS.
    """

    def __init__(
        self,
        url: URL,
        session: aiohttp.ClientSession,
        password: str = "",
        kiwisessionid: str = "",
        kiwisessionid_changed_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the API wrapper.

        Args:
            url: Base URL for the API.
            session: aiohttp client session to use for requests.
            password: Optional password for authentication.
            kiwisessionid: Optional kiwisessionid cookie to set in the session.
            kiwisessionid_changed_callback: Called when the device rotates the
                session cookie.
        """
        self.session = session
        self.url = url
        self.password = password
        self._kiwisessionid_changed = kiwisessionid_changed_callback
        if kiwisessionid and (
            CONF_KIWISESSIONID not in session.cookie_jar.filter_cookies(url)
        ):
            session.cookie_jar.update_cookies(
                {CONF_KIWISESSIONID: kiwisessionid}, response_url=url
            )

    @staticmethod
    def _response_error(
        response: aiohttp.ClientResponse, message: str
    ) -> aiohttp.ClientResponseError:
        """Build a response error for a handled-but-unexpected response."""
        return aiohttp.ClientResponseError(
            response.request_info,
            response.history,
            status=response.status,
            message=message,
            headers=response.headers,
        )

    @staticmethod
    def _is_login_redirect(response: aiohttp.ClientResponse) -> bool:
        """Return whether the response is a redirect to the login page."""
        return 300 <= response.status < 400 and response.headers.get(
            "Location", ""
        ).endswith(_LOGON_SUFFIX)

    @asynccontextmanager
    async def _get(
        self, path: str, retry: bool
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        """Perform a GET request and yield the response."""
        response = await self.session.get(
            self.url.join(URL(path)), allow_redirects=False
        )
        try:
            if 200 <= response.status < 300:
                yield response
                return
            if not retry:
                response.raise_for_status()
                raise self._response_error(response, f"GET {path} failed")
            if response.status == 401 or self._is_login_redirect(response):
                await self.login()
                async with self._get(path, retry=False) as retry_response:
                    yield retry_response
                return

            response.raise_for_status()
            yield response
        finally:
            await response.release()

    @asynccontextmanager
    async def _post(
        self, path: str, data: Any, retry: bool, skip_response_handling: bool = False
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        """Perform a POST request and yield the response."""
        response = await self.session.post(
            self.url.join(URL(path)),
            data=data,
            allow_redirects=False,
        )
        try:
            if skip_response_handling or 200 <= response.status < 300:
                yield response
                return
            if not retry:
                response.raise_for_status()
                raise self._response_error(response, f"POST {path} failed")
            if self._is_login_redirect(response):
                await self.login()
                async with self._post(
                    path,
                    data,
                    retry=False,
                    skip_response_handling=skip_response_handling,
                ) as retry_response:
                    yield retry_response
                return

            response.raise_for_status()
            yield response
        finally:
            await response.release()

    async def _get_json(self, path: str) -> Any:
        """Perform a GET request and return parsed JSON."""
        async with self._get(path, retry=True) as response:
            return await response.json(content_type=_JSON_CONTENT_TYPE)

    async def login(self) -> None:
        """Perform login to obtain the kiwisessionid cookie."""
        if not self.password:
            raise PasswordRequiredException

        async with self._post(
            path="auth/login",
            data={
                "username": "installer",
                "url": "/rest",
                "password": self.password,
                "submit": "Login",
            },
            retry=False,
            skip_response_handling=True,
        ) as response:
            location = response.headers.get("Location", "")
            cookie = response.cookies.get(CONF_KIWISESSIONID)
            kiwisessionid = cookie.value if cookie is not None else ""

            if 200 <= response.status < 400:
                if kiwisessionid:
                    if self._kiwisessionid_changed:
                        self._kiwisessionid_changed(kiwisessionid)
                    return
                if location.endswith(_LOGON_ERROR_SUFFIX):
                    raise PasswordInvalidException

            response.raise_for_status()
            if not kiwisessionid:
                raise self._response_error(
                    response, "Server did not set kiwisessionid cookie"
                )
            raise self._response_error(response, "Unexpected login response")

    def get_kiwisessionid(self) -> str:
        """Return the current kiwisessionid cookie value, or an empty string."""
        cookie = self.session.cookie_jar.filter_cookies(self.url).get(
            CONF_KIWISESSIONID
        )
        return cookie.value if cookie is not None else ""

    async def get_things(self) -> Any:
        """Fetch the /rest/things endpoint."""
        return await self._get_json("/rest/things")

    async def get_items(self) -> Any:
        """Fetch the /rest/items endpoint."""
        return await self._get_json("/rest/items")

    # -- KiwiOS Edge ----------------------------------------------------

    async def get_edge_things(self) -> Any:
        """Fetch the configured devices of a KiwiOS Edge device."""
        return await self._get_json(f"{EDGE_API_PATH}/things")

    async def get_edge_gateway_info(self) -> Any:
        """Fetch the gateway identity and the installed versions."""
        return await self._get_json(f"{EDGE_API_PATH}/public/gateway/info")

    async def get_edge_gateway_info_if_present(self) -> Any | None:
        """Return the gateway info, or None for firmware serving the older API.

        The current API is assumed first, so a device running it spends no
        request on detection: the answer is the one the setup needs anyway.
        Firmware without it answers 404 and falls back to the per-channel API.
        """
        try:
            return await self.get_edge_gateway_info()
        except aiohttp.ClientResponseError as error:
            if error.status != 404:
                raise
            return None

    async def get_edge_energy_overview(self) -> Any:
        """Fetch the aggregated power flows of the whole installation."""
        return await self._get_json(f"{EDGE_API_PATH}/energy-overview")

    async def get_edge_power_indicators(self) -> Any:
        """Fetch the instantaneous power of every device."""
        return await self._get_json(f"{EDGE_API_PATH}/power-indicator")

    async def get_edge_pv_plants(self) -> Any:
        """Fetch the configured PV plants."""
        return await self._get_json(f"{EDGE_API_PATH}/pv-plants")
