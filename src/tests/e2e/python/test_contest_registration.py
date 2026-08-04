from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from e2e_helpers import (
    UserIdentity,
    app_url,
    assert_api_success,
    goto_loaded,
    login_browser_context,
    reload_loaded,
    response_json,
    signout_api,
    unique_text,
)


def _iso8601(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _create_approval_contest(
    context: BrowserContext,
    ntoj_base_url: str,
) -> tuple[int, str]:
    contest_name = unique_text("approval-contest")
    created = context.request.post(
        app_url(ntoj_base_url, "/be/contests/manage/add"),
        form={"reqtype": "add", "name": contest_name},
    )
    created_payload = assert_api_success(created, operation="create approval contest")
    contest_id = int(created_payload["data"])

    now = datetime.now(timezone.utc)
    body = urlencode(
        [
            ("reqtype", "update"),
            ("name", contest_name),
            ("contest_mode", "0"),
            ("contest_start", _iso8601(now + timedelta(days=2))),
            ("contest_end", _iso8601(now + timedelta(days=3))),
            ("reg_mode", "2"),
            ("reg_end", _iso8601(now + timedelta(days=1))),
            ("allow_compilers[]", "3"),
            ("is_public_scoreboard", "true"),
            ("allow_view_other_page", "false"),
            ("hide_admin", "true"),
            ("submission_cd_time", "30"),
            ("freeze_scoreboard_period", "0"),
            ("penalty_value", "20"),
            ("enable_system_test", "false"),
        ]
    )
    configured = context.request.post(
        app_url(ntoj_base_url, f"/be/contests/{contest_id}/manage/general"),
        data=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert_api_success(configured, operation="configure approval contest")
    return contest_id, contest_name


def _new_user_context(
    browser: Browser,
    browser_context_args: dict,
    user: UserIdentity,
    ntoj_base_url: str,
) -> BrowserContext:
    context = browser.new_context(**browser_context_args)
    login_browser_context(context, ntoj_base_url, user.email, user.password)
    return context


def _register_for_contest(page: Page, ntoj_base_url: str, contest_id: int) -> None:
    goto_loaded(page, ntoj_base_url, f"/contests/{contest_id}/reg/")
    expect(page.get_by_text("Status: Not Registered", exact=True)).to_be_visible()
    with page.expect_response(
        lambda response: response.url.endswith(f"/be/contests/{contest_id}/reg")
        and response.request.method == "POST"
    ) as info:
        page.locator("button.reg").click()
    payload = response_json(info.value)
    assert payload["status"] == "S", payload
    reload_loaded(page)
    expect(page.get_by_text("Status: Waiting Approval", exact=True)).to_be_visible()


@pytest.mark.admin
@pytest.mark.contest
def test_user_can_cancel_a_pending_contest_registration(
    page: Page,
    context: BrowserContext,
    browser: Browser,
    browser_context_args: dict,
    signed_in_admin: tuple[str, str],
    e2e_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    contest_id, contest_name = _create_approval_contest(context, ntoj_base_url)
    goto_loaded(page, ntoj_base_url, f"/contests/{contest_id}/manage/general/")
    expect(page.locator("#contestName")).to_have_value(contest_name)
    expect(page.locator("#regMode")).to_have_value("2")

    user_context = _new_user_context(browser, browser_context_args, e2e_user, ntoj_base_url)
    user_page = user_context.new_page()
    try:
        _register_for_contest(user_page, ntoj_base_url, contest_id)
        with user_page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest_id}/reg")
            and response.request.method == "POST"
        ) as info:
            user_page.locator("button.cancel-register").click()
        payload = response_json(info.value)
        assert payload["status"] == "S", payload
        reload_loaded(user_page)
        expect(user_page.get_by_text("Status: Not Registered", exact=True)).to_be_visible()
    finally:
        signout_api(user_context.request, ntoj_base_url)
        user_context.close()


@pytest.mark.admin
@pytest.mark.contest
def test_admin_can_reject_then_reapprove_a_registration(
    page: Page,
    context: BrowserContext,
    browser: Browser,
    browser_context_args: dict,
    signed_in_admin: tuple[str, str],
    e2e_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    contest_id, _ = _create_approval_contest(context, ntoj_base_url)
    user_context = _new_user_context(browser, browser_context_args, e2e_user, ntoj_base_url)
    user_page = user_context.new_page()
    registered = False

    try:
        _register_for_contest(user_page, ntoj_base_url, contest_id)

        goto_loaded(page, ntoj_base_url, f"/contests/{contest_id}/manage/reg/")
        request_row = page.locator("tbody tr").filter(has_text=e2e_user.name)
        expect(request_row).to_have_count(1)
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest_id}/manage/reg")
            and response.request.method == "POST"
        ) as info:
            request_row.locator("button.reject").click()
        payload = response_json(info.value)
        assert payload["status"] == "S", payload

        reload_loaded(user_page)
        expect(user_page.get_by_text("Status: Rejected", exact=True)).to_be_visible()

        reload_loaded(page)
        rejected_row = page.locator("tbody tr").filter(has_text=e2e_user.name)
        expect(rejected_row).to_have_count(1)
        page.once("dialog", lambda dialog: dialog.accept())
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest_id}/manage/reg")
            and response.request.method == "POST"
        ) as info:
            rejected_row.locator("button.re-approve").click()
        payload = response_json(info.value)
        assert payload["status"] == "S", payload
        registered = True

        reload_loaded(user_page)
        expect(user_page.get_by_text("Status: Registered", exact=True)).to_be_visible()
    finally:
        if registered:
            unregistered = user_context.request.post(
                app_url(ntoj_base_url, f"/be/contests/{contest_id}/reg"),
                form={"reqtype": "unreg"},
            )
            assert_api_success(unregistered, operation="unregister E2E contest user")
        signout_api(user_context.request, ntoj_base_url)
        user_context.close()
