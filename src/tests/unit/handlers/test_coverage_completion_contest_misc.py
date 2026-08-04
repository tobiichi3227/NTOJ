import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.contests.base import contest_require_permission
from handlers.contests.contests import ContestInfoHandler, ContestListHandler
from handlers.contests.manage.reg import (
    ContestManageRegHandler,
    contest_manage_reg_dispatcher,
)
from handlers.contests.proset import ContestProsetHandler
from services.contests import ContestService, UserStatus
from services.pro import ProConst, ProService
from services.rate import RateService
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Base,
    Subject,
    contest,
    original,
)


class TestContestPermissions(unittest.IsolatedAsyncioTestCase):
    async def test_all_permission_modes_and_no_contest(self):
        async def endpoint(subject):
            subject.called = True
            return "ok"

        subject = Subject()
        subject.contest = None
        self.assertEqual(
            await contest_require_permission("admin")(endpoint)(subject), "ok"
        )

        for mode in ("admin", "normal", "all"):
            value = contest()
            value.is_admin = MagicMock(return_value=mode != "admin")
            value.member_is_status = MagicMock(return_value=mode != "normal")
            value.is_member = MagicMock(return_value=mode != "all")
            subject = Subject(value)
            subject.finish = AsyncMock()
            await contest_require_permission(mode)(endpoint)(subject)
            subject.finish.assert_awaited_once()

            if mode == "admin":
                value.is_admin.return_value = True
            elif mode == "normal":
                value.member_is_status.return_value = True
            else:
                value.is_member.return_value = True
            subject = Subject(value)
            subject.finish = AsyncMock()
            self.assertEqual(
                await contest_require_permission(mode)(endpoint)(subject), "ok"
            )
            subject.finish.assert_not_awaited()

        subject = Subject(contest())
        self.assertEqual(
            await contest_require_permission("unknown")(endpoint)(subject), "ok"
        )


class TestContestListAndProset(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.contests.get_contest_list = AsyncMock()
        self.problems = SimpleNamespace(
            list_pro=AsyncMock(),
            get_pro=AsyncMock(),
        )
        self.rates = SimpleNamespace(
            map_rate_acct=AsyncMock(),
            get_pro_ac_rate=AsyncMock(),
        )
        for service, value in (
            (ProService, self.problems),
            (RateService, self.rates),
        ):
            active = patch.object(service, "inst", value, create=True)
            active.start()
            self.addCleanup(active.stop)

    async def test_info_and_list_categories_offsets(self):
        subject = Subject()
        await original(ContestInfoHandler.get)(subject)
        subject.render.assert_awaited_once()

        now = datetime.datetime.now(datetime.UTC)
        contests = [
            {
                "contest_start": now - datetime.timedelta(hours=1),
                "contest_end": now + datetime.timedelta(hours=1),
            },
            {
                "contest_start": now + datetime.timedelta(hours=1),
                "contest_end": now + datetime.timedelta(hours=2),
            },
            {
                "contest_start": now - datetime.timedelta(hours=2),
                "contest_end": now - datetime.timedelta(hours=1),
            },
            {
                "contest_start": now,
                "contest_end": now,
            },
        ]
        self.contests.get_contest_list.return_value = (None, contests)
        method = original(ContestListHandler.get)
        for pageoff in ("bad", "-1", "0"):
            subject = Subject(arguments={"pageoff": pageoff})
            await method(subject)
            subject.render.assert_awaited_once()

    def proset_contest(self, **overrides):
        values = {
            "pro_list": {1: {}, 2: {}},
            "is_public_scoreboard": False,
        }
        values.update(overrides)
        value = contest(**values)
        value.is_start = MagicMock(return_value=True)
        value.is_running = MagicMock(return_value=True)
        value.is_admin = MagicMock(return_value=False)
        value.is_member = MagicMock(return_value=True)
        value.is_pro = MagicMock(side_effect=lambda pro_id: pro_id in value.pro_list)
        return value

    async def test_proset_permissions_validation_scores_and_ratios(self):
        method = original(ContestProsetHandler.get)
        self.assertEqual(
            (await method(Subject(arguments={"pageoff": "bad"})))[0],
            "Eparam",
        )

        value = self.proset_contest()
        value.is_start.return_value = False
        value.is_admin.return_value = False
        self.assertEqual((await method(Subject(value)))[0], "Eacces")

        value = self.proset_contest()
        value.is_member.return_value = False
        self.assertEqual((await method(Subject(value)))[0], "Eacces")

        self.rates.map_rate_acct.return_value = (
            None, {1: {"rate": 80, "state": 1}}
        )
        self.problems.list_pro.return_value = (
            None,
            [
                SimpleNamespace(pro_id=2),
                SimpleNamespace(pro_id=3),
                SimpleNamespace(pro_id=1),
            ],
        )
        value = self.proset_contest()
        value.is_running.return_value = False
        subject = Subject(value, {"pageoff": "-1"})
        await method(subject)
        subject.render.assert_awaited_once()
        self.rates.get_pro_ac_rate.assert_not_awaited()

        self.rates.get_pro_ac_rate.return_value = (
            None, {"ac": 1, "total": 2}
        )
        value = self.proset_contest(is_public_scoreboard=True)
        subject = Subject(value)
        await method(subject)
        self.assertEqual(self.rates.get_pro_ac_rate.await_count, 2)

        self.rates.get_pro_ac_rate.reset_mock()
        value = self.proset_contest()
        value.is_admin.return_value = True
        await method(Subject(value))
        self.assertEqual(self.rates.get_pro_ac_rate.await_count, 2)


class TestContestManageRegistration(Base):
    def managed_contest(self, users):
        value = contest(user_list=users)
        value.member_is_status = MagicMock(
            side_effect=lambda acct_id, status: (
                acct_id in value.user_list
                and value.user_list[acct_id]["status"] == status
            )
        )
        return value

    async def test_get_and_post(self):
        value = self.managed_contest(
            {
                1: {"status": UserStatus.ADMIN},
                2: {"status": UserStatus.REQUESTED},
                3: {"status": UserStatus.REJECTED},
                4: {"status": UserStatus.APPROVED},
            }
        )
        self.users.info_acct.side_effect = lambda acct_id: (
            None, SimpleNamespace(acct_id=acct_id)
        )
        subject = Subject(value)
        await original(ContestManageRegHandler.get)(subject)
        self.assertEqual(self.users.info_acct.await_count, 2)

        subject = Subject(value, {"reqtype": "approve", "acct_id": "bad"})
        self.assertEqual(
            (await original(ContestManageRegHandler.post)(subject))[0],
            "Eparam",
        )
        subject = Subject(value, {"reqtype": "approve", "acct_id": "2"})
        with patch.object(
            contest_manage_reg_dispatcher,
            "dispatch",
            AsyncMock(return_value="ok"),
        ) as dispatch:
            self.assertEqual(
                await original(ContestManageRegHandler.post)(subject), "ok"
            )
        self.assertEqual(subject.acct_id, 2)
        dispatch.assert_awaited_once_with(subject, "approve")

    async def test_approval_missing_wrong_requested_and_rejected(self):
        method = ContestManageRegHandler.approval_action
        value = self.managed_contest({})
        subject = Subject(value)
        subject.acct_id = 9
        self.assertEqual((await method(subject))[0], "Enoext")

        value = self.managed_contest(
            {9: {"status": UserStatus.APPROVED}}
        )
        subject = Subject(value)
        subject.acct_id = 9
        self.assertEqual((await method(subject))[0], "Enoext")

        for old_status, text in (
            (UserStatus.REQUESTED, "Approve account"),
            (UserStatus.REJECTED, "Re-approve account"),
        ):
            value = self.managed_contest({9: {"status": old_status}})
            subject = Subject(value)
            subject.acct_id = 9
            result = await method(subject)
            self.assertEqual(result[0], "S")
            self.assertIn(text, result[1])
            self.assertEqual(
                value.user_list[9]["status"], UserStatus.APPROVED
            )

    async def test_reject_missing_and_success(self):
        method = ContestManageRegHandler.reject_action
        value = self.managed_contest({})
        subject = Subject(value)
        subject.acct_id = 9
        self.assertEqual((await method(subject))[0], "Enoext")

        value = self.managed_contest(
            {9: {"status": UserStatus.REQUESTED}}
        )
        subject = Subject(value)
        subject.acct_id = 9
        self.assertEqual((await method(subject))[0], "S")
        self.assertEqual(value.user_list[9]["status"], UserStatus.REJECTED)


if __name__ == "__main__":
    unittest.main()
