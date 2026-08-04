import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.chal import ChalHandler, ChalListHandler, chal_dispatcher
from services.chal import (
    ChalConst,
    ChalSearchingParamBuilder,
    ChalService,
    Compiler,
    MessageType,
)
from services.contests import UserStatus
from services.pro import ProConst, ProService
from services.rate import RateService
from services.user import UserConst


def original(function):
    seen = set()
    while function.__name__ == "wrap" and function not in seen:
        seen.add(function)
        nested = [
            cell.cell_contents
            for cell in (function.__closure__ or ())
            if inspect.iscoroutinefunction(cell.cell_contents)
        ]
        if len(nested) != 1:
            raise AssertionError(f"Cannot unwrap {function}: {nested}")
        function = nested[0]
    return function


class Subject:
    def __init__(self, arguments=None, contest=None):
        self.arguments = arguments or {}
        self.contest = contest
        self.error = MagicMock(side_effect=lambda value: value)
        self.render = AsyncMock(return_value="rendered")
        self.add_log = AsyncMock(return_value=(None, 1))
        self.len_check = MagicMock(return_value=None)
        self.acct = MagicMock(
            acct_id=7,
            acct_type=UserConst.ACCTTYPE_USER,
            name="viewer",
        )
        self.acct.is_kernel.return_value = False
        self._parse_problem_filter = ChalListHandler._parse_problem_filter.__get__(self)
        self._parse_account_filter = ChalListHandler._parse_account_filter.__get__(self)
        self._setup_permissions = ChalListHandler._setup_permissions.__get__(self)
        self._apply_contest_filters = ChalListHandler._apply_contest_filters.__get__(self)
        self._get_non_admin_contest_accounts = (
            ChalListHandler._get_non_admin_contest_accounts.__get__(self)
        )
        self._get_post_contest_accounts = (
            ChalListHandler._get_post_contest_accounts.__get__(self)
        )

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


def challenge(*, owner=8, contest_id=0):
    return SimpleNamespace(
        chal_id=12,
        pro_id=5,
        acct_id=owner,
        contest_id=contest_id,
        compiler_type=Compiler.GPP,
        total_result=MagicMock(),
        subtask_results={1: MagicMock()},
        testdata_results={1: MagicMock()},
    )


def contest():
    value = MagicMock(
        contest_id=9,
        hide_admin=False,
        is_public_scoreboard=True,
        user_list={
            7: {"status": UserStatus.APPROVED},
            8: {"status": UserStatus.ADMIN},
            10: {"status": UserStatus.APPROVED},
        },
    )
    value.name = "Contest"
    value.is_admin.return_value = False
    value.is_start.return_value = True
    value.is_running.return_value = False
    return value


class TestChallengeListHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.chal_service = SimpleNamespace(
            get_chals_count=AsyncMock(return_value=(None, 1)),
            list_chal=AsyncMock(
                return_value=(None, [challenge(owner=7, contest_id=9)])
            ),
        )
        active_patch = patch.object(ChalService, "inst", self.chal_service, create=True)
        active_patch.start()
        self.addCleanup(active_patch.stop)

    async def test_get_validates_inputs_and_renders_contest_title(self):
        method = original(ChalListHandler.get)
        self.assertEqual((await method(Subject({"pageoff": "bad"})))[0], "Eparam")
        self.assertEqual((await method(Subject({"state": "999"})))[0], "Eparam")
        self.assertEqual(
            (await method(Subject({"compiler_type": "999"})))[0], "Eparam"
        )

        value = contest()
        value.is_admin.return_value = True
        subject = Subject(
            {"pageoff": "-2", "proid": "5,6", "acctid": "7"}, contest=value
        )
        await method(subject)
        self.assertEqual(subject.render.await_args.args[1], "Contest - Challenges")
        self.assertEqual(subject.render.await_args.kwargs["pageoff"], 0)
        self.assertEqual(
            subject.render.await_args.kwargs["challist"][0].compiler_type,
            "G++ 14.2.0 GNU++17",
        )

    def test_filter_helpers_cover_admin_running_private_and_public_contests(self):
        subject = Subject()
        self.assertIsNone(ChalListHandler._parse_problem_filter(subject, ""))
        self.assertEqual(ChalListHandler._parse_problem_filter(subject, "1,2"), [1, 2])
        self.assertIsNone(ChalListHandler._parse_account_filter(subject, ""))
        self.assertEqual(ChalListHandler._parse_account_filter(subject, "7"), [7])

        builder = ChalSearchingParamBuilder()
        subject.acct.is_kernel.return_value = True
        self.assertTrue(ChalListHandler._setup_permissions(subject, builder))
        self.assertEqual(builder.build().allow_pro_statuses, ProConst.PRO_STATUS_KERNEL_USER)
        self.assertEqual(
            ChalListHandler._apply_contest_filters(subject, builder, [7], True), [7]
        )

        value = contest()
        subject.contest = value
        value.is_admin.return_value = True
        builder = ChalSearchingParamBuilder()
        self.assertEqual(
            ChalListHandler._apply_contest_filters(subject, builder, [7], False), [7]
        )
        self.assertEqual(builder.build().contest, 9)

        value.is_admin.return_value = False
        value.is_start.return_value = False
        self.assertEqual(
            ChalListHandler._get_non_admin_contest_accounts(subject, None), []
        )
        value.is_start.return_value = True
        value.is_running.return_value = True
        self.assertEqual(
            ChalListHandler._get_non_admin_contest_accounts(subject, [10]), [7]
        )

        value.is_running.return_value = False
        value.is_public_scoreboard = False
        self.assertEqual(
            ChalListHandler._get_post_contest_accounts(subject, [10]), [7]
        )
        value.is_public_scoreboard = True
        self.assertEqual(
            ChalListHandler._get_post_contest_accounts(subject, None), [7, 10]
        )
        value.is_admin.side_effect = lambda acct_id=None, **_: acct_id == 8
        self.assertEqual(
            ChalListHandler._get_post_contest_accounts(subject, [7, 8, 10]),
            [7, 10],
        )


class TestChallengeHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.chal_service = SimpleNamespace(
            get_chal=AsyncMock(),
            update_total_result=AsyncMock(),
            update_subtask_result=AsyncMock(),
            update_testdata_result=AsyncMock(),
        )
        self.pro_service = SimpleNamespace(get_pro=AsyncMock())
        self.rate_service = SimpleNamespace(refresh_pro_topcoder=AsyncMock())
        for service, value in (
            (ChalService, self.chal_service),
            (ProService, self.pro_service),
            (RateService, self.rate_service),
        ):
            active_patch = patch.object(service, "inst", value, create=True)
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def test_get_validation_visibility_and_problem_errors(self):
        method = original(ChalHandler.get)
        self.assertEqual((await method(Subject(), "bad"))[0], "Eparam")
        self.chal_service.get_chal.return_value = (("Enoext", "missing"), None)
        self.assertEqual(await method(Subject(), "12"), ("Enoext", "missing"))

        self.chal_service.get_chal.return_value = (None, challenge(contest_id=9))
        self.assertEqual((await method(Subject(), "12"))[0], "Enoext")

        value = contest()
        value.is_start.return_value = False
        value.is_admin.side_effect = lambda target=None, acct_id=None: acct_id == 8
        self.assertEqual(
            (await method(Subject(contest=value), "12"))[0], "Eacces"
        )

        value = contest()
        value.is_running.return_value = True
        value.hide_admin = True
        value.is_admin.side_effect = lambda target=None, acct_id=None: acct_id == 8
        self.assertEqual(
            (await method(Subject(contest=value), "12"))[0], "Eacces"
        )

        value = contest()
        value.is_running.return_value = True
        value.hide_admin = False
        value.is_admin.return_value = False
        self.assertEqual(
            (await method(Subject(contest=value), "12"))[0], "Eacces"
        )

        value = contest()
        value.is_public_scoreboard = False
        self.assertEqual(
            (await method(Subject(contest=value), "12"))[0], "Eacces"
        )

        item = challenge(owner=7)
        self.chal_service.get_chal.return_value = (None, item)
        subject = Subject()
        subject.acct.is_kernel.return_value = True
        self.pro_service.get_pro.return_value = (("Eacces", "hidden"), None)
        self.assertEqual(await method(subject, "12"), ("Eacces", "hidden"))
        self.pro_service.get_pro.assert_awaited_with(5, ProConst.PRO_STATUS_KERNEL_USER)

    async def test_get_success_builds_testdata_to_subtask_map(self):
        method = original(ChalHandler.get)
        item = challenge(owner=7)
        self.chal_service.get_chal.return_value = (None, item)
        td1 = SimpleNamespace(testdata_id=1)
        td2 = SimpleNamespace(testdata_id=2)
        config = SimpleNamespace(
            subtask_configs={
                3: SimpleNamespace(subtask_id=3, testdatas=[td1, td2]),
                4: SimpleNamespace(subtask_id=4, testdatas=[td1]),
            }
        )
        self.pro_service.get_pro.return_value = (
            None,
            SimpleNamespace(pro_id=5, config=config),
        )
        subject = Subject()
        subject.acct.is_kernel.return_value = True
        await method(subject, "12")
        mapping = subject.render.await_args.kwargs["testdata_to_subtasks"]
        self.assertEqual(mapping[1], [3, 4])
        self.assertEqual(mapping[2], [3])
        self.assertTrue(subject.render.await_args.kwargs["rechal"])

    async def test_post_dispatch_and_reject_error_and_success_branches(self):
        post = original(ChalHandler.post)
        self.assertEqual((await post(Subject(), "bad"))[0], "Eparam")
        subject = Subject({"reqtype": "reject"})
        with patch.object(
            chal_dispatcher, "dispatch", new=AsyncMock(return_value="dispatched")
        ) as dispatch:
            self.assertEqual(await post(subject, "12"), "dispatched")
        self.assertEqual(subject.path_args, [12])
        dispatch.assert_awaited_once_with(subject, "reject")

        subject = Subject({"chal_id": "12", "reason": "x"})
        subject.len_check.return_value = ("Elen", "too long")
        self.assertEqual(
            await ChalHandler.reject_challenge(subject), ("Elen", "too long")
        )
        subject.len_check.return_value = None
        self.assertEqual((await ChalHandler.reject_challenge(subject))[0], "Eacces")

        subject.acct.is_kernel.return_value = True
        self.chal_service.get_chal.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            await ChalHandler.reject_challenge(subject), ("Enoext", "missing")
        )

        item = challenge(owner=7)
        self.chal_service.get_chal.return_value = (None, item)
        await ChalHandler.reject_challenge(subject)
        self.assertEqual(item.total_result.state, ChalConst.STATE_REJECTED)
        self.assertEqual(item.total_result.message_type, MessageType.TEXT)
        self.assertEqual(item.subtask_results[1].state, ChalConst.STATE_REJECTED)
        self.assertEqual(item.testdata_results[1].state, ChalConst.STATE_REJECTED)
        self.chal_service.update_total_result.assert_awaited_once()
        self.chal_service.update_subtask_result.assert_awaited_once()
        self.chal_service.update_testdata_result.assert_awaited_once()
        self.rate_service.refresh_pro_topcoder.assert_awaited_once_with(5)
        subject.error.assert_called_with(("S", ""))


if __name__ == "__main__":
    unittest.main()
