import pytest
from playwright.sync_api import Page, expect

from e2e_helpers import app_url, goto_loaded, wait_for_container


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("path", "selector", "text"),
    [
        ("/info/", "#index-cont h1", "公告"),
        ("/proset/", "#prolist", None),
        ("/chal/", "#challist", None),
        ("/contests/", "#index-cont h4", "Active Contests"),
        ("/about/", "#index-cont", "TOJ開発者"),
    ],
)
def test_public_page_loads(page: Page, ntoj_base_url: str, path: str, selector: str, text: str | None) -> None:
    goto_loaded(page, ntoj_base_url, path)
    locator = page.locator(selector)
    if text is None:
        expect(locator).to_be_visible()
    else:
        expect(locator.filter(has_text=text).first).to_be_visible()


@pytest.mark.smoke
def test_guest_navigation_uses_spa_fragment_loading(page: Page, ntoj_base_url: str) -> None:
    goto_loaded(page, ntoj_base_url, "/info/")

    page.locator("#index-navlist li.proset a").click()
    page.wait_for_url(app_url(ntoj_base_url, "/proset/"))
    expect(page.locator("#prolist")).to_be_visible()
    wait_for_container(page)

    page.locator("#index-navlist li.contests a").click()
    page.wait_for_url(app_url(ntoj_base_url, "/contests/"))
    expect(page.locator("#index-cont h4", has_text="Active Contests")).to_be_visible()
    wait_for_container(page)


@pytest.mark.smoke
def test_guest_navigation_exposes_auth_but_not_management(page: Page, ntoj_base_url: str) -> None:
    goto_loaded(page, ntoj_base_url, "/info/")
    expect(page.locator("#index-navlist li.sign")).to_be_visible()
    expect(page.locator("#index-navlist a.account")).to_be_hidden()
    expect(page.locator("#index-navlist li.manage")).to_have_count(0)
