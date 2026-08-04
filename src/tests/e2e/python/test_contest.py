import re

import pytest
from playwright.sync_api import Page, expect

from e2e_helpers import goto_loaded, response_json, unique_text, wait_for_container


@pytest.mark.admin
@pytest.mark.contest
def test_admin_can_create_a_contest_through_ui(
    page: Page,
    signed_in_admin: tuple[str, str],
    ntoj_base_url: str,
) -> None:
    contest_name = unique_text("contest")
    goto_loaded(page, ntoj_base_url, "/contests/manage/add/")
    page.locator("#name").fill(contest_name)

    with page.expect_response(
        lambda response: response.url.endswith("/be/contests/manage/add") and response.request.method == "POST"
    ) as info:
        page.get_by_role("button", name="Add", exact=True).click()

    payload = response_json(info.value)
    assert payload["status"] == "S", payload
    contest_id = int(payload["data"])
    page.wait_for_url(re.compile(rf"/contests/{contest_id}/manage/general/$"))
    wait_for_container(page)
    expect(page.locator("#contestName")).to_have_value(contest_name)
    expect(page.locator("a.nav-link.active", has_text="General")).to_be_visible()
