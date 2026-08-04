import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from e2e_helpers import (
    UserIdentity,
    goto_loaded,
    login_browser_context,
    response_json,
    signout_api,
)


SECONDARY_USER_AGENT = "NTOJ-E2E-secondary-device"


@pytest.mark.auth
@pytest.mark.realtime
def test_user_can_remotely_log_out_another_browser_session(
    page: Page,
    context: BrowserContext,
    browser: Browser,
    browser_context_args: dict,
    signed_in_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    secondary_args = {**browser_context_args, "user_agent": SECONDARY_USER_AGENT}
    secondary_context = browser.new_context(**secondary_args)
    # Tornado's signed cookie timestamp has one-second granularity. The current
    # implementation otherwise creates the same Redis session key twice.
    page.wait_for_timeout(1100)
    login_browser_context(
        secondary_context,
        ntoj_base_url,
        signed_in_user.email,
        signed_in_user.password,
    )
    secondary_page = secondary_context.new_page()

    try:
        goto_loaded(page, ntoj_base_url, "/info/")
        acct_id = page.evaluate("() => index.acct_id")
        assert isinstance(acct_id, int)

        goto_loaded(secondary_page, ntoj_base_url, "/info/")
        secondary_page.wait_for_function(
            "() => Boolean(index.ws && index.ws.readyState === WebSocket.OPEN)"
        )
        secondary_page.evaluate(
            """
            () => {
                window.__e2eRemoteLogoutClosed = false;
                index.ws.addEventListener(
                    'close',
                    () => { window.__e2eRemoteLogoutClosed = true; },
                    { once: true },
                );
            }
            """
        )

        goto_loaded(page, ntoj_base_url, f"/acctedit/{acct_id}/")
        session_rows = page.locator("#loginlist tbody tr")
        expect(session_rows).to_have_count(2)
        secondary_row = session_rows.filter(has_text=SECONDARY_USER_AGENT)
        expect(secondary_row).to_have_count(1)

        with page.expect_response(
            lambda response: response.url.endswith("/be/acctedit")
            and response.request.method == "POST"
        ) as info:
            secondary_row.locator("button.logout").click()

        payload = response_json(info.value)
        assert payload["status"] == "S", payload
        secondary_page.wait_for_function("() => window.__e2eRemoteLogoutClosed === true")
        expect(page.locator("#indexNotifyDialog .modal-body")).to_have_text("Log out Successfully")
        expect(page.locator("#loginlist tbody tr").filter(has_text=SECONDARY_USER_AGENT)).to_have_count(0)
    finally:
        signout_api(secondary_context.request, ntoj_base_url)
        secondary_context.close()
