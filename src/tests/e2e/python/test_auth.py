import pytest
from playwright.sync_api import BrowserContext, Page, expect

from e2e_helpers import (
    UserIdentity,
    app_url,
    goto_loaded,
    response_json,
    wait_for_container,
)


@pytest.mark.auth
def test_failed_login_stays_on_sign_page(page: Page, ntoj_base_url: str) -> None:
    goto_loaded(page, ntoj_base_url, "/sign/")
    page.locator("#signin input.mail").fill("missing-e2e-user@example.test")
    page.locator("#signin input.pw").fill("wrong-password")

    with page.expect_response(lambda response: response.url.endswith("/be/sign") and response.request.method == "POST") as info:
        page.locator("#signin button.submit").click()

    payload = response_json(info.value)
    assert payload["status"] == "Esign"
    expect(page.locator("#signin div.print")).to_have_text("Login failed")
    expect(page).to_have_url(app_url(ntoj_base_url, "/sign/"))


@pytest.mark.auth
def test_user_can_register_and_sign_out_through_ui(page: Page, ntoj_base_url: str, identity: UserIdentity) -> None:
    goto_loaded(page, ntoj_base_url, "/sign/")
    page.locator("#signin button.signup").click()
    expect(page.locator("#warning")).to_be_visible()
    page.locator("#warning button.confirm").click()
    expect(page.locator("#signup")).to_be_visible()

    page.locator("#signup input.name").fill(identity.name)
    page.locator("#signup input.mail").fill(identity.email)
    page.locator("#signup input.pw").fill(identity.password)
    page.locator("#signup input.repeat").fill(identity.password)

    with page.expect_response(lambda response: response.url.endswith("/be/sign") and response.request.method == "POST") as info:
        page.locator("#signup button.submit").click()

    assert info.value.ok
    page.wait_for_url(app_url(ntoj_base_url, "/info/"))
    wait_for_container(page)
    expect(page.locator("#index-navlist a.account")).to_be_visible()
    expect(page.locator("#index-navlist a.account")).to_have_text(identity.name)

    with page.expect_response(lambda response: response.url.endswith("/be/sign") and response.request.method == "POST"):
        page.locator("#index-navlist li.leave a").click()

    page.wait_for_url(app_url(ntoj_base_url, "/sign/"))
    wait_for_container(page)
    expect(page.locator("#signin")).to_be_visible()


@pytest.mark.auth
def test_existing_user_can_login_through_ui(page: Page, ntoj_base_url: str, e2e_user: UserIdentity) -> None:
    goto_loaded(page, ntoj_base_url, "/sign/")
    page.locator("#signin input.mail").fill(e2e_user.email)
    page.locator("#signin input.pw").fill(e2e_user.password)

    with page.expect_response(lambda response: response.url.endswith("/be/sign") and response.request.method == "POST") as info:
        page.locator("#signin button.submit").click()

    assert info.value.ok
    page.wait_for_url(app_url(ntoj_base_url, "/info/"))
    wait_for_container(page)
    expect(page.locator("#index-navlist a.account")).to_have_text(e2e_user.name)


@pytest.mark.auth
@pytest.mark.realtime
def test_signout_closes_the_authenticated_browser_websocket(
    page: Page,
    context: BrowserContext,
    signed_in_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    goto_loaded(page, ntoj_base_url, "/info/")
    page.wait_for_function("() => index.ws && index.ws.readyState === WebSocket.OPEN")
    page.evaluate(
        """
        () => {
            window.__e2eWsClosed = false;
            index.ws.addEventListener('close', () => { window.__e2eWsClosed = true; }, { once: true });
        }
        """
    )

    response = context.request.post(app_url(ntoj_base_url, "/be/sign"), form={"reqtype": "signout"})
    assert response_json(response)["status"] == "S"
    page.wait_for_function("() => window.__e2eWsClosed === true")
