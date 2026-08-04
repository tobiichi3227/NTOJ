import re

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from e2e_helpers import (
    UserIdentity,
    app_url,
    assert_api_success,
    goto_loaded,
    login_browser_context,
    response_json,
    signout_api,
    unique_text,
    wait_for_container,
)


@pytest.mark.admin
@pytest.mark.standard
def test_admin_can_reply_to_a_user_question(
    page: Page,
    browser: Browser,
    browser_context_args: dict,
    signed_in_admin: tuple[str, str],
    e2e_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    question = unique_text("question-for-admin")
    reply = unique_text("admin-reply")
    user_context = browser.new_context(**browser_context_args)
    login_browser_context(user_context, ntoj_base_url, e2e_user.email, e2e_user.password)
    user_page = user_context.new_page()
    question_added = False

    try:
        asked = user_context.request.post(
            app_url(ntoj_base_url, "/be/question"),
            form={"reqtype": "ask", "qtext": question},
        )
        assert_api_success(asked, operation="ask E2E question")
        question_added = True

        goto_loaded(page, ntoj_base_url, "/manage/question/")
        row = page.locator("tbody tr").filter(has_text=e2e_user.name)
        expect(row).to_have_count(1)
        row.locator("a[href*='/manage/question/reply/']").click()
        page.wait_for_url(re.compile(r"/manage/question/reply/\?qacct=\d+$"))
        wait_for_container(page)

        expect(page.get_by_text(question, exact=True)).to_be_visible()
        page.locator('textarea[id="0"]').fill(reply)
        with page.expect_response(
            lambda response: response.url.endswith("/be/manage/question/reply")
            and response.request.method == "POST"
        ) as info:
            page.locator('input[value="Reply"]').click()

        payload = response_json(info.value)
        assert payload["status"] == "S", payload
        expect(page.locator("#indexNotifyDialog .modal-body")).to_have_text("Reply Successfully")

        goto_loaded(user_page, ntoj_base_url, "/question/")
        expect(user_page.get_by_text(question, exact=True)).to_be_visible()
        expect(user_page.get_by_text("Reply:", exact=True)).to_be_visible()
        expect(user_page.locator("#form h5").filter(has_text=reply)).to_be_visible()
    finally:
        if question_added:
            removed = user_context.request.post(
                app_url(ntoj_base_url, "/be/question"),
                form={"reqtype": "rm_ques", "index": "0"},
            )
            assert_api_success(removed, operation="remove replied E2E question")
        signout_api(user_context.request, ntoj_base_url)
        user_context.close()
