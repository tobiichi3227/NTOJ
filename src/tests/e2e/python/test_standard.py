import os
import re

import pytest
from playwright.sync_api import BrowserContext, Page, expect

from e2e_helpers import (
    UserIdentity,
    app_url,
    assert_api_success,
    goto_loaded,
    reload_loaded,
    response_json,
    unique_text,
    wait_for_container,
)


@pytest.mark.standard
def test_problem_set_filter_updates_the_spa(page: Page, ntoj_base_url: str) -> None:
    search = unique_text("no-such-problem")
    goto_loaded(page, ntoj_base_url, "/proset/")
    page.locator("#filter #name").fill(search)

    with page.expect_response(lambda response: "/be/proset" in response.url and response.request.method == "GET"):
        page.locator("#filter_submit").click()

    page.wait_for_url(re.compile(rf"[?&]name={re.escape(search)}(?:&|$)"))
    expect(page.locator("#filter #name")).to_have_value(search)
    expect(page.locator("#prolist")).to_be_visible()
    wait_for_container(page)


@pytest.mark.standard
def test_user_can_update_profile_through_ui(
    page: Page,
    signed_in_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    motto = unique_text("motto")
    goto_loaded(page, ntoj_base_url, "/info/")
    acct_id = page.evaluate("() => index.acct_id")
    assert isinstance(acct_id, int)

    goto_loaded(page, ntoj_base_url, f"/acctedit/{acct_id}/")
    page.locator("#profile input.motto").fill(motto)
    with page.expect_response(lambda response: response.url.endswith("/be/acctedit") and response.request.method == "POST") as info:
        page.locator("#profile button.submit").click()

    assert response_json(info.value)["status"] == "S"
    expect(page.locator("#indexNotifyDialog .modal-body")).to_have_text("Update Successfully")

    goto_loaded(page, ntoj_base_url, f"/acct/{acct_id}/")
    expect(page.locator("#profile p", has_text=motto)).to_be_visible()


@pytest.mark.standard
def test_user_can_ask_and_remove_a_question(
    page: Page,
    context: BrowserContext,
    signed_in_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    question = unique_text("question")
    goto_loaded(page, ntoj_base_url, "/question/")
    page.locator("#form textarea.ques").fill(question)

    with page.expect_response(lambda response: response.url.endswith("/be/question") and response.request.method == "POST") as info:
        page.locator("#form button.submit").click()
    assert response_json(info.value)["status"] == "S"

    reload_loaded(page)
    expect(page.get_by_text(question, exact=True)).to_be_visible()

    cleanup = context.request.post(
        app_url(ntoj_base_url, "/be/question"),
        form={"reqtype": "rm_ques", "index": "0"},
    )
    assert_api_success(cleanup, operation="remove E2E question")
    reload_loaded(page)
    expect(page.get_by_text(question, exact=True)).to_have_count(0)


@pytest.mark.standard
@pytest.mark.judge
def test_configured_problem_submission_opens_a_challenge(
    page: Page,
    signed_in_user: UserIdentity,
    ntoj_base_url: str,
) -> None:
    problem_id = os.getenv("NTOJ_E2E_PROBLEM_ID")
    if not problem_id:
        pytest.skip("Set NTOJ_E2E_PROBLEM_ID to an online Batch problem to run judge E2E tests")

    source_code = os.getenv("NTOJ_E2E_SUBMISSION_CODE", "print(0)\n")
    goto_loaded(page, ntoj_base_url, f"/pro/{problem_id}/")
    page.get_by_role("link", name="Submit", exact=True).click()
    page.wait_for_url(app_url(ntoj_base_url, f"/submit/{problem_id}/"))
    expect(page.locator("#submit")).to_be_visible()
    wait_for_container(page)
    page.locator("#codeArea").fill(source_code)

    with page.expect_response(lambda response: response.url.endswith("/be/submit") and response.request.method == "POST") as info:
        page.locator("#submit button.submit").click()

    payload = response_json(info.value)
    assert payload["status"] == "S", payload
    page.wait_for_url(re.compile(r"/chal/\d+/$"))
    wait_for_container(page)
    expect(page.locator("#index-cont table").first).to_be_visible()
