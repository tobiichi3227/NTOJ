from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from contest_e2e_helpers import create_contest, new_user_context, remove_contest_member
from e2e_helpers import (
    UserIdentity,
    app_url,
    assert_api_success,
    goto_loaded,
    reload_loaded,
    response_json,
    signout_api,
    unique_text,
    wait_for_container,
)


def _running_contest_with_user(
    page: Page,
    context: BrowserContext,
    browser: Browser,
    browser_context_args: dict,
    user: UserIdentity,
    base_url: str,
):
    now = datetime.now(timezone.utc)
    contest = create_contest(
        context.request,
        base_url,
        prefix="running-qa",
        start=now - timedelta(hours=1),
        end=now + timedelta(hours=2),
        reg_mode=1,
        reg_end=now + timedelta(hours=1),
    )
    user_context = new_user_context(browser, browser_context_args, user, base_url)
    user_page = user_context.new_page()
    goto_loaded(user_page, base_url, "/info/")
    acct_id = user_page.evaluate("() => index.acct_id")
    assert isinstance(acct_id, int)
    registered = user_context.request.post(
        app_url(base_url, f"/be/contests/{contest.contest_id}/reg"),
        form={"reqtype": "reg"},
    )
    assert_api_success(registered, operation="register contest Q&A member")
    return contest, user_context, user_page, acct_id


@pytest.mark.admin
@pytest.mark.contest
def test_contest_member_can_ask_and_receive_an_admin_reply(
    page: Page,
    context: BrowserContext,
    browser: Browser,
    browser_context_args: dict,
    signed_in_admin: tuple[str, str],
    e2e_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    contest, user_context, user_page, acct_id = _running_contest_with_user(
        page,
        context,
        browser,
        browser_context_args,
        e2e_user,
        ntoj_base_url,
    )
    subject = unique_text("contest-question")
    content = unique_text("contest-question-content")
    reply = unique_text("contest-answer")

    try:
        goto_loaded(user_page, ntoj_base_url, f"/contests/{contest.contest_id}/qa/")
        user_page.locator("#subject").fill(subject)
        user_page.locator("#content").fill(content)
        with user_page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/qa")
            and response.request.method == "POST"
        ) as info:
            user_page.locator("#ask").click()
        assert response_json(info.value)["status"] == "S"
        reload_loaded(user_page)
        expect(user_page.get_by_text(subject, exact=True)).to_be_visible()

        goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/manage/question/")
        question_row = page.locator("tbody tr").filter(has_text=subject)
        expect(question_row).to_have_count(1)
        reply_cell = question_row.locator("td.reply")
        reply_cell.locator(".answer-type").select_option("Other")
        reply_cell.locator("textarea").fill(reply)
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/question")
            and response.request.method == "POST"
        ) as info:
            reply_cell.locator("button.reply").click()
        assert info.value.ok
        page.wait_for_load_state("domcontentloaded")

        reload_loaded(user_page)
        expect(user_page.get_by_text(reply, exact=True)).to_be_visible()
    finally:
        remove_contest_member(context.request, ntoj_base_url, contest.contest_id, acct_id)
        signout_api(user_context.request, ntoj_base_url)
        user_context.close()


@pytest.mark.admin
@pytest.mark.contest
@pytest.mark.realtime
def test_contest_announcement_updates_the_badge_and_can_popup_over_websocket(
    page: Page,
    context: BrowserContext,
    browser: Browser,
    browser_context_args: dict,
    signed_in_admin: tuple[str, str],
    e2e_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    contest, user_context, user_page, acct_id = _running_contest_with_user(
        page,
        context,
        browser,
        browser_context_args,
        e2e_user,
        ntoj_base_url,
    )
    subject = unique_text("contest-announcement")
    content = unique_text("contest-announcement-content")

    try:
        goto_loaded(user_page, ntoj_base_url, f"/contests/{contest.contest_id}/info/")
        user_page.wait_for_function("() => Boolean(index.ws && index.ws.readyState === WebSocket.OPEN)")
        user_page.wait_for_timeout(200)

        goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/manage/announce/")
        page.locator("#form #subject").fill(subject)
        page.locator("#form #content").fill(content)
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/announce")
            and response.request.method == "POST"
        ) as info:
            page.locator("#add").click()
        assert response_json(info.value)["status"] == "S"
        wait_for_container(page)

        expect(user_page.locator("#notifyRedDot")).to_be_visible()
        expect(user_page.locator("#notifyRedDot")).to_have_text("1")

        announce_cell = page.locator("td.announce").filter(has_text=subject)
        expect(announce_cell).to_have_count(1)
        page.locator("#indexNotifyDialog").get_by_role("button", name="Close").last.click()
        expect(page.locator("#indexNotifyDialog")).to_be_hidden()
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/announce")
            and response.request.method == "POST"
        ) as info:
            announce_cell.locator("button.popup").click()
        assert info.value.ok

        expect(user_page.locator("#indexNotifyDialog .modal-title")).to_have_text(subject)
        expect(user_page.locator("#indexNotifyDialog .modal-body")).to_have_text(content)

        goto_loaded(user_page, ntoj_base_url, f"/contests/{contest.contest_id}/qa/")
        expect(user_page.get_by_text(subject, exact=True)).to_be_visible()
        expect(user_page.get_by_text(content, exact=True)).to_be_visible()
    finally:
        remove_contest_member(context.request, ntoj_base_url, contest.contest_id, acct_id)
        signout_api(user_context.request, ntoj_base_url)
        user_context.close()
