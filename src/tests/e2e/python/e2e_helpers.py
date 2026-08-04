from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from playwright.sync_api import APIRequestContext, BrowserContext, Page, Response, expect


@dataclass(frozen=True)
class UserIdentity:
    name: str
    email: str
    password: str


def unique_identity(prefix: str = "user") -> UserIdentity:
    suffix = uuid.uuid4().hex[:10]
    return UserIdentity(
        name=f"e2e-{prefix}-{suffix}",
        email=f"e2e-{prefix}-{suffix}@example.test",
        password="E2e-password-123",
    )


def unique_text(prefix: str) -> str:
    return f"e2e-{prefix}-{uuid.uuid4().hex[:10]}"


def app_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def response_json(response: Response) -> dict:
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Expected JSON from {response.url}, got: {response.text()[:500]}") from exc


def api_response_json(response) -> dict:
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Expected JSON from {response.url}, got: {response.text()[:500]}") from exc


def assert_api_success(response, *, operation: str) -> dict:
    assert response.ok, f"{operation} returned HTTP {response.status}: {response.text()[:500]}"
    payload = api_response_json(response)
    assert payload.get("status") == "S", f"{operation} failed: {payload}"
    return payload


def signup_via_api(api: APIRequestContext, base_url: str, user: UserIdentity) -> None:
    response = api.post(
        app_url(base_url, "/be/sign"),
        form={"reqtype": "signup", "name": user.name, "mail": user.email, "pw": user.password},
    )
    assert_api_success(response, operation=f"sign up {user.email}")


def login_api(api: APIRequestContext, base_url: str, email: str, password: str) -> None:
    response = api.post(
        app_url(base_url, "/be/sign"),
        form={"reqtype": "signin", "mail": email, "pw": password},
    )
    assert_api_success(response, operation=f"sign in {email}")


def login_browser_context(context: BrowserContext, base_url: str, email: str, password: str) -> None:
    login_api(context.request, base_url, email, password)


def signout_api(api: APIRequestContext, base_url: str) -> None:
    response = api.post(app_url(base_url, "/be/sign"), form={"reqtype": "signout"})
    payload = api_response_json(response)
    assert payload.get("status") in {"S", "Esign"}, f"sign out failed: {payload}"


def goto_loaded(page: Page, base_url: str, path: str) -> Response:
    response = page.goto(app_url(base_url, path), wait_until="domcontentloaded")
    assert response is not None, f"Navigation to {path} did not produce a response"
    assert response.ok, f"Navigation to {path} returned HTTP {response.status}"
    expect(page.locator("#index-cont")).to_be_visible()
    wait_for_container(page)
    return response


def reload_loaded(page: Page) -> Response:
    response = page.reload(wait_until="domcontentloaded")
    assert response is not None, "Reload did not produce a response"
    assert response.ok, f"Reload returned HTTP {response.status}"
    expect(page.locator("#index-cont")).to_be_visible()
    wait_for_container(page)
    return response


def wait_for_container(page: Page) -> None:
    page.wait_for_function("() => Boolean(window.index && window.index.containerLoadDone === true)")


def wait_for_app_path(page: Page, base_url: str, path_pattern: str) -> None:
    base_path = urlsplit(base_url).path.rstrip("/")
    expected = re.compile(rf"{re.escape(base_path)}/{path_pattern.lstrip('/')}($|[?#])")
    page.wait_for_url(expected)

