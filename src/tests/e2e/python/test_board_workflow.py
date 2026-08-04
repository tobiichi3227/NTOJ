from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from e2e_helpers import (
    app_url,
    assert_api_success,
    goto_loaded,
    response_json,
    unique_text,
)


def _iso8601(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@pytest.mark.admin
@pytest.mark.standard
def test_admin_can_publish_then_hide_a_board(
    page: Page,
    context: BrowserContext,
    browser: Browser,
    browser_context_args: dict,
    signed_in_admin: tuple[str, str],
    ntoj_base_url: str,
) -> None:
    board_name = unique_text("board")
    hidden_name = f"{board_name}-hidden"
    now = datetime.now(timezone.utc)

    created = context.request.post(
        app_url(ntoj_base_url, "/be/manage/board/add"),
        form={
            "reqtype": "add",
            "name": board_name,
            "status": "0",
            "start": _iso8601(now - timedelta(hours=1)),
            "end": _iso8601(now + timedelta(days=1)),
            "pro_list": "1",
            "acct_list": "1",
        },
    )
    created_payload = assert_api_success(created, operation="create E2E board")
    board_id = int(created_payload["data"])

    guest_context = browser.new_context(**browser_context_args)
    guest_page = guest_context.new_page()
    try:
        goto_loaded(guest_page, ntoj_base_url, "/board/")
        expect(guest_page.get_by_role("link", name=board_name, exact=True)).to_be_visible()

        goto_loaded(guest_page, ntoj_base_url, f"/board/{board_id}/")
        expect(guest_page.locator("#board1")).to_be_visible()
        expect(guest_page.get_by_role("combobox").locator("option:checked")).to_have_text(board_name)

        goto_loaded(page, ntoj_base_url, f"/manage/board/update/?boardid={board_id}")
        page.locator("#name").fill(hidden_name)
        page.locator("#status").select_option(label="Hidden")

        with page.expect_response(
            lambda response: response.url.endswith("/be/manage/board/update")
            and response.request.method == "POST"
        ) as info:
            page.locator("#update").click()

        payload = response_json(info.value)
        assert payload["status"] == "S", payload
        expect(page.locator("#indexNotifyDialog .modal-body")).to_have_text("Update Successfully")

        goto_loaded(guest_page, ntoj_base_url, "/board/")
        expect(guest_page.get_by_role("link", name=hidden_name, exact=True)).to_have_count(0)

        goto_loaded(guest_page, ntoj_base_url, f"/board/{board_id}/")
        expect(guest_page.locator("#board1")).to_have_count(0)
        expect(guest_page.locator("#index-cont")).to_contain_text("Permission denied")
    finally:
        removed = context.request.post(
            app_url(ntoj_base_url, "/be/manage/board/update"),
            form={"reqtype": "remove", "board_id": str(board_id)},
        )
        assert_api_success(removed, operation="remove E2E board")
        guest_context.close()
