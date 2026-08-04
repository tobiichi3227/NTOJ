from datetime import datetime, timedelta, timezone
import time

import pytest
from playwright.sync_api import APIRequestContext, Page, expect

from contest_e2e_helpers import create_contest
from e2e_helpers import app_url, assert_api_success, goto_loaded, unique_text


@pytest.mark.admin
@pytest.mark.contest
@pytest.mark.allow_browser_error("marked is not defined")
@pytest.mark.xfail(
    strict=True,
    reason="marked is loaded asynchronously, so Contest info init can run before marked exists",
)
def test_guest_can_render_saved_contest_description_on_direct_load(
    page: Page,
    admin_api: APIRequestContext,
    ntoj_base_url: str,
) -> None:
    now = datetime.now(timezone.utc)
    contest = create_contest(
        admin_api,
        ntoj_base_url,
        prefix="guest-description",
        start=now + timedelta(days=2),
        end=now + timedelta(days=3),
    )
    heading = unique_text("guest-contest-heading")
    response = admin_api.post(
        app_url(ntoj_base_url, f"/be/contests/{contest.contest_id}/manage/desc"),
        form={
            "reqtype": "update",
            "desc_type": "before",
            "desc": f"# {heading}",
        },
    )
    assert_api_success(response, operation="save Contest description")

    def delay_marked(route) -> None:
        time.sleep(1)
        route.continue_()

    page.route("https://cdn.jsdelivr.net/npm/marked/marked.min.js", delay_marked)
    goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/info/")
    expect(page.locator("#desc h1")).to_have_text(heading)
