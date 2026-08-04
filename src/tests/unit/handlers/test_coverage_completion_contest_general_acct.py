import datetime
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.contests.manage.acct import (
    ContestManageAcctHandler,
    contest_manage_acct_dispatcher,
)
from handlers.contests.manage.general import (
    ContestManageAddHandler,
    ContestManageDashHandler,
    ContestManageDescEditHandler,
    ContestManageGeneralHandler,
    contest_manage_add_dispatcher,
    contest_manage_desc_edit_dispatcher,
    contest_manage_general_dispatcher,
    trantime,
)
from services.chal import Compiler
from services.contests import (
    ContestMode,
    ContestService,
    ProblemScoreType,
    RegMode,
    UserStatus,
)
from services.user import UserConst, UserService


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


def contest(**overrides):
    data = {
        "contest_id": 9,
        "contest_creator": 1,
        "name": "Contest",
        "contest_mode": ContestMode.IOI,
        "contest_start": datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        "contest_end": datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
        "reg_mode": RegMode.FREE_REG,
        "reg_end": datetime.datetime(2025, 1, 1, 12, tzinfo=datetime.UTC),
        "user_list": {
            1: {"status": UserStatus.ADMIN},
            2: {"status": UserStatus.APPROVED},
        },
        "pro_list": {10: {"score_type": ProblemScoreType.IOI2017}},
        "allow_compilers": {Compiler.GPP},
        "is_public_scoreboard": False,
        "allow_view_other_page": False,
        "hide_admin": False,
        "submission_cd_time": 30,
        "freeze_scoreboard_period": 10,
        "penalty_value": 20,
        "enable_system_test": False,
        "desc_before_contest": "",
        "desc_during_contest": "",
        "desc_after_contest": "",
    }
    data.update(overrides)
    value = SimpleNamespace(**data)
    value.is_start = MagicMock(return_value=True)
    return value


class Subject:
    def __init__(self, value=None, arguments=None):
        self.contest = value or contest()
        self.arguments = arguments or {}
        self.error = MagicMock(side_effect=lambda item, **_: item)
        self.render = AsyncMock()
        self.add_log = AsyncMock(return_value=(None, 1))
        self.len_check = MagicMock(return_value=None)
        self.rs = AsyncMock()
        self.acct = MagicMock(
            acct_id=7, acct_type=UserConst.ACCTTYPE_KERNEL, name="admin"
        )

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)

    def get_arguments(self, name):
        return self.arguments.get(name, [])


def settings(**overrides):
    data = {
        "name": "Updated",
        "contest_mode": str(ContestMode.ACM.value),
        "contest_start": "2025-01-01T00:00:00.000Z",
        "contest_end": "2025-01-02T00:00:00.000Z",
        "reg_mode": str(RegMode.FREE_REG.value),
        "reg_end": "2025-01-01T12:00:00.000Z",
        "allow_compilers[]": [str(Compiler.GPP.value), "999"],
        "is_public_scoreboard": "true",
        "allow_view_other_page": "true",
        "hide_admin": "false",
        "enable_system_test": "true",
        "submission_cd_time": "-1",
        "freeze_scoreboard_period": "-1",
        "penalty_value": "-1",
    }
    data.update(overrides)
    return data


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.contests = SimpleNamespace(
            update_contest=AsyncMock(return_value=([], None)),
            add_default_contest=AsyncMock(return_value=(None, 55)),
        )
        self.users = SimpleNamespace(info_acct=AsyncMock())
        for service, value in (
            (ContestService, self.contests),
            (UserService, self.users),
        ):
            active = patch.object(service, "inst", value, create=True)
            active.start()
            self.addCleanup(active.stop)


class TestGeneral(Base):
    def test_trantime(self):
        self.assertEqual(trantime(""), (None, None))
        self.assertEqual(trantime("bad")[0][0], "Eparam")
        err, value = trantime("2025-01-01T00:00:00.000Z")
        self.assertIsNone(err)
        self.assertEqual(value.tzinfo, datetime.UTC)

    async def test_get_and_post_dispatchers(self):
        for handler in (
            ContestManageDashHandler,
            ContestManageGeneralHandler,
            ContestManageDescEditHandler,
            ContestManageAddHandler,
        ):
            subject = Subject()
            await original(handler.get)(subject)
            subject.render.assert_awaited_once()

        pairs = (
            (ContestManageGeneralHandler, contest_manage_general_dispatcher),
            (ContestManageDescEditHandler, contest_manage_desc_edit_dispatcher),
            (ContestManageAddHandler, contest_manage_add_dispatcher),
            (ContestManageAcctHandler, contest_manage_acct_dispatcher),
        )
        for handler, dispatcher in pairs:
            subject = Subject(arguments={"reqtype": "go"})
            with patch.object(
                dispatcher, "dispatch", AsyncMock(return_value="ok")
            ) as dispatch:
                self.assertEqual(await original(handler.post)(subject), "ok")
            dispatch.assert_awaited_once_with(subject, "go")

    async def test_invalid_times_and_order(self):
        method = ContestManageGeneralHandler.update_action
        for field in ("contest_start", "contest_end", "reg_end"):
            result = await method(
                Subject(arguments=settings(**{field: "bad"}))
            )
            self.assertEqual(result[0], "Eparam")
        result = await method(
            Subject(
                arguments=settings(
                    contest_end="2025-01-01T00:00:00.000Z"
                )
            )
        )
        self.assertEqual(result[0], "Eparam")

    async def test_free_registration_negative_defaults_and_cache(self):
        value = contest(
            reg_mode=RegMode.REG_APPROVAL,
            user_list={
                1: {"status": UserStatus.ADMIN},
                2: {"status": UserStatus.REQUESTED},
                3: {"status": UserStatus.REJECTED},
                4: {"status": UserStatus.APPROVED},
            },
        )
        subject = Subject(value, settings())
        self.assertEqual(
            await ContestManageGeneralHandler.update_action(subject),
            ("S", ""),
        )
        self.assertEqual(value.submission_cd_time, 1)
        self.assertEqual(value.freeze_scoreboard_period, 0)
        self.assertEqual(value.penalty_value, 20)
        self.assertEqual(value.allow_compilers, {Compiler.GPP})
        self.assertEqual(value.user_list[2]["status"], UserStatus.APPROVED)
        self.assertNotIn(3, value.user_list)
        self.assertEqual(value.pro_list[10]["score_type"], ProblemScoreType.ICPC)
        subject.rs.delete.assert_awaited_once_with("contest_9_scores")

    async def test_invited_invalid_numbers_and_unchanged_cache(self):
        value = contest(
            reg_mode=RegMode.REG_APPROVAL,
            freeze_scoreboard_period=0,
            user_list={
                1: {"status": UserStatus.ADMIN},
                2: {"status": UserStatus.REQUESTED},
                3: {"status": UserStatus.REJECTED},
            },
        )
        args = settings(
            contest_mode=str(ContestMode.IOI.value),
            reg_mode=str(RegMode.INVITED.value),
            submission_cd_time="bad",
            freeze_scoreboard_period="bad",
            penalty_value="bad",
            is_public_scoreboard="false",
            allow_view_other_page="false",
            hide_admin="true",
            enable_system_test="false",
        )
        subject = Subject(value, args)
        await ContestManageGeneralHandler.update_action(subject)
        self.assertEqual(value.user_list, {1: {"status": UserStatus.ADMIN}})
        self.assertEqual(value.reg_end, value.contest_end)
        self.assertEqual(
            (value.submission_cd_time, value.freeze_scoreboard_period, value.penalty_value),
            (30, 0, 20),
        )
        self.assertEqual(
            value.pro_list[10]["score_type"], ProblemScoreType.IOI2017
        )
        subject.rs.delete.assert_not_awaited()

    async def test_descriptions_and_add(self):
        for kind, attribute in (
            ("before", "desc_before_contest"),
            ("during", "desc_during_contest"),
            ("after", "desc_after_contest"),
        ):
            value = contest()
            result = await ContestManageDescEditHandler.update_action(
                Subject(value, {"desc": kind, "desc_type": kind})
            )
            self.assertEqual(result, ("S", ""))
            self.assertEqual(getattr(value, attribute), kind)
        result = await ContestManageDescEditHandler.update_action(
            Subject(arguments={"desc": "x", "desc_type": "bad"})
        )
        self.assertEqual(result[0], "Eunk")

        subject = Subject(arguments={"name": ""})
        subject.len_check.return_value = ("Eparam", "bad")
        self.assertEqual(
            (await ContestManageAddHandler.add_action(subject))[0], "Eparam"
        )
        subject = Subject(arguments={"name": "New"})
        self.assertEqual(
            await ContestManageAddHandler.add_action(subject), ("S", 55)
        )


class TestAccounts(Base):
    async def test_get(self):
        value = contest(
            user_list={
                1: {"status": UserStatus.ADMIN},
                2: {"status": UserStatus.APPROVED},
                3: {"status": UserStatus.REQUESTED},
            }
        )
        self.users.info_acct.side_effect = lambda acct_id: (
            None,
            SimpleNamespace(acct_id=acct_id),
        )
        subject = Subject(value)
        await original(ContestManageAcctHandler.get)(subject)
        self.assertEqual(self.users.info_acct.await_count, 3)
        subject.render.assert_awaited_once()

    async def test_add_paths(self):
        method = ContestManageAcctHandler.add_action
        cases = (
            ({"acct_id": "bad", "type": "normal"}, "Eparam"),
            ({"acct_id": "1", "type": "normal"}, "Eexist"),
            ({"acct_id": "2", "type": "bad"}, "Eparam"),
        )
        for args, code in cases:
            self.assertEqual((await method(Subject(arguments=args)))[0], code)

        self.contests.update_contest.return_value = (
            [("Enoext", "missing")], None
        )
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"acct_id": "8", "type": "normal"})
                )
            )[0],
            "Enoext",
        )
        self.contests.update_contest.return_value = ([], None)
        subject = Subject(arguments={"acct_id": "8", "type": "normal"})
        self.assertEqual((await method(subject))[0], "S")
        subject.rs.delete.assert_awaited_once()
        subject = Subject(
            contest(hide_admin=True), {"acct_id": "8", "type": "admin"}
        )
        self.assertEqual((await method(subject))[0], "S")
        subject.rs.delete.assert_not_awaited()

    async def test_remove_paths(self):
        method = ContestManageAcctHandler.remove_action
        cases = (
            (contest(), {"acct_id": "bad", "type": "normal"}, "Eparam"),
            (contest(), {"acct_id": "1", "type": "normal"}, "Eacces"),
            (contest(), {"acct_id": "99", "type": "normal"}, "Enoext"),
            (contest(), {"acct_id": "2", "type": "bad"}, "Eparam"),
            (contest(), {"acct_id": "2", "type": "admin"}, "Eacces"),
        )
        for value, args, code in cases:
            self.assertEqual((await method(Subject(value, args)))[0], code)
        subject = Subject(arguments={"acct_id": "2", "type": "normal"})
        self.assertEqual((await method(subject))[0], "S")
        subject.rs.delete.assert_awaited_once()
        value = contest(
            hide_admin=True,
            user_list={
                1: {"status": UserStatus.ADMIN},
                8: {"status": UserStatus.ADMIN},
            },
        )
        subject = Subject(value, {"acct_id": "8", "type": "admin"})
        self.assertEqual((await method(subject))[0], "S")
        subject.rs.delete.assert_not_awaited()

    async def test_multi_add(self):
        method = ContestManageAcctHandler.multi_add_action
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"acct_id": "2", "type": "bad"})
                )
            )[0],
            "Eparam",
        )
        self.contests.update_contest.return_value = (
            [("Enoext", "missing")], None
        )
        subject = Subject(arguments={"acct_id": "1,2-3", "type": "normal"})
        result = await method(subject)
        self.assertIn("Errors:", result[1])
        subject.rs.delete.assert_awaited_once()
        self.contests.update_contest.return_value = ([], None)
        subject = Subject(
            contest(hide_admin=True),
            {"acct_id": "8-9", "type": "admin"},
        )
        result = await method(subject)
        self.assertIn("successfully added", result[1])
        subject.rs.delete.assert_not_awaited()

    async def test_multi_remove(self):
        method = ContestManageAcctHandler.multi_remove_action
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"acct_id": "2", "type": "bad"})
                )
            )[0],
            "Eparam",
        )
        value = contest(
            user_list={
                1: {"status": UserStatus.ADMIN},
                2: {"status": UserStatus.APPROVED},
                3: {"status": UserStatus.ADMIN},
            }
        )
        self.contests.update_contest.return_value = (
            [("Edb", "failed")], None
        )
        result = await method(
            Subject(value, {"acct_id": "1-4", "type": "normal"})
        )
        self.assertIn("Successfully removed: [2]", result[1])
        for code in ("Eacces", "Enoext", "Edb"):
            self.assertIn(code, result[1])

        self.contests.update_contest.return_value = ([], None)
        value = contest(
            hide_admin=True,
            user_list={
                1: {"status": UserStatus.ADMIN},
                8: {"status": UserStatus.ADMIN},
                9: {"status": UserStatus.ADMIN},
            },
        )
        subject = Subject(value, {"acct_id": "8-9", "type": "admin"})
        result = await method(subject)
        self.assertIn("[8, 9]", result[1])
        subject.rs.delete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
