import re

import pytest
from playwright.sync_api import APIRequestContext, BrowserContext, Page, expect

from e2e_helpers import (
    app_url,
    assert_api_success,
    goto_loaded,
    response_json,
    unique_text,
    wait_for_container,
)


def remove_bulletin(api, base_url: str, bulletin_id: int) -> None:
    response = api.post(
        app_url(base_url, "/be/manage/bulletin/update"),
        form={"reqtype": "remove", "bulletin_id": str(bulletin_id)},
    )
    assert_api_success(response, operation=f"remove bulletin {bulletin_id}")


@pytest.mark.admin
def test_admin_can_create_and_preview_a_bulletin(
    page: Page,
    context: BrowserContext,
    signed_in_admin: tuple[str, str],
    ntoj_base_url: str,
) -> None:
    title = unique_text("bulletin")
    content = f"# {title}\n\nCreated by Playwright."
    bulletin_id = None

    try:
        goto_loaded(page, ntoj_base_url, "/manage/bulletin/add/")
        page.wait_for_function("() => Boolean(window.marked)")
        page.locator("#title").fill(title)
        page.locator("#color").fill("white")
        page.locator("#content").fill(content)
        page.locator("#preview").click()
        expect(page.locator("#descPreviewDialog .modal-body h1")).to_have_text(title)
        page.locator("#descPreviewDialog button", has_text="Close").click()

        with page.expect_response(
            lambda response: response.url.endswith("/be/manage/bulletin/add") and response.request.method == "POST"
        ) as info:
            page.locator("#add").click()

        payload = response_json(info.value)
        assert payload["status"] == "S", payload
        bulletin_id = int(payload["data"])
        page.wait_for_url(re.compile(rf"/manage/bulletin/update/\?bulletin_id={bulletin_id}$"))
        wait_for_container(page)
        expect(page.locator("#title")).to_have_value(title)
        expect(page.locator("#content")).to_have_value(content)
    finally:
        if bulletin_id is not None:
            remove_bulletin(context.request, ntoj_base_url, bulletin_id)


@pytest.mark.admin
@pytest.mark.realtime
def test_browser_receives_new_bulletin_websocket_notification(
    page: Page,
    admin_api: APIRequestContext,
    ntoj_base_url: str,
) -> None:
    title = unique_text("bulletin-ws")
    bulletin_id = None
    goto_loaded(page, ntoj_base_url, "/info/")
    page.wait_for_function("() => index.ws && index.ws.readyState === WebSocket.OPEN")
    page.evaluate(
        """
        () => {
            window.__e2eBulletins = [];
            index.register_ws_callback('bulletinsub', data => window.__e2eBulletins.push(Number(data)));
        }
        """
    )

    try:
        created = admin_api.post(
            app_url(ntoj_base_url, "/be/manage/bulletin/add"),
            form={"reqtype": "add", "title": title, "content": title, "color": "white", "pinned": "false"},
        )
        payload = assert_api_success(created, operation="create bulletin for WebSocket test")
        bulletin_id = int(payload["data"])
        page.wait_for_function("() => window.__e2eBulletins.length > 0")

        page.evaluate("() => index.reload()")
        expect(page.get_by_role("link", name=title, exact=True)).to_be_visible()
        wait_for_container(page)
    finally:
        if bulletin_id is not None:
            remove_bulletin(admin_api, ntoj_base_url, bulletin_id)
