import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from msgpack import packb

from handlers.manage.judge import ManageJudgeHandler
from handlers.manage.pro.add import ManageProAddHandler
from handlers.manage.pro.limit import ManageProLimitHandler
from handlers.manage.pro.updategeneral import ManageProUpdateGeneralHandler
from services.chal import Compiler
from services.judge import JudgeServerClusterService
from services.pro import ProService
from services.prospec.batch import batch_spec
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Subject,
    original,
)


class TestProblemManagementEdges(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.problems = SimpleNamespace(
            get_pro=AsyncMock(),
            update_pro=AsyncMock(),
            unpack_pro=AsyncMock(),
            add_pro=AsyncMock(),
            update_pro_config=AsyncMock(),
        )
        active = patch.object(
            ProService, "inst", self.problems, create=True
        )
        active.start()
        self.addCleanup(active.stop)

    async def test_add_page_service_failure_and_unpack_failure(self):
        subject = Subject()
        await original(ManageProAddHandler.get)(subject)
        subject.render.assert_awaited_once()

        self.problems.add_pro.return_value = (
            ("Edb", "failed"),
            41,
        )
        result = await ManageProAddHandler.add_pro(
            Subject(
                arguments={
                    "name": "Problem",
                    "status": "1",
                    "mode": "create",
                }
            )
        )
        self.assertEqual(result[0], "Edb")

        self.problems.add_pro.return_value = (None, 42)
        self.problems.unpack_pro.return_value = (
            ("Epack", "invalid"),
            None,
        )
        result = await ManageProAddHandler.add_pro(
            Subject(
                arguments={
                    "name": "Problem",
                    "status": "1",
                    "mode": "upload",
                    "pack_token": "token",
                }
            )
        )
        self.assertEqual(result[0], "Epack")

    async def test_update_general_update_service_failure(self):
        problem = SimpleNamespace(
            name="old",
            status=0,
            tags="",
            allow_submit=False,
        )
        self.problems.get_pro.return_value = (None, problem)
        self.problems.update_pro.return_value = (
            ("Edb", "failed"),
            None,
        )
        result = await ManageProUpdateGeneralHandler.update_general(
            Subject(
                arguments={
                    "pro_id": "1",
                    "status": "1",
                    "name": "new",
                    "tags": "tag",
                    "allow_submit": "true",
                }
            )
        )
        self.assertEqual(result[0], "Edb")
        self.assertTrue(problem.allow_submit)

    async def test_upload_package_unpack_failure_and_symlink_warning(self):
        self.problems.get_pro.return_value = (
            None,
            SimpleNamespace(),
        )
        self.problems.unpack_pro.return_value = (
            ("Epack", "invalid"),
            None,
        )
        result = await ManageProUpdateGeneralHandler.upload_package(
            Subject(
                arguments={"pro_id": "1", "pack_token": "bad"}
            )
        )
        self.assertEqual(result[0], "Epack")

        self.problems.unpack_pro.return_value = (None, None)
        subject = Subject(
            arguments={"pro_id": "1", "pack_token": "good"}
        )
        import handlers.manage.pro.updategeneral as module

        with (
            patch.object(
                module.os, "listdir", return_value=["link", "plain"]
            ),
            patch.object(
                module.os.path,
                "islink",
                side_effect=lambda name: name == "link",
            ),
            patch.object(
                module.os.path,
                "realpath",
                return_value="/outside/link",
            ),
        ):
            await ManageProUpdateGeneralHandler.upload_package(subject)
        self.assertEqual(subject.add_log.await_count, 2)
        self.assertEqual(subject.error.call_args.args[0], ("S", ""))

    async def test_limit_skips_invalid_and_disallowed_compilers(self):
        config = SimpleNamespace(
            spec_config=batch_spec.get_default_config(),
            limits={},
        )
        config.spec_config.allow_compilers = {Compiler.GPP}
        problem = SimpleNamespace(
            config=config,
            problem_type="batch",
        )
        self.problems.get_pro.return_value = (None, problem)

        limits = {
            "default": {"time": "1", "memory": "2", "output": "3"},
            "not-a-number": {
                "time": "1",
                "memory": "2",
                "output": "3",
            },
            str(Compiler.GCC.value): {
                "time": "1",
                "memory": "2",
                "output": "3",
            },
            str(Compiler.GPP.value): {
                "time": "4",
                "memory": "5",
                "output": "6",
            },
        }
        subject = Subject(
            arguments={
                "pro_id": "1",
                "limits": json.dumps(limits),
            }
        )
        result = await ManageProLimitHandler.update_limit_action(subject)
        self.assertEqual(result, ("S", ""))
        self.assertIn("default", problem.config.limits)
        self.assertIn(Compiler.GPP, problem.config.limits)
        self.assertNotIn(Compiler.GCC, problem.config.limits)
        self.problems.update_pro_config.assert_awaited_once()


class TestJudgeManagementEdges(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.judges = SimpleNamespace(
            get_server_status=MagicMock(),
            connect_server=AsyncMock(),
            disconnect_server=AsyncMock(),
        )
        active = patch.object(
            JudgeServerClusterService,
            "inst",
            self.judges,
            create=True,
        )
        active.start()
        self.addCleanup(active.stop)

    async def test_connect_named_server_failure(self):
        self.judges.get_server_status.return_value = (
            None,
            {"name": "primary"},
        )
        self.judges.connect_server.return_value = (
            "Ejudge",
            "offline",
        )
        result = await ManageJudgeHandler.connect_judge(
            Subject(arguments={"index": "1"})
        )
        self.assertEqual(result[0], "Ejudge")

    async def test_disconnect_unnamed_server_success(self):
        self.judges.get_server_status.return_value = (
            None,
            {"name": ""},
        )
        self.judges.disconnect_server.return_value = None
        subject = Subject(
            arguments={"index": "2", "pwd": "secret"}
        )
        import handlers.manage.judge as module

        encoded = base64.b64encode(packb("secret"))
        with patch.object(module.config, "unlock_pwd", encoded):
            await ManageJudgeHandler.disconnect_judge(subject)
        self.judges.disconnect_server.assert_awaited_once_with(2)
        subject.add_log.assert_awaited_once()
        subject.error.assert_called_with(("S", ""))


if __name__ == "__main__":
    unittest.main()
