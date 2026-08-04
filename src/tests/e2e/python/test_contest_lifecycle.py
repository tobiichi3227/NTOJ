from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import APIRequestContext, Browser, BrowserContext, Page, expect

from contest_e2e_helpers import create_contest, new_user_context, remove_contest_member
from e2e_helpers import (
    UserIdentity,
    app_url,
    assert_api_success,
    goto_loaded,
    reload_loaded,
    response_json,
    signout_api,
)


@pytest.mark.contest
def test_free_registration_registers_and_unregisters_immediately(
    page: Page,
    context: BrowserContext,
    admin_api: APIRequestContext,
    signed_in_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    now = datetime.now(timezone.utc)
    contest = create_contest(
        admin_api,
        ntoj_base_url,
        prefix="free-registration",
        start=now + timedelta(days=2),
        end=now + timedelta(days=3),
        reg_mode=1,
        reg_end=now + timedelta(days=1),
    )

    goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/reg/")
    expect(page.get_by_text("Status: Not Registered", exact=True)).to_be_visible()
    with page.expect_response(
        lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/reg")
        and response.request.method == "POST"
    ) as info:
        page.locator("button.reg").click()
    assert response_json(info.value)["status"] == "S"

    reload_loaded(page)
    expect(page.get_by_text("Status: Registered", exact=True)).to_be_visible()
    with page.expect_response(
        lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/reg")
        and response.request.method == "POST"
    ) as info:
        page.locator("button.unreg").click()
    assert response_json(info.value)["status"] == "S"

    reload_loaded(page)
    expect(page.get_by_text("Status: Not Registered", exact=True)).to_be_visible()


@pytest.mark.contest
def test_contest_list_classifies_upcoming_active_and_recent(
    page: Page,
    admin_api: APIRequestContext,
    ntoj_base_url: str,
) -> None:
    now = datetime.now(timezone.utc)
    upcoming = create_contest(
        admin_api,
        ntoj_base_url,
        prefix="upcoming",
        start=now + timedelta(days=2),
        end=now + timedelta(days=3),
    )
    active = create_contest(
        admin_api,
        ntoj_base_url,
        prefix="active",
        start=now - timedelta(hours=1),
        end=now + timedelta(hours=2),
    )
    recent = create_contest(
        admin_api,
        ntoj_base_url,
        prefix="recent",
        start=now - timedelta(days=3),
        end=now - timedelta(days=2),
        public_scoreboard=False,
    )

    goto_loaded(page, ntoj_base_url, "/contests/")
    upcoming_table = page.get_by_role("heading", name="Upcoming Contests").locator(
        "xpath=following-sibling::table[1]"
    )
    active_table = page.get_by_role("heading", name="Active Contests").locator(
        "xpath=following-sibling::table[1]"
    )
    recent_table = page.get_by_role("heading", name="Recent Contests").locator(
        "xpath=following-sibling::table[1]"
    )

    expect(upcoming_table.get_by_role("link", name=upcoming.name, exact=True)).to_be_visible()
    expect(active_table.get_by_role("link", name=active.name, exact=True)).to_be_visible()
    recent_row = recent_table.locator("tr").filter(has_text=recent.name)
    expect(recent_row).to_have_count(1)
    expect(recent_row).to_contain_text("No")


@pytest.mark.contest
def test_private_scoreboard_hides_guests_but_shows_the_member(
    page: Page,
    browser: Browser,
    browser_context_args: dict,
    admin_api: APIRequestContext,
    e2e_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    now = datetime.now(timezone.utc)
    contest = create_contest(
        admin_api,
        ntoj_base_url,
        prefix="private-scoreboard",
        start=now - timedelta(hours=1),
        end=now + timedelta(hours=2),
        reg_mode=1,
        reg_end=now + timedelta(hours=1),
        public_scoreboard=False,
    )
    user_context = new_user_context(browser, browser_context_args, e2e_user, ntoj_base_url)
    user_page = user_context.new_page()
    member_added = False

    try:
        goto_loaded(user_page, ntoj_base_url, "/info/")
        acct_id = user_page.evaluate("() => index.acct_id")
        assert isinstance(acct_id, int)
        registered = user_context.request.post(
            app_url(ntoj_base_url, f"/be/contests/{contest.contest_id}/reg"),
            form={"reqtype": "reg"},
        )
        assert_api_success(registered, operation="register private scoreboard member")
        member_added = True

        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/scoreboard")
            and response.request.method == "POST"
        ) as guest_info:
            goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/scoreboard/")
        assert response_json(guest_info.value)["status"] == "Eacces"
        expect(page.locator("#scoreboard")).to_contain_text("No Scoreboard")

        with user_page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/scoreboard")
            and response.request.method == "POST"
        ) as member_info:
            goto_loaded(user_page, ntoj_base_url, f"/contests/{contest.contest_id}/scoreboard/")
        assert response_json(member_info.value)["status"] == "S"
        expect(user_page.locator("#scoreboard").get_by_text(e2e_user.name, exact=True)).to_be_visible()
    finally:
        if member_added:
            remove_contest_member(
                admin_api,
                ntoj_base_url,
                contest.contest_id,
                acct_id,
            )
        signout_api(user_context.request, ntoj_base_url)
        user_context.close()
