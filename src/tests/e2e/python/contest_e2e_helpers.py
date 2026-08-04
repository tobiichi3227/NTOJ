from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from playwright.sync_api import APIRequestContext, Browser, BrowserContext

from e2e_helpers import (
    UserIdentity,
    app_url,
    assert_api_success,
    login_browser_context,
    unique_text,
)


@dataclass(frozen=True)
class ContestIdentity:
    contest_id: int
    name: str


def iso8601(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def create_contest(
    api: APIRequestContext,
    base_url: str,
    *,
    prefix: str,
    start: datetime,
    end: datetime,
    reg_mode: int = 0,
    reg_end: datetime | None = None,
    contest_mode: int = 0,
    public_scoreboard: bool = True,
    hide_admin: bool = True,
    enable_system_test: bool = False,
) -> ContestIdentity:
    assert start < end
    name = unique_text(prefix)
    created = api.post(
        app_url(base_url, "/be/contests/manage/add"),
        form={"reqtype": "add", "name": name},
    )
    payload = assert_api_success(created, operation=f"create contest {name}")
    contest = ContestIdentity(contest_id=int(payload["data"]), name=name)
    configure_contest(
        api,
        base_url,
        contest,
        start=start,
        end=end,
        reg_mode=reg_mode,
        reg_end=reg_end or end,
        contest_mode=contest_mode,
        public_scoreboard=public_scoreboard,
        hide_admin=hide_admin,
        enable_system_test=enable_system_test,
    )
    return contest


def configure_contest(
    api: APIRequestContext,
    base_url: str,
    contest: ContestIdentity,
    *,
    start: datetime,
    end: datetime,
    reg_mode: int,
    reg_end: datetime,
    contest_mode: int = 0,
    public_scoreboard: bool = True,
    hide_admin: bool = True,
    enable_system_test: bool = False,
) -> None:
    body = urlencode(
        [
            ("reqtype", "update"),
            ("name", contest.name),
            ("contest_mode", str(contest_mode)),
            ("contest_start", iso8601(start)),
            ("contest_end", iso8601(end)),
            ("reg_mode", str(reg_mode)),
            ("reg_end", iso8601(reg_end)),
            ("allow_compilers[]", "3"),
            ("allow_compilers[]", "6"),
            ("is_public_scoreboard", str(public_scoreboard).lower()),
            ("allow_view_other_page", "false"),
            ("hide_admin", str(hide_admin).lower()),
            ("submission_cd_time", "30" if contest_mode == 0 else "1"),
            ("freeze_scoreboard_period", "0"),
            ("penalty_value", "20"),
            ("enable_system_test", str(enable_system_test).lower()),
        ]
    )
    configured = api.post(
        app_url(base_url, f"/be/contests/{contest.contest_id}/manage/general"),
        data=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert_api_success(configured, operation=f"configure contest {contest.contest_id}")


def add_contest_member(
    api: APIRequestContext,
    base_url: str,
    contest_id: int,
    acct_id: int,
    *,
    member_type: str = "normal",
) -> None:
    response = api.post(
        app_url(base_url, f"/be/contests/{contest_id}/manage/acct"),
        form={"reqtype": "add", "acct_id": str(acct_id), "type": member_type},
    )
    assert_api_success(response, operation=f"add {member_type} account {acct_id} to contest {contest_id}")


def remove_contest_member(
    api: APIRequestContext,
    base_url: str,
    contest_id: int,
    acct_id: int,
    *,
    member_type: str = "normal",
) -> None:
    response = api.post(
        app_url(base_url, f"/be/contests/{contest_id}/manage/acct"),
        form={"reqtype": "remove", "acct_id": str(acct_id), "type": member_type},
    )
    assert_api_success(response, operation=f"remove {member_type} account {acct_id} from contest {contest_id}")


def new_user_context(
    browser: Browser,
    browser_context_args: dict,
    user: UserIdentity,
    base_url: str,
) -> BrowserContext:
    context = browser.new_context(**browser_context_args)
    login_browser_context(context, base_url, user.email, user.password)
    return context
