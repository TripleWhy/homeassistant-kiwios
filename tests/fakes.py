"""Small aiohttp doubles used by the unit tests.

The integration talks to an embedded device over HTTP.  These helpers let the
tests drive every response path (success, redirect, auth retry, malformed
payload, ...) without opening a socket.
"""

from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Any
from unittest.mock import Mock

import aiohttp
from yarl import URL


class FakeResponse:
    """Minimal stand-in for :class:`aiohttp.ClientResponse`."""

    def __init__(
        self,
        status: int = 200,
        *,
        headers: dict[str, str] | None = None,
        json_data: Any = None,
        cookies: dict[str, str] | None = None,
        raise_for_status: bool = True,
    ) -> None:
        """Initialize the fake response.

        ``raise_for_status`` controls whether :meth:`raise_for_status` actually
        raises for error statuses.  Turning it off lets the tests reach the
        defensive ``raise ClientResponseError`` calls that follow it.
        """
        self.status = status
        self.headers = dict(headers or {})
        self.cookies: SimpleCookie = SimpleCookie()
        for name, value in (cookies or {}).items():
            self.cookies[name] = value
            # Devices set the session cookie for the whole site.
            self.cookies[name]["path"] = "/"
        self.request_info = Mock()
        self.history: tuple[Any, ...] = ()
        self.released = False
        self.json_content_type: Any = "unset"
        self.raise_for_status_calls = 0
        self._json_data = json_data
        self._raise_for_status = raise_for_status

    def raise_for_status(self) -> None:
        """Mimic aiohttp's error handling for 4xx/5xx responses."""
        self.raise_for_status_calls += 1
        if self._raise_for_status and self.status >= 400:
            raise aiohttp.ClientResponseError(
                self.request_info,
                self.history,
                status=self.status,
                message=f"HTTP {self.status}",
                headers=self.headers,
            )

    async def json(self, content_type: str | None = "application/json") -> Any:
        """Return the canned JSON payload."""
        self.json_content_type = content_type
        return self._json_data

    async def release(self) -> None:
        """Mark the response as released."""
        self.released = True


class FakeSession:
    """Minimal stand-in for :class:`aiohttp.ClientSession`.

    Responses are queued per verb and returned in order.  Cookies set on a
    POST response are stored in the (real) cookie jar, just like aiohttp does
    for a ``Set-Cookie`` header.
    """

    def __init__(self) -> None:
        """Create the fake session with a real cookie jar."""
        self.cookie_jar = aiohttp.CookieJar(unsafe=True)
        self.get_calls: list[tuple[URL, bool]] = []
        self.post_calls: list[tuple[URL, Any, bool]] = []
        self.detached = False
        self.closed = False
        self._get_responses: list[FakeResponse] = []
        self._post_responses: list[FakeResponse] = []

    def queue_get(self, *responses: FakeResponse) -> None:
        """Queue responses for upcoming GET requests."""
        self._get_responses.extend(responses)

    def queue_post(self, *responses: FakeResponse) -> None:
        """Queue responses for upcoming POST requests."""
        self._post_responses.extend(responses)

    async def get(
        self, url: URL, *, allow_redirects: bool = True, **kwargs: Any
    ) -> FakeResponse:
        """Return the next queued GET response."""
        self.get_calls.append((url, allow_redirects))
        return self._get_responses.pop(0)

    async def post(
        self,
        url: URL,
        *,
        data: Any = None,
        allow_redirects: bool = True,
        **kwargs: Any,
    ) -> FakeResponse:
        """Return the next queued POST response and store its cookies."""
        self.post_calls.append((url, data, allow_redirects))
        response = self._post_responses.pop(0)
        for name, morsel in response.cookies.items():
            # aiohttp derives the cookie path from the response URL, so use
            # the origin to emulate a device that scopes the cookie to "/".
            self.cookie_jar.update_cookies(
                {name: morsel.value}, response_url=URL(str(url)).origin()
            )
        return response

    def detach(self) -> None:
        """Mimic ``ClientSession.detach``."""
        self.detached = True

    async def close(self) -> None:
        """Mimic ``ClientSession.close``."""
        self.closed = True
