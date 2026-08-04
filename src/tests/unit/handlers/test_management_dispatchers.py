import inspect
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

test_config = sys.modules.setdefault("config", SimpleNamespace())
test_config.BASE_URL = "/"
test_config.SITE_TITLE = "NTOJ Test"
test_config.lock_user_list = []
test_config.can_see_code_user = []
test_config.unlock_pwd = b"expected"

from handlers.code import CodeHandler
from handlers.manage.judge import JudgeCntCallback, ManageJudgeHandler
from handlers.manage.pro.filemanager import ManageProFilemanagerHandler
from handlers.manage.pro.judge_dispatcher import ManageProJudgeHandler
from handlers.manage.pro.testdata_dispatcher import ManageProTestdataHandler
from services.chal import ChalService
from services.judge import JudgeServerClusterService
from services.pro import ProConst, ProService, ProType
from services.user import UserConst


def original(function):
    """Walk the project's reqenv/permission closures to the business method."""
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
    def __init__(self, arguments=None):
        self.arguments = arguments or {}
        self.error = MagicMock(side_effect=lambda value: value)
        self.render = AsyncMock(return_value="rendered")
        self.add_log = AsyncMock(return_value=(None, 1))
        self.rs = AsyncMock()
        self.db = MagicMock()
        self.application = MagicMock()
        self.request = MagicMock()
        self.acct = MagicMock(acct_id=1, acct_type=UserConst.ACCTTYPE_KERNEL, name="admin")

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


class FakeDelegatedHandler:
    calls = []

    def __init__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.acct = None
        self._transforms = None

    async def get(self):
        return "delegated-get"

    async def post(self):
        return "delegated-post"


class TestSimpleManagementCallbacks(unittest.IsolatedAsyncioTestCase):
    async def test_judge_count_callback_forwards_and_has_no_lifecycle_state(self):
        callback = JudgeCntCallback()
        connection = object()
        self.assertIsNone(await callback.register(connection))
        self.assertEqual(await callback.message(connection, "7"), "7")
        self.assertIsNone(await callback.unregister(connection))


class TestProblemTypeDispatchers(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pro_service = SimpleNamespace(get_pro=AsyncMock())
        self.pro_patch = patch.object(ProService, "inst", self.pro_service, create=True)
        self.pro_patch.start()
        self.addCleanup(self.pro_patch.stop)

    async def assert_get_matrix(self, handler_type, batch_patch):
        method = original(handler_type.get)
        subject = Subject({"proid": "bad"})
        self.assertEqual(await method(subject), ("Eparam", "Invalid problem ID"))

        subject = Subject({"proid": "9"})
        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(await method(subject), ("Enoext", "missing"))

        responses = {
            ProType.COMMUNICATION: "Enotsupport",
            ProType.TWOSTEP: "Enotsupport",
            ProType.OUTPUTONLY: "Enotsupport",
            999: "Eparam",
        }
        if handler_type is ManageProFilemanagerHandler:
            responses[999] = "Enotsupport"
        for problem_type, status in responses.items():
            with self.subTest(handler=handler_type.__name__, problem_type=problem_type):
                subject = Subject({"proid": "9"})
                self.pro_service.get_pro.return_value = (
                    None,
                    SimpleNamespace(problem_type=problem_type),
                )
                result = await method(subject)
                self.assertEqual(result[0], status)

        subject = Subject({"proid": "9"})
        pro = SimpleNamespace(problem_type=ProType.BATCH)
        self.pro_service.get_pro.return_value = (None, pro)
        if handler_type is ManageProJudgeHandler:
            self.assertIsNone(await method(subject))
            subject.render.assert_awaited_once()
        else:
            FakeDelegatedHandler.calls.clear()
            with patch(batch_patch, FakeDelegatedHandler):
                self.assertEqual(await method(subject), "delegated-get")
            self.assertIs(FakeDelegatedHandler.calls[-1][1]["db"], subject.db)

    async def assert_post_matrix(self, handler_type, batch_patch):
        method = original(handler_type.post)
        subject = Subject({"pro_id": "bad"})
        self.assertEqual(await method(subject), ("Eparam", "Invalid problem ID"))

        subject = Subject({"pro_id": "9"})
        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(await method(subject), ("Enoext", "missing"))

        responses = {
            ProType.COMMUNICATION: "Enotsupport",
            ProType.TWOSTEP: "Enotsupport",
            ProType.OUTPUTONLY: "Enotsupport",
            999: "Eparam",
        }
        if handler_type is ManageProFilemanagerHandler:
            responses = {999: "Enotsupport"}
        for problem_type, status in responses.items():
            with self.subTest(handler=handler_type.__name__, problem_type=problem_type):
                subject = Subject({"pro_id": "9"})
                self.pro_service.get_pro.return_value = (
                    None,
                    SimpleNamespace(problem_type=problem_type),
                )
                result = await method(subject)
                self.assertEqual(result[0], status)

        subject = Subject({"pro_id": "9"})
        self.pro_service.get_pro.return_value = (
            None,
            SimpleNamespace(problem_type=ProType.BATCH),
        )
        FakeDelegatedHandler.calls.clear()
        with patch(batch_patch, FakeDelegatedHandler):
            self.assertEqual(await method(subject), "delegated-post")
        self.assertIs(FakeDelegatedHandler.calls[-1][1]["rs"], subject.rs)

    async def test_judge_dispatcher_problem_type_matrix(self):
        await self.assert_get_matrix(
            ManageProJudgeHandler,
            "handlers.prospec.batch.judge.BatchJudgeHandler",
        )
        await self.assert_post_matrix(
            ManageProJudgeHandler,
            "handlers.prospec.batch.judge.BatchJudgeHandler",
        )

    async def test_testdata_dispatcher_problem_type_matrix(self):
        await self.assert_get_matrix(
            ManageProTestdataHandler,
            "handlers.prospec.batch.testdata.BatchTestdataHandler",
        )
        await self.assert_post_matrix(
            ManageProTestdataHandler,
            "handlers.prospec.batch.testdata.BatchTestdataHandler",
        )

    async def test_filemanager_get_and_supported_batch_post(self):
        await self.assert_get_matrix(
            ManageProFilemanagerHandler,
            "handlers.prospec.batch.filemanager.BatchFilemanagerHandler",
        )
        await self.assert_post_matrix(
            ManageProFilemanagerHandler,
            "handlers.prospec.batch.filemanager.BatchFilemanagerHandler",
        )


class TestCodeDispatcher(unittest.IsolatedAsyncioTestCase):
    async def test_code_validation_permissions_and_problem_type_matrix(self):
        method = original(CodeHandler.post)
        chal_service = SimpleNamespace(get_chal=AsyncMock())
        pro_service = SimpleNamespace(get_pro=AsyncMock())
        with (
            patch.object(ChalService, "inst", chal_service, create=True),
            patch.object(ProService, "inst", pro_service, create=True),
        ):
            subject = Subject({"chal_id": "bad"})
            self.assertEqual(await method(subject), ("Eparam", "Invalid challenge id"))

            subject = Subject({"chal_id": "7"})
            chal_service.get_chal.return_value = (("Enoext", "missing"), None)
            self.assertEqual(await method(subject), ("Enoext", "missing"))

            for contest_id, is_kernel, expected_statuses in (
                (4, False, ProConst.PRO_STATUS_CONTEST_USER),
                (0, True, ProConst.PRO_STATUS_KERNEL_USER),
                (0, False, ProConst.PRO_STATUS_NORMAL_USER),
            ):
                subject = Subject({"chal_id": "7"})
                subject.acct.is_kernel.return_value = is_kernel
                chal_service.get_chal.return_value = (
                    None,
                    SimpleNamespace(pro_id=9, contest_id=contest_id),
                )
                pro_service.get_pro.return_value = (("Eacces", "hidden"), None)
                self.assertEqual(await method(subject), ("Eacces", "hidden"))
                pro_service.get_pro.assert_awaited_with(9, expected_statuses)

            for problem_type, status in (
                (ProType.COMMUNICATION, "Enotsupport"),
                (ProType.TWOSTEP, "Enotsupport"),
                (ProType.OUTPUTONLY, "Enotsupport"),
                (999, "Eparam"),
            ):
                subject = Subject({"chal_id": "7"})
                subject.acct.is_kernel.return_value = False
                chal_service.get_chal.return_value = (
                    None,
                    SimpleNamespace(pro_id=9, contest_id=0),
                )
                pro_service.get_pro.return_value = (
                    None,
                    SimpleNamespace(problem_type=problem_type),
                )
                self.assertEqual((await method(subject))[0], status)

            subject = Subject({"chal_id": "7"})
            subject.acct.is_kernel.return_value = False
            chal_service.get_chal.return_value = (
                None,
                SimpleNamespace(pro_id=9, contest_id=0),
            )
            pro_service.get_pro.return_value = (
                None,
                SimpleNamespace(problem_type=ProType.BATCH),
            )
            with patch(
                "handlers.prospec.batch.code.BatchCodeHandler",
                FakeDelegatedHandler,
            ):
                self.assertEqual(await method(subject), "delegated-post")


class TestManageJudgeActions(unittest.IsolatedAsyncioTestCase):
    async def test_connect_and_disconnect_validation_and_service_errors(self):
        judge = SimpleNamespace(
            get_server_status=MagicMock(),
            connect_server=AsyncMock(),
            disconnect_server=AsyncMock(),
        )
        with patch.object(JudgeServerClusterService, "inst", judge, create=True):
            subject = Subject({"index": "bad"})
            self.assertEqual(
                await ManageJudgeHandler.connect_judge(subject),
                ("Eparam", "Invalid index"),
            )

            subject = Subject({"index": "9"})
            judge.get_server_status.return_value = (("Eparam", "bad index"), None)
            self.assertEqual(
                await ManageJudgeHandler.connect_judge(subject),
                ("Eparam", "bad index"),
            )

            judge.get_server_status.return_value = (None, {"name": ""})
            judge.connect_server.return_value = ("Ejudge", "offline")
            self.assertEqual(
                await ManageJudgeHandler.connect_judge(subject),
                ("Ejudge", "offline"),
            )
            subject.add_log.assert_awaited()

            judge.connect_server.return_value = None
            self.assertIsNone(await ManageJudgeHandler.connect_judge(subject))
            subject.error.assert_called_with(("S", ""))

            subject = Subject({"index": "bad", "pwd": "x"})
            self.assertEqual(
                await ManageJudgeHandler.disconnect_judge(subject),
                ("Eparam", "Invalid index"),
            )

            subject = Subject({"index": "9", "pwd": "x"})
            judge.get_server_status.return_value = (("Eparam", "bad index"), None)
            self.assertEqual(
                await ManageJudgeHandler.disconnect_judge(subject),
                ("Eparam", "bad index"),
            )

            judge.get_server_status.return_value = (None, {"name": "judge"})
            self.assertEqual(
                (await ManageJudgeHandler.disconnect_judge(subject))[0],
                "Eacces",
            )

