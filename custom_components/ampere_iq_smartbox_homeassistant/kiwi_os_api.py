"""API client for interacting with Ampere IQ Smartbox.

This module provides an API wrapper for communicating with Ampere IQ Smartbox devices,
handling authentication, session management and HTTP requests.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Callable, Any

import aiohttp

from homeassistant.components.http import URL

_DBG_DISABLE_CONTENT_CHECK = True
_JSON_CONTENT_TYPE = "application/json"

if _DBG_DISABLE_CONTENT_CHECK:
    _JSON_CONTENT_TYPE = None

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
    """API client for Ampere IQ Smartbox.

    Handles HTTP requests, authentication (login) and session cookie
    management for communicating with Ampere IQ Smartbox devices.
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
        """
        self.session = session
        self.url = url
        self.password = password
        self._kiwisessionid_changed = kiwisessionid_changed_callback
        if kiwisessionid and (
            "kiwisessionid" not in session.cookie_jar.filter_cookies(url)
        ):
            session.cookie_jar.update_cookies(
                {"kiwisessionid": kiwisessionid}, response_url=url
            )

    @asynccontextmanager
    async def _get(
        self, path: str, retry: bool
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        """Perform a GET request and return response object."""
        response = await self.session.get(
            self.url.join(URL(path)), allow_redirects=False
        )
        try:
            if 200 <= response.status < 300:
                yield response
                return
            if not retry:
                response.raise_for_status()
                raise aiohttp.ClientResponseError(
                    response.request_info,
                    response.history,
                    status=response.status,
                    message=f"GET {path} failed",
                    headers=response.headers,
                )
            if 300 <= response.status < 400:
                location = response.headers.get("Location", "")
                if location.endswith("/logon.html"):
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
        """Perform a POST request and return response object."""
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
                raise aiohttp.ClientResponseError(
                    response.request_info,
                    response.history,
                    status=response.status,
                    message=f"POST {path} failed",
                    headers=response.headers,
                )
            if 300 <= response.status < 400:
                location = response.headers.get("Location", "")
                if location.endswith("/logon.html"):
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
        """Perform login to obtain kiwisessionid cookie.

        Returns:
            True if login was successful, False otherwise.
        """

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
            cookie = response.cookies.get("kiwisessionid")
            kiwisessionid = cookie.value if cookie is not None else ""

            if 200 <= response.status < 400:
                if kiwisessionid:
                    if self._kiwisessionid_changed:
                        self._kiwisessionid_changed(kiwisessionid)
                    return
                if location.endswith("/logon-error.html"):
                    raise PasswordInvalidException
            response.raise_for_status()
            if not kiwisessionid:
                raise aiohttp.ClientResponseError(
                    response.request_info,
                    response.history,
                    status=response.status,
                    message="Server did not set kiwisessionid cookie",
                    headers=response.headers,
                )
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=response.status,
                message="Unexpected login response",
                headers=response.headers,
            )

    def get_kiwisessionid(self) -> str:
        """Get the current kiwisessionid cookie value.

        Returns:
            The kiwisessionid cookie value as a string, or an empty string if not found.
        """
        cookies = self.session.cookie_jar.filter_cookies(self.url)
        if "kiwisessionid" in cookies:
            return cookies["kiwisessionid"].value
        return ""

    async def get_rest(self) -> Any:
        """Fetch the /rest endpoint."""
        return await self._get_json("/rest")

    async def get_things(self) -> Any:
        """Fetch the /rest/things endpoint."""
        return await self._get_json("/rest/things")

    async def get_items(self) -> Any:
        """Fetch the /rest/items endpoint."""
        return await self._get_json("/rest/items")
