from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from contest_e2e_helpers import create_contest, new_user_context, remove_contest_member
from e2e_helpers import (
    UserIdentity,
    app_url,
    assert_api_success,
    goto_loaded,
    response_json,
    signout_api,
    unique_text,
    wait_for_container,
)


def _wait_for_delayed_reload(page: Page) -> None:
    page.wait_for_timeout(1150)
    wait_for_container(page)
    dialog = page.locator("#indexNotifyDialog")
    if dialog.count():
        dialog.locator(".btn-close").click()
        expect(dialog).to_have_count(0)


@pytest.mark.admin
@pytest.mark.contest
def test_admin_description_preview_is_sanitized_and_persisted(
    page: Page,
    context: BrowserContext,
    signed_in_admin: tuple[str, str],
    ntoj_base_url: str,
) -> None:
    now = datetime.now(timezone.utc)
    contest = create_contest(
        context.request,
        ntoj_base_url,
        prefix="markdown-description",
        start=now + timedelta(days=2),
        end=now + timedelta(days=3),
    )
    heading = unique_text("contest-heading")
    body = unique_text("contest-body")
    markdown = (
        f"# {heading}\n\n**{body}**\n\n"
        '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" '
        'onerror="window.__e2eUnsafe = true">'
    )

    goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/manage/desc/")
    page.locator("#contestDesc").fill(markdown)
    page.get_by_role("button", name="Preview", exact=True).click()
    preview = page.locator("#descPreviewDialog")
    expect(preview).to_be_visible()
    expect(preview.locator("h1")).to_have_text(heading)
    expect(preview.locator("strong")).to_have_text(body)
    expect(preview.locator("script")).to_have_count(0)
    assert preview.locator("img").get_attribute("onerror") is None
    preview.get_by_role("button", name="Close", exact=True).click()
    expect(preview).to_be_hidden()

    page.locator("#contestDesc").fill(f"# {heading}\n\n**{body}**")
    with page.expect_response(
        lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/desc")
        and response.request.method == "POST"
    ) as info:
        page.get_by_role("button", name="Update", exact=True).click()
    assert response_json(info.value)["status"] == "S"
    expect(page.locator("#indexNotifyDialog .modal-body")).to_have_text("Update Successfully")

    goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/manage/desc/")
    expect(page.locator("#descType")).to_have_value("before")
    expect(page.locator("#contestDesc")).to_have_value(f"# {heading}\n\n**{body}**")

@pytest.mark.admin
@pytest.mark.contest
def test_admin_can_grant_and_revoke_contest_member_and_admin_roles(
    page: Page,
    context: BrowserContext,
    browser: Browser,
    browser_context_args: dict,
    signed_in_admin: tuple[str, str],
    e2e_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    now = datetime.now(timezone.utc)
    contest = create_contest(
        context.request,
        ntoj_base_url,
        prefix="role-management",
        start=now + timedelta(days=2),
        end=now + timedelta(days=3),
    )
    user_context = new_user_context(browser, browser_context_args, e2e_user, ntoj_base_url)
    user_page = user_context.new_page()
    current_role: str | None = None

    try:
        goto_loaded(user_page, ntoj_base_url, "/info/")
        acct_id = user_page.evaluate("() => index.acct_id")
        assert isinstance(acct_id, int)

        goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/manage/acct/")
        page.locator("#acctIdNormal").fill(str(acct_id))
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/acct")
            and response.request.method == "POST"
        ) as info:
            page.locator("#addAcctNormal").click()
        assert response_json(info.value)["status"] == "S"
        current_role = "normal"
        _wait_for_delayed_reload(page)
        normal_row = page.locator("tbody tr").filter(has_text=e2e_user.name)
        expect(normal_row).to_have_count(1)

        goto_loaded(user_page, ntoj_base_url, f"/contests/{contest.contest_id}/info/")
        expect(user_page.get_by_role("heading", name="Invited", exact=True).last).to_be_visible()
        goto_loaded(user_page, ntoj_base_url, f"/contests/{contest.contest_id}/manage/general/")
        expect(user_page.locator("#index-cont")).to_contain_text("Permission denied")

        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/acct")
            and response.request.method == "POST"
        ) as info:
            normal_row.locator("button.remove.normal").click()
        assert response_json(info.value)["status"] == "S"
        current_role = None
        _wait_for_delayed_reload(page)

        page.locator("#acctIdAdmin").fill(str(acct_id))
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/acct")
            and response.request.method == "POST"
        ) as info:
            page.locator("#addAcctAdmin").click()
        assert response_json(info.value)["status"] == "S"
        current_role = "admin"
        _wait_for_delayed_reload(page)

        goto_loaded(user_page, ntoj_base_url, f"/contests/{contest.contest_id}/manage/general/")
        expect(user_page.locator("#contestName")).to_have_value(contest.name)

        admin_row = page.locator("tbody tr").filter(has_text=e2e_user.name)
        expect(admin_row).to_have_count(1)
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/acct")
            and response.request.method == "POST"
        ) as info:
            admin_row.locator("button.remove.admin").click()
        assert response_json(info.value)["status"] == "S"
        current_role = None

        goto_loaded(user_page, ntoj_base_url, f"/contests/{contest.contest_id}/info/")
        expect(user_page.get_by_text("Not Invited", exact=True)).to_be_visible()
    finally:
        if current_role is not None:
            remove_contest_member(
                context.request,
                ntoj_base_url,
                contest.contest_id,
                acct_id,
                member_type=current_role,
            )
        signout_api(user_context.request, ntoj_base_url)
        user_context.close()


@pytest.mark.admin
@pytest.mark.contest
def test_admin_can_add_configure_and_remove_a_contest_problem(
    page: Page,
    context: BrowserContext,
    signed_in_admin: tuple[str, str],
    ntoj_base_url: str,
) -> None:
    now = datetime.now(timezone.utc)
    contest = create_contest(
        context.request,
        ntoj_base_url,
        prefix="problem-management",
        start=now + timedelta(days=2),
        end=now + timedelta(days=3),
    )
    problem_added = False
    problem_name = unique_text("contest-problem")
    created_problem = context.request.post(
        app_url(ntoj_base_url, "/be/manage/pro/add"),
        form={
            "reqtype": "addpro",
            "name": problem_name,
            "status": "0",
            "mode": "manual",
            "pack_token": "",
        },
    )
    problem_id = int(assert_api_success(created_problem, operation="create online E2E problem")["data"])

    try:
        goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/manage/pro/")
        page.locator("#proId").fill(str(problem_id))
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/pro")
            and response.request.method == "POST"
        ) as info:
            page.locator("#addPro").click()
        assert response_json(info.value)["status"] == "S"
        problem_added = True
        _wait_for_delayed_reload(page)

        row = page.locator("tbody tr").filter(has=page.locator(f'a[href*="/pro/{problem_id}/"]'))
        expect(row).to_have_count(1)
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/pro")
            and response.request.method == "POST"
        ) as info:
            row.locator(".score-type-select").select_option(label="IOI2013")
        assert response_json(info.value)["status"] == "S"
        _wait_for_delayed_reload(page)

        row = page.locator("tbody tr").filter(has=page.locator(f'a[href*="/pro/{problem_id}/"]'))
        expect(row.locator(".score-type-select")).to_have_value("0")
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/pro")
            and response.request.method == "POST"
        ) as info:
            row.locator(".challenge-style-select").select_option(label="Total Only")
        assert response_json(info.value)["status"] == "S"
        _wait_for_delayed_reload(page)

        goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/proset/")
        proset_row = page.locator("#prolist tbody tr").filter(has=page.locator(f'a[href*="/pro/{problem_id}/"]'))
        expect(proset_row).to_have_count(1)

        goto_loaded(page, ntoj_base_url, f"/contests/{contest.contest_id}/manage/pro/")
        row = page.locator("tbody tr").filter(has=page.locator(f'a[href*="/pro/{problem_id}/"]'))
        expect(row.locator(".challenge-style-select")).to_have_value("4")
        with page.expect_response(
            lambda response: response.url.endswith(f"/be/contests/{contest.contest_id}/manage/pro")
            and response.request.method == "POST"
        ) as info:
            row.locator("button.remove").click()
        assert response_json(info.value)["status"] == "S"
        problem_added = False
        _wait_for_delayed_reload(page)
        expect(page.locator("tbody tr").filter(has=page.locator(f'a[href*="/pro/{problem_id}/"]'))).to_have_count(0)
    finally:
        if problem_added:
            removed = context.request.post(
                app_url(ntoj_base_url, f"/be/contests/{contest.contest_id}/manage/pro"),
                form={"reqtype": "remove", "pro_id": str(problem_id)},
            )
            assert_api_success(removed, operation="remove E2E contest problem")
