import datetime
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.prospec.batch.submit import BatchSubmitHandler, submit_dispatcher
from services.chal import ChalConst, ChalService, Compiler
from services.contests import ContestService, UserStatus
from services.judge import JudgeServerClusterService
from services.pro import ProConst, ProService, ProType
from services.prospec.batch import BatchProblemSpec
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


class Subject:
    def __init__(self, arguments=None, contest=None):
        self.arguments = arguments or {}
        self.contest = contest
        self.error = MagicMock(side_effect=lambda value: value)
        self.render = AsyncMock(return_value="rendered")
        self.add_log = AsyncMock(return_value=(None, 1))
        self.rs = AsyncMock()
        self.acct = MagicMock(
            acct_id=7,
            acct_type=UserConst.ACCTTYPE_USER,
            name="submitter",
            last_compiler=Compiler.CLANGPP,
        )
        self.acct.is_kernel.return_value = False

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


def problem(*, allow_submit=True, status=ProConst.STATUS_ONLINE):
    config = SimpleNamespace(spec_config=BatchProblemSpec().get_default_config())
    return SimpleNamespace(
        pro_id=5,
        name="Batch",
        status=status,
        tags="",
        allow_submit=allow_submit,
        problem_type=ProType.BATCH,
        config=config,
    )


class TestBatchSubmitHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pro_service = SimpleNamespace(get_pro=AsyncMock())
        self.chal_service = SimpleNamespace(
            add_chal=AsyncMock(),
            emit_chal=AsyncMock(),
            reset_chal=AsyncMock(),
            get_chal=AsyncMock(),
        )
        self.user_service = SimpleNamespace(update_acct=AsyncMock())
        self.judge_service = SimpleNamespace(is_server_online=MagicMock(return_value=True))
        self.patches = [
            patch.object(ProService, "inst", self.pro_service, create=True),
            patch.object(ChalService, "inst", self.chal_service, create=True),
            patch.object(UserService, "inst", self.user_service, create=True),
            patch.object(
                JudgeServerClusterService, "inst", self.judge_service, create=True
            ),
        ]
        for active_patch in self.patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def test_get_validates_inputs_problem_type_and_contest_compilers(self):
        method = original(BatchSubmitHandler.get)

        self.assertEqual(
            await method(Subject({"pro_id": "bad"})),
            ("Eparam", "Invalid problem ID"),
        )
        self.assertEqual(
            await method(Subject({"pro_id": "5", "contest_id": "bad"})),
            ("Eparam", "Invalid contest ID"),
        )

        subject = Subject({"pro_id": "5"})
        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(await method(subject), ("Enoext", "missing"))

        subject = Subject({"pro_id": "5"})
        self.pro_service.get_pro.return_value = (
            None,
            SimpleNamespace(problem_type=ProType.OUTPUTONLY, config=object()),
        )
        self.assertEqual(
            await method(subject),
            ("Eparam", "Invalid problem type for this handler"),
        )

        allowed = {Compiler.GPP, Compiler.PYTHON3}
        contest = SimpleNamespace(allow_compilers={Compiler.PYTHON3})
        contest_service = SimpleNamespace(
            get_contest=AsyncMock(return_value=(None, contest))
        )
        subject = Subject({"pro_id": "5", "contest_id": "9"})
        pro = problem()
        pro.config.spec_config.allow_compilers = allowed
        self.pro_service.get_pro.return_value = (None, pro)
        with patch.object(ContestService, "inst", contest_service, create=True):
            await method(subject)
        subject.render.assert_awaited_once()
        self.assertEqual(
            subject.render.await_args.kwargs["allow_compilers"], {Compiler.PYTHON3}
        )
        self.pro_service.get_pro.assert_awaited_with(
            5, ProConst.PRO_STATUS_CONTEST_USER
        )

        subject = Subject({"pro_id": "5"})
        subject.acct.is_kernel.return_value = True
        self.pro_service.get_pro.return_value = (None, problem())
        await method(subject)
        self.pro_service.get_pro.assert_awaited_with(5, ProConst.PRO_STATUS_KERNEL_USER)

        subject = Subject({"pro_id": "5"})
        self.pro_service.get_pro.return_value = (
            None,
            SimpleNamespace(problem_type=ProType.BATCH, config=object()),
        )
        result = await method(subject)
        self.assertEqual(result[0], "Eunk")

    async def test_post_rejects_offline_judge_and_dispatches_online_action(self):
        method = original(BatchSubmitHandler.post)
        self.judge_service.is_server_online.return_value = False
        self.assertEqual(
            await method(Subject({"reqtype": "submit"})),
            ("Ejudge", "No available judge"),
        )

        self.judge_service.is_server_online.return_value = True
        subject = Subject({"reqtype": "submit"})
        with patch.object(
            submit_dispatcher, "dispatch", new=AsyncMock(return_value="dispatched")
        ) as dispatch:
            self.assertEqual(await method(subject), "dispatched")
        dispatch.assert_awaited_once_with(subject, "submit")

    async def test_submit_validation_and_service_error_branches(self):
        subject = Subject({"pro_id": "bad", "code": "x", "compiler_type": "3"})
        self.assertEqual(
            await BatchSubmitHandler.submit_code(subject),
            ("Eparam", "Invalid problem ID"),
        )

        subject = Subject({"pro_id": "5", "code": "x", "compiler_type": "bad"})
        self.assertEqual((await BatchSubmitHandler.submit_code(subject))[0], "Ecomp")

        contest = MagicMock(contest_id=9)
        contest.is_running.return_value = False
        contest.is_admin.return_value = False
        subject = Subject(
            {"pro_id": "5", "code": "x", "compiler_type": "3"}, contest
        )
        self.assertEqual((await BatchSubmitHandler.submit_code(subject))[0], "Eacces")

        contest.is_running.return_value = True
        contest.is_pro.return_value = False
        subject = Subject(
            {"pro_id": "5", "code": "x", "compiler_type": "3"}, contest
        )
        self.assertEqual((await BatchSubmitHandler.submit_code(subject))[0], "Enoext")

        subject = Subject({"pro_id": "5", "code": "x", "compiler_type": "3"})
        subject._is_allow_submit = AsyncMock()
        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            await BatchSubmitHandler.submit_code(subject), ("Enoext", "missing")
        )

        pro = problem()
        self.pro_service.get_pro.return_value = (None, pro)
        subject._is_allow_submit.return_value = ("Eempty", "empty")
        self.assertEqual(
            await BatchSubmitHandler.submit_code(subject), ("Eempty", "empty")
        )

        pro.allow_submit = False
        subject._is_allow_submit.return_value = None
        self.assertEqual((await BatchSubmitHandler.submit_code(subject))[0], "Eacces")

        pro.allow_submit = True
        self.chal_service.add_chal.return_value = (("Eunk", "add failed"), None)
        self.assertEqual((await BatchSubmitHandler.submit_code(subject))[0], "Eunk")

        self.chal_service.add_chal.return_value = (None, 77)
        self.user_service.update_acct.return_value = (("Eunk", "update failed"), None)
        self.assertEqual((await BatchSubmitHandler.submit_code(subject))[0], "Eunk")

        self.user_service.update_acct.return_value = (None, None)
        self.pro_service.get_pro.side_effect = [
            (None, pro),
            (("Enoext", "vanished"), None),
        ]
        self.assertEqual((await BatchSubmitHandler.submit_code(subject))[0], "Enoext")

        self.pro_service.get_pro.side_effect = [(None, pro), (None, pro)]
        self.chal_service.emit_chal.return_value = (("Ejudge", "emit failed"), None)
        self.assertEqual((await BatchSubmitHandler.submit_code(subject))[0], "Ejudge")

    async def test_submit_success_uses_contest_pretest_and_updates_state(self):
        contest = MagicMock(
            contest_id=9,
            enable_system_test=True,
        )
        contest.is_running.return_value = True
        contest.is_admin.return_value = False
        contest.is_pro.return_value = True
        subject = Subject(
            {"pro_id": "5", "code": "int main(){}", "compiler_type": "3"},
            contest,
        )
        subject._is_allow_submit = AsyncMock(return_value=None)
        pro = problem(status=ProConst.STATUS_ONLINE)
        self.pro_service.get_pro.side_effect = [(None, pro), (None, pro)]
        self.chal_service.add_chal.return_value = (None, 81)
        self.chal_service.emit_chal.return_value = (None, None)
        self.user_service.update_acct.return_value = (None, None)

        await BatchSubmitHandler.submit_code(subject)

        self.chal_service.add_chal.assert_awaited_once_with(
            5, 7, 9, Compiler.GPP, "int main(){}", ProType.BATCH
        )
        self.chal_service.emit_chal.assert_awaited_once()
        self.assertFalse(
            self.chal_service.emit_chal.await_args.kwargs["include_system_test"]
        )
        subject.rs.publish.assert_awaited_once_with("challist_sub", "1")
        subject.rs.hdel.assert_awaited_once_with("rate", "7")
        subject.error.assert_called_with(("S", 81))

    async def test_rejudge_validates_permissions_and_propagates_service_errors(self):
        subject = Subject({"chal_id": "bad"})
        self.assertEqual((await BatchSubmitHandler.rechal_submission(subject))[0], "Eparam")

        subject = Subject({"chal_id": "8"})
        self.assertEqual((await BatchSubmitHandler.rechal_submission(subject))[0], "Eunk")

        subject.acct.is_kernel.return_value = True
        self.chal_service.reset_chal.return_value = (("Eunk", "reset failed"), None)
        self.assertEqual(
            await BatchSubmitHandler.rechal_submission(subject),
            ("Eunk", "reset failed"),
        )

        self.chal_service.reset_chal.return_value = (None, None)
        self.chal_service.get_chal.return_value = (("Enoext", "gone"), None)
        self.assertEqual(
            await BatchSubmitHandler.rechal_submission(subject), ("Enoext", "gone")
        )

        chal = SimpleNamespace(pro_id=5, compiler_type=Compiler.GPP, acct_id=12)
        self.chal_service.get_chal.return_value = (None, chal)
        self.pro_service.get_pro.return_value = (("Enoext", "problem gone"), None)
        self.assertEqual(
            (await BatchSubmitHandler.rechal_submission(subject))[0], "Enoext"
        )

        pro = problem()
        self.pro_service.get_pro.side_effect = [
            (None, pro),
            (("Eacces", "full denied"), None),
        ]
        self.assertEqual(
            (await BatchSubmitHandler.rechal_submission(subject))[0], "Eacces"
        )

        self.pro_service.get_pro.side_effect = [(None, pro), (None, pro)]
        self.chal_service.emit_chal.return_value = (("Ejudge", "failed"), None)
        self.assertEqual(
            (await BatchSubmitHandler.rechal_submission(subject))[0], "Ejudge"
        )

    async def test_contest_rejudge_filters_system_tests_for_original_submitter(self):
        contest = MagicMock(contest_id=10, enable_system_test=True)
        contest.is_admin.side_effect = [True, False]
        subject = Subject({"chal_id": "9"}, contest)
        chal = SimpleNamespace(pro_id=5, compiler_type=Compiler.GPP, acct_id=12)
        pro = problem()
        self.chal_service.reset_chal.return_value = (None, None)
        self.chal_service.get_chal.return_value = (None, chal)
        self.pro_service.get_pro.side_effect = [(None, pro), (None, pro)]
        self.chal_service.emit_chal.return_value = (None, None)

        await BatchSubmitHandler.rechal_submission(subject)

        self.chal_service.emit_chal.assert_awaited_once()
        call = self.chal_service.emit_chal.await_args
        self.assertEqual(call.args[3], ChalConst.CONTEST_REJUDGE_PRI)
        self.assertFalse(call.kwargs["include_system_test"])
        subject.rs.hdel.assert_awaited_once_with("rate", "12")
        subject.error.assert_called_with(("S", 9))
    async def test_remaining_contest_lookup_admin_and_zero_cooldown_branches(self):
        get_subject = Subject({"pro_id": "5", "contest_id": "9"})
        get_problem = problem()
        get_problem.config.spec_config.allow_compilers = {
            Compiler.GPP,
            Compiler.PYTHON3,
        }
        self.pro_service.get_pro.return_value = (None, get_problem)
        contest_service = SimpleNamespace(
            get_contest=AsyncMock(
                return_value=(("Enoext", "missing"), None)
            )
        )
        with patch.object(
            ContestService, "inst", contest_service, create=True
        ):
            await original(BatchSubmitHandler.get)(get_subject)
        self.assertEqual(
            get_subject.render.await_args.kwargs["allow_compilers"],
            {Compiler.GPP, Compiler.PYTHON3},
        )

        admin_contest = MagicMock(
            contest_id=9,
            enable_system_test=True,
        )
        admin_contest.is_running.return_value = True
        admin_contest.is_pro.return_value = True
        admin_contest.is_admin.return_value = True
        submit_subject = Subject(
            {
                "pro_id": "5",
                "code": "int main(){}",
                "compiler_type": "3",
            },
            admin_contest,
        )
        submit_subject._is_allow_submit = AsyncMock(return_value=None)
        submit_problem = problem()
        self.pro_service.get_pro.side_effect = [
            (None, submit_problem),
            (None, submit_problem),
        ]
        self.chal_service.add_chal.return_value = (None, 90)
        self.chal_service.emit_chal.return_value = (None, None)
        self.user_service.update_acct.return_value = (None, None)

        await BatchSubmitHandler.submit_code(submit_subject)

        self.assertTrue(
            self.chal_service.emit_chal.await_args.kwargs[
                "include_system_test"
            ]
        )

        self.chal_service.emit_chal.reset_mock()
        rechal_subject = Subject({"chal_id": "91"}, admin_contest)
        challenge = SimpleNamespace(
            pro_id=5,
            compiler_type=Compiler.GPP,
            acct_id=12,
        )
        self.chal_service.reset_chal.return_value = (None, None)
        self.chal_service.get_chal.return_value = (None, challenge)
        self.pro_service.get_pro.side_effect = [
            (None, submit_problem),
            (None, submit_problem),
        ]

        await BatchSubmitHandler.rechal_submission(rechal_subject)

        self.assertTrue(
            self.chal_service.emit_chal.await_args.kwargs[
                "include_system_test"
            ]
        )

        zero_cd_contest = MagicMock(
            contest_id=22,
            submission_cd_time=0,
            allow_compilers={Compiler.GPP},
            contest_start=datetime.datetime(2025, 1, 1),
            contest_end=datetime.datetime(2025, 1, 1, 2),
        )
        zero_cd_contest.member_is_status.return_value = True
        cooldown_subject = Subject(contest=zero_cd_contest)
        cooldown_subject.rs.sismember.return_value = False
        cooldown_subject.rs.get.return_value = None

        self.assertIsNone(
            await BatchSubmitHandler._is_allow_submit(
                cooldown_subject,
                "new code",
                Compiler.GPP,
                problem(),
            )
        )
        self.assertFalse(
            any(
                call.args
                and str(call.args[0]).startswith("last_submit_time_")
                for call in cooldown_subject.rs.set.await_args_list
            )
        )
        cooldown_subject.rs.sadd.assert_awaited_once()
        cooldown_subject.rs.eval.assert_awaited_once()

    async def test_is_allow_submit_validation_cooldown_and_duplicate_branches(self):
        pro = problem()
        subject = Subject()

        self.assertEqual(
            (await BatchSubmitHandler._is_allow_submit(subject, "   ", Compiler.GPP, pro))[0],
            "Eempty",
        )
        self.assertEqual(
            (
                await BatchSubmitHandler._is_allow_submit(
                    subject, "x" * (ProConst.CODE_MAX + 1), Compiler.GPP, pro
                )
            )[0],
            "Ecodemax",
        )
        pro.config.spec_config.allow_compilers = {Compiler.PYTHON3}
        self.assertEqual(
            (await BatchSubmitHandler._is_allow_submit(subject, "x", Compiler.GPP, pro))[0],
            "Ecomp",
        )

        pro.config.spec_config.allow_compilers = {Compiler.GPP}
        subject.rs.get.return_value = None
        with patch("handlers.prospec.batch.submit.time.time", return_value=100):
            self.assertIsNone(
                await BatchSubmitHandler._is_allow_submit(subject, "x", Compiler.GPP, pro)
            )
        subject.rs.set.assert_awaited_with("last_submit_time_7", 100, ex=30)

        subject.rs.reset_mock()
        subject.rs.get.return_value = b"100"
        with patch("handlers.prospec.batch.submit.time.time", return_value=110):
            result = await BatchSubmitHandler._is_allow_submit(
                subject, "x", Compiler.GPP, pro
            )
        self.assertEqual(result[0], "Einternal")

        subject.rs.reset_mock()
        subject.rs.get.return_value = b"100"
        with patch("handlers.prospec.batch.submit.time.time", return_value=140):
            self.assertIsNone(
                await BatchSubmitHandler._is_allow_submit(subject, "x", Compiler.GPP, pro)
            )
        subject.rs.set.assert_awaited_with("last_submit_time_7", 140)

        contest = MagicMock(
            contest_id=22,
            submission_cd_time=5,
            allow_compilers={Compiler.GPP},
            contest_start=datetime.datetime(2025, 1, 1),
            contest_end=datetime.datetime(2025, 1, 1, 2),
        )
        contest.member_is_status.return_value = True
        subject = Subject(contest=contest)
        subject.rs.sismember.return_value = True
        self.assertEqual(
            (
                await BatchSubmitHandler._is_allow_submit(
                    subject, "contest code", Compiler.GPP, pro
                )
            )[0],
            "Esame",
        )

        subject.rs.sismember.return_value = False
        subject.rs.get.return_value = None
        self.assertIsNone(
            await BatchSubmitHandler._is_allow_submit(
                subject, "new contest code", Compiler.GPP, pro
            )
        )
        subject.rs.sadd.assert_awaited_once()
        subject.rs.expire.assert_awaited_once_with(
            subject.rs.sadd.await_args.args[0], time=datetime.timedelta(hours=2)
        )


if __name__ == "__main__":
    unittest.main()
