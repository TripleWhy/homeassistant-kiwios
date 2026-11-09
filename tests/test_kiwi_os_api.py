"""Tests for the Ampere.IQ HTTP API client."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from yarl import URL

from custom_components.kiwios.kiwi_os_api import (
    KiwiOsApi,
    KiwiOsApiItems,
    PasswordInvalidException,
    PasswordRequiredException,
)

from .fakes import FakeResponse, FakeSession

URL_BASE = URL("http://box.local/")


@pytest.fixture
async def session() -> FakeSession:
    """Return a fake aiohttp session."""
    return FakeSession()


@pytest.fixture
async def api(session: FakeSession) -> KiwiOsApi:
    """Return an API client without a password."""
    return KiwiOsApi(url=URL_BASE, session=session)


def test_api_items_alias_is_a_dict_alias() -> None:
    """The exported items alias refers to a plain dict."""
    assert KiwiOsApiItems.__value__ == dict[str, Any]


def test_exceptions_default_message() -> None:
    """Both login exceptions default to a human readable message."""
    assert str(PasswordRequiredException()) == "Invalid password"
    assert str(PasswordInvalidException()) == "Invalid password"


def test_exceptions_custom_message() -> None:
    """Both login exceptions accept a custom message."""
    assert str(PasswordRequiredException("need password")) == "need password"
    assert str(PasswordInvalidException("bad password")) == "bad password"


async def test_init_without_session_id_leaves_cookie_jar_empty(
    session: FakeSession,
) -> None:
    """No cookie is written when no session id is supplied."""
    KiwiOsApi(url=URL_BASE, session=session)
    assert "kiwisessionid" not in session.cookie_jar.filter_cookies(URL_BASE)


async def test_init_stores_session_id_in_cookie_jar(session: FakeSession) -> None:
    """A supplied session id is restored into the cookie jar."""
    api = KiwiOsApi(url=URL_BASE, session=session, kiwisessionid="stored")
    assert api.get_kiwisessionid() == "stored"


async def test_init_keeps_existing_session_id_cookie(session: FakeSession) -> None:
    """An already-present cookie is not overwritten."""
    session.cookie_jar.update_cookies(
        {"kiwisessionid": "existing"}, response_url=URL_BASE
    )
    api = KiwiOsApi(url=URL_BASE, session=session, kiwisessionid="ignored")
    assert api.get_kiwisessionid() == "existing"


async def test_get_kiwisessionid_without_cookie(api: KiwiOsApi) -> None:
    """An empty string is returned when the cookie is absent."""
    assert api.get_kiwisessionid() == ""


async def test_get_json_success(api: KiwiOsApi, session: FakeSession) -> None:
    """A 2xx response is yielded, decoded and released."""
    response = FakeResponse(json_data={"ok": True})
    session.queue_get(response)

    assert await api.get_edge_energy_overview() == {"ok": True}

    assert session.get_calls == [
        (URL("http://box.local/rest/hems-configurator/energy-overview"), False)
    ]
    assert response.released is True
    # The integration intentionally disables content-type checking.
    assert response.json_content_type is None


async def test_get_things_and_items_paths(api: KiwiOsApi, session: FakeSession) -> None:
    """Each convenience method hits its documented endpoint."""
    session.queue_get(FakeResponse(json_data=["thing"]))
    session.queue_get(FakeResponse(json_data=["item"]))

    assert await api.get_things() == ["thing"]
    assert await api.get_items() == ["item"]
    assert [call[0] for call in session.get_calls] == [
        URL("http://box.local/rest/things"),
        URL("http://box.local/rest/items"),
    ]


async def test_gateway_info_of_current_firmware(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """The current firmware answers detection with the info setup needs."""
    session.queue_get(FakeResponse(json_data={"serialNumber": "EHC01"}))

    assert await api.get_edge_gateway_info_if_present() == {"serialNumber": "EHC01"}
    assert [call[0] for call in session.get_calls] == [
        URL("http://box.local/rest/hems-configurator/public/gateway/info")
    ]


async def test_gateway_info_absent_on_older_firmware(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """A 404 means firmware that serves the per-channel API instead."""
    session.queue_get(FakeResponse(404))

    assert await api.get_edge_gateway_info_if_present() is None


async def test_gateway_info_reraises_other_errors(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """Errors other than a 404 are not mistaken for another API."""
    session.queue_get(FakeResponse(500))

    with pytest.raises(aiohttp.ClientResponseError) as exc_info:
        await api.get_edge_gateway_info_if_present()

    assert exc_info.value.status == 500


async def test_edge_paths(api: KiwiOsApi, session: FakeSession) -> None:
    """Every KiwiOS Edge endpoint is requested below its own prefix."""
    for payload in ([], {}, [], [], []):
        session.queue_get(FakeResponse(json_data=payload))

    assert await api.get_edge_things() == []
    assert await api.get_edge_gateway_info() == {}
    assert await api.get_edge_energy_overview() == []
    assert await api.get_edge_power_indicators() == []
    assert await api.get_edge_pv_plants() == []

    assert [call[0] for call in session.get_calls] == [
        URL("http://box.local/rest/hems-configurator/things"),
        URL("http://box.local/rest/hems-configurator/public/gateway/info"),
        URL("http://box.local/rest/hems-configurator/energy-overview"),
        URL("http://box.local/rest/hems-configurator/power-indicator"),
        URL("http://box.local/rest/hems-configurator/pv-plants"),
    ]


async def test_get_retries_after_401(api: KiwiOsApi, session: FakeSession) -> None:
    """A 401 triggers a login and a single retry."""
    api.password = "secret"
    first = FakeResponse(401)
    login = FakeResponse(
        302, headers={"Location": "/"}, cookies={"kiwisessionid": "fresh"}
    )
    retried = FakeResponse(json_data={"retried": True})
    session.queue_get(first)
    session.queue_post(login)
    session.queue_get(retried)

    assert await api.get_items() == {"retried": True}

    assert len(session.get_calls) == 2
    assert len(session.post_calls) == 1
    assert first.released is True
    assert retried.released is True
    assert api.get_kiwisessionid() == "fresh"


async def test_get_retries_after_logon_redirect(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """A redirect to /logon.html triggers a login and a retry."""
    api.password = "secret"
    redirect = FakeResponse(302, headers={"Location": "http://box.local/logon.html"})
    login = FakeResponse(
        302, headers={"Location": "/"}, cookies={"kiwisessionid": "fresh"}
    )
    retried = FakeResponse(json_data={"retried": True})
    session.queue_get(redirect)
    session.queue_post(login)
    session.queue_get(retried)

    assert await api.get_edge_things() == {"retried": True}
    assert redirect.released is True
    assert retried.released is True


async def test_get_retry_yields_other_error_response_after_status_check(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """A non-login redirect is yielded once raise_for_status is a no-op."""
    response = FakeResponse(
        302, headers={"Location": "/elsewhere"}, raise_for_status=False
    )
    session.queue_get(response)

    async with api._get("/rest", retry=True) as yielded:
        assert yielded is response

    assert response.raise_for_status_calls == 1
    assert response.released is True


async def test_get_retry_raises_for_server_error(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """With retries remaining a 500 is reported through raise_for_status."""
    session.queue_get(FakeResponse(500))

    with pytest.raises(aiohttp.ClientResponseError) as exc_info:
        async with api._get("/rest", retry=True):
            pass

    assert exc_info.value.status == 500


async def test_get_without_retry_raises_for_error_status(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """Without retries the response status is raised."""
    response = FakeResponse(500)
    session.queue_get(response)

    with pytest.raises(aiohttp.ClientResponseError):
        async with api._get("/rest", retry=False):
            pass

    assert response.raise_for_status_calls == 1
    assert response.released is True


async def test_get_without_retry_raises_defensive_error(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """The explicit ClientResponseError is raised if raise_for_status did not."""
    session.queue_get(FakeResponse(500, raise_for_status=False))

    with pytest.raises(aiohttp.ClientResponseError, match="GET /rest failed"):
        async with api._get("/rest", retry=False):
            pass


async def test_post_success_yields_response(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """A 2xx POST response is yielded and released."""
    response = FakeResponse(200)
    session.queue_post(response)

    async with api._post("/auth/login", data={"a": 1}, retry=False) as yielded:
        assert yielded is response

    assert session.post_calls == [(URL("http://box.local/auth/login"), {"a": 1}, False)]
    assert response.released is True


async def test_post_skip_response_handling_yields_error(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """Response handling can be skipped, yielding any status."""
    response = FakeResponse(500)
    session.queue_post(response)

    async with api._post(
        "/auth/login", data={}, retry=False, skip_response_handling=True
    ) as yielded:
        assert yielded is response

    assert response.raise_for_status_calls == 0
    assert response.released is True


async def test_post_without_retry_raises_for_error_status(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """Without retries a failing POST raises."""
    response = FakeResponse(400)
    session.queue_post(response)

    with pytest.raises(aiohttp.ClientResponseError):
        async with api._post("/x", data={}, retry=False):
            pass

    assert response.released is True


async def test_post_without_retry_raises_defensive_error(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """The explicit ClientResponseError is raised if raise_for_status did not."""
    session.queue_post(FakeResponse(400, raise_for_status=False))

    with pytest.raises(aiohttp.ClientResponseError, match="POST /x failed"):
        async with api._post("/x", data={}, retry=False):
            pass


async def test_post_retries_after_logon_redirect(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """A POST redirected to /logon.html is retried after logging in."""
    api.password = "secret"
    redirect = FakeResponse(302, headers={"Location": "http://box.local/logon.html"})
    login = FakeResponse(200, cookies={"kiwisessionid": "fresh"})
    retried = FakeResponse(200)
    session.queue_post(redirect)
    session.queue_post(login)
    session.queue_post(retried)

    async with api._post("/x", data={"v": 1}, retry=True) as yielded:
        assert yielded is retried

    # redirect -> login -> retried request
    assert len(session.post_calls) == 3
    assert session.post_calls[0] == (
        URL("http://box.local/x"),
        {"v": 1},
        False,
    )
    assert redirect.released is True
    assert retried.released is True


async def test_post_retry_yields_other_redirect(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """A redirect that is not a login page is yielded after status handling."""
    response = FakeResponse(
        302, headers={"Location": "/elsewhere"}, raise_for_status=False
    )
    session.queue_post(response)

    async with api._post("/x", data={}, retry=True) as yielded:
        assert yielded is response

    assert response.raise_for_status_calls == 1
    assert response.released is True


async def test_post_retry_raises_for_server_error(
    api: KiwiOsApi, session: FakeSession
) -> None:
    """With retries remaining a failing POST is raised."""
    session.queue_post(FakeResponse(500))

    with pytest.raises(aiohttp.ClientResponseError):
        async with api._post("/x", data={}, retry=True):
            pass


async def test_login_without_password_raises(api: KiwiOsApi) -> None:
    """Login is rejected immediately when no password was configured."""
    with pytest.raises(PasswordRequiredException):
        await api.login()


async def test_login_success_calls_callback(session: FakeSession) -> None:
    """A successful login stores the cookie and notifies the callback."""
    changed: list[str] = []
    api = KiwiOsApi(
        url=URL_BASE,
        session=session,
        password="secret",
        kiwisessionid_changed_callback=changed.append,
    )
    response = FakeResponse(
        302, headers={"Location": "/"}, cookies={"kiwisessionid": "tok"}
    )
    session.queue_post(response)

    await api.login()

    assert changed == ["tok"]
    assert api.get_kiwisessionid() == "tok"
    assert response.released is True
    assert session.post_calls[0][1] == {
        "username": "installer",
        "url": "/rest",
        "password": "secret",
        "submit": "Login",
    }


async def test_login_success_without_callback(session: FakeSession) -> None:
    """A successful login works without a change callback."""
    api = KiwiOsApi(url=URL_BASE, session=session, password="secret")
    session.queue_post(FakeResponse(200, cookies={"kiwisessionid": "tok"}))

    await api.login()

    assert api.get_kiwisessionid() == "tok"


async def test_login_invalid_password(session: FakeSession) -> None:
    """A redirect to the error page means the password was rejected."""
    api = KiwiOsApi(url=URL_BASE, session=session, password="wrong")
    response = FakeResponse(
        302, headers={"Location": "http://box.local/logon-error.html"}
    )
    session.queue_post(response)

    with pytest.raises(PasswordInvalidException):
        await api.login()

    assert response.released is True


async def test_login_missing_cookie(session: FakeSession) -> None:
    """A 2xx login without a session cookie is reported as an error."""
    api = KiwiOsApi(url=URL_BASE, session=session, password="secret")
    session.queue_post(FakeResponse(200, headers={"Location": "/"}))

    with pytest.raises(aiohttp.ClientResponseError, match="did not set kiwisessionid"):
        await api.login()


async def test_login_unexpected_response_with_cookie(
    session: FakeSession,
) -> None:
    """An error status that still sets a cookie is an unexpected response."""
    api = KiwiOsApi(url=URL_BASE, session=session, password="secret")
    response = FakeResponse(
        500,
        cookies={"kiwisessionid": "tok"},
        raise_for_status=False,
    )
    session.queue_post(response)

    with pytest.raises(aiohttp.ClientResponseError, match="Unexpected login response"):
        await api.login()


async def test_login_unexpected_response_without_cookie(
    session: FakeSession,
) -> None:
    """An error status without a cookie reports the missing cookie."""
    api = KiwiOsApi(url=URL_BASE, session=session, password="secret")
    session.queue_post(FakeResponse(500, raise_for_status=False))

    with pytest.raises(aiohttp.ClientResponseError, match="did not set kiwisessionid"):
        await api.login()
