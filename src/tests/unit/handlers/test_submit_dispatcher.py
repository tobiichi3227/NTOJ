import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.submit import SubmitHandler, submit_dispatcher
from services.chal import ChalService
from services.judge import JudgeServerClusterService
from services.pro import ProConst, ProService, ProType
from services.prospec.batch import BatchProblemSpec
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
        self.finish = MagicMock()
        self.render = AsyncMock(return_value="rendered")
        self.acct = MagicMock(acct_id=7, acct_type=UserConst.ACCTTYPE_USER)
        self.acct.is_kernel.return_value = False
        self.application = MagicMock()
        self.request = MagicMock()
        self.db = MagicMock()
        self.rs = AsyncMock()

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


def problem(problem_type=ProType.BATCH, *, allow_submit=True):
    return SimpleNamespace(
        pro_id=5,
        name="Problem",
        allow_submit=allow_submit,
        problem_type=problem_type,
        config=SimpleNamespace(spec_config=BatchProblemSpec().get_default_config()),
    )


class FakeBatchSubmitHandler:
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.post = AsyncMock(return_value="batch-post")
        self.__class__.instances.append(self)


class TestSubmitHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pro_service = SimpleNamespace(get_pro=AsyncMock())
        self.chal_service = SimpleNamespace(get_chal=AsyncMock())
        self.judge_service = SimpleNamespace(is_server_online=MagicMock(return_value=True))
        for service, value in (
            (ProService, self.pro_service),
            (ChalService, self.chal_service),
            (JudgeServerClusterService, self.judge_service),
        ):
            active_patch = patch.object(service, "inst", value, create=True)
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def test_get_validation_permissions_availability_and_type_matrix(self):
        method = original(SubmitHandler.get)
        self.assertEqual((await method(Subject(), "bad"))[0], "Eparam")

        contest = MagicMock(contest_id=9, allow_compilers=set())
        contest.is_running.return_value = False
        contest.is_admin.return_value = False
        self.assertEqual((await method(Subject(contest=contest), "5"))[0], "Eacces")
        contest.is_running.return_value = True
        contest.is_pro.return_value = False
        self.assertEqual((await method(Subject(contest=contest), "5"))[0], "Enoext")

        subject = Subject()
        subject.acct.is_kernel.return_value = True
        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(await method(subject, "5"), ("Enoext", "missing"))
        self.pro_service.get_pro.assert_awaited_with(5, ProConst.PRO_STATUS_KERNEL_USER)

        self.pro_service.get_pro.return_value = (None, problem())
        self.judge_service.is_server_online.return_value = False
        subject = Subject()
        self.assertIsNone(await method(subject, "5"))
        subject.finish.assert_called_once()

        self.judge_service.is_server_online.return_value = True
        self.pro_service.get_pro.return_value = (None, problem(allow_submit=False))
        self.assertEqual((await method(Subject(), "5"))[0], "Eacces")

        for problem_type, expected in (
            (ProType.COMMUNICATION, "Enotsupport"),
            (ProType.TWOSTEP, "Enotsupport"),
            (ProType.OUTPUTONLY, "Enotsupport"),
            (999, "Eparam"),
        ):
            self.pro_service.get_pro.return_value = (None, problem(problem_type))
            self.assertEqual((await method(Subject(), "5"))[0], expected)

        contest.is_pro.return_value = True
        batch = problem()
        batch.config.spec_config.allow_compilers = {1, 3}
        contest.allow_compilers = {3}
        self.pro_service.get_pro.return_value = (None, batch)
        subject = Subject(contest=contest)
        await method(subject, "5")
        self.assertEqual(subject.render.await_args.kwargs["allow_compilers"], {3})
        self.assertEqual(subject.render.await_args.kwargs["contest_id"], 9)

    async def test_post_offline_and_dispatch(self):
        method = original(SubmitHandler.post)
        self.judge_service.is_server_online.return_value = False
        self.assertEqual((await method(Subject({"reqtype": "submit"})))[0], "Ejudge")
        self.judge_service.is_server_online.return_value = True
        subject = Subject({"reqtype": "submit"})
        with patch.object(
            submit_dispatcher, "dispatch", new=AsyncMock(return_value="dispatched")
        ) as dispatch:
            self.assertEqual(await method(subject), "dispatched")
        dispatch.assert_awaited_once_with(subject, "submit")

    async def test_problem_type_dispatch_matrix_and_batch_delegation(self):
        subject = Subject()
        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            await SubmitHandler._dispatch_to_problem_handler(subject, 5),
            ("Enoext", "missing"),
        )

        for problem_type, expected in (
            (ProType.COMMUNICATION, "Enotsupport"),
            (ProType.TWOSTEP, "Enotsupport"),
            (ProType.OUTPUTONLY, "Enotsupport"),
            (999, "Eparam"),
        ):
            self.pro_service.get_pro.return_value = (None, problem(problem_type))
            self.assertEqual(
                (await SubmitHandler._dispatch_to_problem_handler(subject, 5))[0],
                expected,
            )

        self.pro_service.get_pro.return_value = (None, problem())
        FakeBatchSubmitHandler.instances.clear()
        with patch(
            "handlers.prospec.batch.submit.BatchSubmitHandler", FakeBatchSubmitHandler
        ):
            self.assertEqual(
                await SubmitHandler._dispatch_to_problem_handler(subject, 5),
                "batch-post",
            )
        delegated = FakeBatchSubmitHandler.instances[-1]
        self.assertIs(delegated.acct, subject.acct)
        self.assertIsNone(delegated.contest)
        delegated.post.assert_awaited_once()

    async def test_submit_and_rejudge_actions_validate_and_forward_problem(self):
        subject = Subject({"pro_id": "bad"})
        subject._dispatch_to_problem_handler = AsyncMock()
        self.assertEqual((await SubmitHandler.submit_problem(subject))[0], "Eparam")
        subject.arguments["pro_id"] = "5"
        subject._dispatch_to_problem_handler.return_value = "forwarded"
        self.assertEqual(await SubmitHandler.submit_problem(subject), "forwarded")
        subject._dispatch_to_problem_handler.assert_awaited_with(5)

        subject = Subject({"chal_id": "bad"})
        subject._dispatch_to_problem_handler = AsyncMock()
        self.assertEqual((await SubmitHandler.rejudge_challenge(subject))[0], "Eparam")
        subject.arguments["chal_id"] = "8"
        self.chal_service.get_chal.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            await SubmitHandler.rejudge_challenge(subject), ("Enoext", "missing")
        )
        self.chal_service.get_chal.return_value = (None, SimpleNamespace(pro_id=5))
        subject._dispatch_to_problem_handler.return_value = "rejudge-forwarded"
        self.assertEqual(
            await SubmitHandler.rejudge_challenge(subject), "rejudge-forwarded"
        )
        subject._dispatch_to_problem_handler.assert_awaited_with(5)


if __name__ == "__main__":
    unittest.main()
