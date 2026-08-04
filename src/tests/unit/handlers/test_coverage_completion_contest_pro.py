import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.contests.manage.pro import (
    ContestManageProHandler,
    contest_manage_pro_dispatcher,
)
from services.chal import ChalService, Compiler
from services.contests import (
    ChallengeResultStyle,
    ContestMode,
    ContestService,
    ProblemScoreType,
)
from services.judge import JudgeServerClusterService
from services.pro import ProConst, ProService
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Base,
    Subject,
    contest,
    original,
)


def problem_contest(**overrides):
    values = {
        "pro_list": {
            1: {
                "score_type": ProblemScoreType.IOI2017,
                "challenge_style": ChallengeResultStyle.FULL,
            }
        },
        "contest_mode": ContestMode.IOI,
        "enable_system_test": False,
    }
    values.update(overrides)
    value = contest(**values)
    value.is_pro = MagicMock(side_effect=lambda pro_id: pro_id in value.pro_list)
    value.is_end = MagicMock(return_value=True)
    value.is_admin = MagicMock(
        side_effect=lambda *_, **kwargs: kwargs.get("acct_id") == 7
    )
    return value


def problem():
    return SimpleNamespace(
        config=SimpleNamespace(name="config"),
        problem_type="batch",
        status=ProConst.PRO_STATUS_CONTEST_USER,
    )


def db_subject(value, arguments, rows):
    subject = Subject(value, arguments)
    connection = AsyncMock()
    connection.fetch.return_value = rows
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=connection)
    manager.__aexit__ = AsyncMock(return_value=None)
    subject.db = MagicMock()
    subject.db.acquire.return_value = manager
    return subject, connection


class TestContestManageProblems(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.problems = SimpleNamespace(
            get_pro=AsyncMock(return_value=(None, problem())),
            update_pro=AsyncMock(return_value=(None, None)),
        )
        self.challenges = SimpleNamespace(
            reset_chal=AsyncMock(),
            emit_chal=AsyncMock(),
        )
        self.judges = SimpleNamespace(
            is_server_online=MagicMock(return_value=True)
        )
        for service, value in (
            (ProService, self.problems),
            (ChalService, self.challenges),
            (JudgeServerClusterService, self.judges),
        ):
            active = patch.object(service, "inst", value, create=True)
            active.start()
            self.addCleanup(active.stop)
        active = patch.object(
            Subject,
            "_rejudge_challenges",
            ContestManageProHandler._rejudge_challenges,
            create=True,
        )
        active.start()
        self.addCleanup(active.stop)

    async def test_get_skips_missing_problem_and_post_dispatches(self):
        value = problem_contest(
            pro_list={
                1: {"score_type": ProblemScoreType.IOI2017},
                2: {"score_type": ProblemScoreType.IOI2017},
            }
        )
        self.problems.get_pro.side_effect = [
            (("Enoext", "missing"), None),
            (None, problem()),
        ]
        subject = Subject(value)
        await original(ContestManageProHandler.get)(subject)
        subject.render.assert_awaited_once()

        subject = Subject(value, {"reqtype": "add"})
        with patch.object(
            contest_manage_pro_dispatcher,
            "dispatch",
            AsyncMock(return_value="ok"),
        ) as dispatch:
            self.assertEqual(
                await original(ContestManageProHandler.post)(subject), "ok"
            )
        dispatch.assert_awaited_once_with(subject, "add")

    async def test_remove_invalid_and_multi_add_acm(self):
        self.assertEqual(
            (
                await ContestManageProHandler.remove_action(
                    Subject(arguments={"pro_id": "bad"})
                )
            )[0],
            "Eparam",
        )

        value = problem_contest(contest_mode=ContestMode.ACM)
        self.contests.update_contest.return_value = (
            [("Enoext", "missing")], None
        )
        result = await ContestManageProHandler.multi_add_action(
            Subject(
                value,
                {
                    "pro_id": "2-3",
                    "score_type": str(ProblemScoreType.IOI2017.value),
                },
            )
        )
        self.assertIn("Errors:", result[1])
        self.assertEqual(
            value.pro_list[2]["score_type"], ProblemScoreType.ICPC
        )

    async def test_rejudge_helper_error_and_each_challenge(self):
        subject = Subject(problem_contest())
        self.problems.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertIsNone(
            await ContestManageProHandler._rejudge_challenges(
                subject, 1, [(10, Compiler.GPP)]
            )
        )
        self.challenges.reset_chal.assert_not_awaited()

        self.problems.get_pro.return_value = (None, problem())
        await ContestManageProHandler._rejudge_challenges(
            subject,
            1,
            [(10, Compiler.GPP), (11, Compiler.CLANGPP)],
            include_system_test=True,
        )
        self.assertEqual(self.challenges.reset_chal.await_count, 2)
        self.assertEqual(self.challenges.emit_chal.await_count, 2)

    async def test_rechal_judge_problem_and_both_database_modes(self):
        method = ContestManageProHandler.rechal_action
        self.judges.is_server_online.return_value = False
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"pro_id": "1"})
                )
            )[0],
            "Ejudge",
        )

        self.judges.is_server_online.return_value = True
        self.problems.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"pro_id": "1"})
                )
            )[0],
            "Enoext",
        )

        self.problems.get_pro.return_value = (None, problem())
        value = problem_contest(enable_system_test=False)
        subject, connection = db_subject(
            value,
            {"pro_id": "1"},
            [(10, Compiler.GPP)],
        )
        self.assertEqual((await method(subject))[0], "S")
        connection.fetch.assert_awaited_once()

        value = problem_contest(enable_system_test=True)
        subject, connection = db_subject(
            value,
            {"pro_id": "1"},
            [
                (7, 10, Compiler.GPP),
                (8, 11, Compiler.CLANGPP),
            ],
        )
        self.assertEqual((await method(subject))[0], "S")
        self.assertEqual(connection.fetch.await_count, 1)
        self.assertGreaterEqual(self.challenges.emit_chal.await_count, 3)

    async def test_public_validation_service_errors_and_success(self):
        method = ContestManageProHandler.public_action
        self.assertEqual(
            (await method(Subject(arguments={"pro_id": "bad"})))[0],
            "Eparam",
        )

        self.problems.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (
                await method(
                    Subject(problem_contest(), {"pro_id": "1"})
                )
            )[0],
            "Enoext",
        )

        public_problem = problem()
        self.problems.get_pro.return_value = (None, public_problem)
        self.problems.update_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(
            (
                await method(
                    Subject(problem_contest(), {"pro_id": "1"})
                )
            )[0],
            "Edb",
        )

        self.problems.update_pro.return_value = (None, None)
        subject = Subject(problem_contest(), {"pro_id": "1"})
        self.assertEqual(await method(subject), ("S", ""))
        self.assertEqual(public_problem.status, ProConst.STATUS_ONLINE)

    async def test_system_test_time_judge_problem_empty_and_success(self):
        method = ContestManageProHandler.system_test_action

        value = problem_contest(enable_system_test=True)
        value.is_end.return_value = False
        self.assertEqual(
            (await method(Subject(value, {"pro_id": "1"})))[0], "Etime"
        )

        value.is_end.return_value = True
        self.judges.is_server_online.return_value = False
        self.assertEqual(
            (await method(Subject(value, {"pro_id": "1"})))[0], "Ejudge"
        )

        self.judges.is_server_online.return_value = True
        self.problems.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (await method(Subject(value, {"pro_id": "1"})))[0], "Enoext"
        )

        self.problems.get_pro.return_value = (None, problem())
        subject, _ = db_subject(value, {"pro_id": "1"}, [])
        self.assertEqual((await method(subject))[0], "Enoext")

        subject, _ = db_subject(
            value,
            {"pro_id": "1"},
            [(10, Compiler.GPP), (11, Compiler.CLANGPP)],
        )
        result = await method(subject)
        self.assertEqual(result[0], "S")
        self.assertIn("2 AC challenges", result[1])


if __name__ == "__main__":
    unittest.main()
