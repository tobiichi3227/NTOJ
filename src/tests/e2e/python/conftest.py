from __future__ import annotations

import base64
import os
from collections.abc import Iterator

import pytest
import pytest_html
from playwright.sync_api import APIRequestContext, BrowserContext, Page, Playwright

from e2e_helpers import UserIdentity, login_api, login_browser_context, signout_api, signup_via_api, unique_identity


def pytest_html_report_title(report) -> None:
    report.title = "NTOJ Playwright E2E Dashboard"


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    if not report.failed:
        return

    page = item.funcargs.get("page")
    if page is None or page.is_closed():
        return

    extras = getattr(report, "extras", [])
    try:
        screenshot = base64.b64encode(page.screenshot(full_page=True)).decode("ascii")
        extras.append(pytest_html.extras.png(screenshot, name="Failure screenshot"))
        extras.append(pytest_html.extras.url(page.url, name="Browser URL"))
    except Exception as exc:
        extras.append(pytest_html.extras.text(str(exc), name="Screenshot capture error"))
    report.extras = extras


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("ntoj-e2e")
    group.addoption(
        "--ntoj-base-url",
        action="store",
        default=os.getenv("NTOJ_E2E_BASE_URL", "http://127.0.0.1:5500"),
        help="Base URL of the disposable NTOJ E2E environment",
    )


@pytest.fixture(scope="session")
def ntoj_base_url(pytestconfig: pytest.Config) -> str:
    return str(pytestconfig.getoption("--ntoj-base-url")).rstrip("/")


@pytest.fixture(scope="session")
def browser_context_args(ntoj_base_url: str) -> dict:
    return {
        "base_url": ntoj_base_url,
        "viewport": {"width": 1440, "height": 1000},
        "locale": "zh-TW",
        "timezone_id": "Asia/Taipei",
    }


@pytest.fixture
def identity() -> UserIdentity:
    return unique_identity()


@pytest.fixture
def e2e_user(playwright: Playwright, ntoj_base_url: str) -> Iterator[UserIdentity]:
    user = unique_identity()
    api = playwright.request.new_context()
    signup_via_api(api, ntoj_base_url, user)
    signout_api(api, ntoj_base_url)
    api.dispose()
    yield user


@pytest.fixture
def signed_in_user(
    context: BrowserContext,
    e2e_user: UserIdentity,
    ntoj_base_url: str,
) -> Iterator[UserIdentity]:
    login_browser_context(context, ntoj_base_url, e2e_user.email, e2e_user.password)
    yield e2e_user
    signout_api(context.request, ntoj_base_url)


@pytest.fixture
def admin_credentials() -> tuple[str, str]:
    email = os.getenv("NTOJ_E2E_ADMIN_EMAIL")
    password = os.getenv("NTOJ_E2E_ADMIN_PASSWORD")
    if not email or not password:
        pytest.skip("Set NTOJ_E2E_ADMIN_EMAIL and NTOJ_E2E_ADMIN_PASSWORD to run admin E2E tests")
    return email, password


@pytest.fixture
def signed_in_admin(
    context: BrowserContext,
    admin_credentials: tuple[str, str],
    ntoj_base_url: str,
) -> Iterator[tuple[str, str]]:
    email, password = admin_credentials
    login_browser_context(context, ntoj_base_url, email, password)
    yield admin_credentials
    signout_api(context.request, ntoj_base_url)


@pytest.fixture
def admin_api(
    playwright: Playwright,
    admin_credentials: tuple[str, str],
    ntoj_base_url: str,
) -> Iterator[APIRequestContext]:
    email, password = admin_credentials
    api = playwright.request.new_context()
    login_api(api, ntoj_base_url, email, password)
    yield api
    signout_api(api, ntoj_base_url)
    api.dispose()


@pytest.fixture(autouse=True)
def assert_clean_browser_runtime(
    page: Page,
    ntoj_base_url: str,
    request: pytest.FixtureRequest,
) -> Iterator[None]:
    errors: list[str] = []

    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))

    def on_console(message) -> None:
        if message.type == "error":
            errors.append(f"console: {message.text}")

    def on_request_failed(request) -> None:
        if request.resource_type not in {"document", "script", "xhr", "fetch"}:
            return
        cancellable_async_scripts = (
            "cdn.jsdelivr.net/npm/mathjax@",
            "cdn.jsdelivr.net/npm/marked/marked.min.js",
        )
        if request.failure == "net::ERR_ABORTED" and any(
            script_url in request.url for script_url in cancellable_async_scripts
        ):
            return
        errors.append(f"requestfailed: {request.method} {request.url}: {request.failure}")

    page.on("console", on_console)
    page.on("requestfailed", on_request_failed)
    yield

    known_errors = ["pdfjs-dist@4.7.76/+esm"]
    configured_errors = [
        item.strip() for item in os.getenv("NTOJ_E2E_ALLOWED_BROWSER_ERRORS", "").split("||") if item.strip()
    ]
    marker_errors = [
        str(argument)
        for marker in request.node.iter_markers("allow_browser_error")
        for argument in marker.args
    ]
    allowed = known_errors + configured_errors + marker_errors
    unexpected = [error for error in errors if not any(allowed_text in error for allowed_text in allowed)]
    assert not unexpected, "Unexpected browser errors:\n" + "\n".join(unexpected)
