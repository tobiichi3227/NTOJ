import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

from services.chal import ChalConst, ChalService, Compiler
from services.filemanager import FileManager
from services.judge import JudgeServerClusterService
from services.pack import PackService
from services.pro import (
    CheckerType,
    Limit,
    ProblemConfig,
    ProService,
    SubtaskConfig,
)
from services.prospec.batch import BatchProblemSpec, BatchTestdata


def fake_database():
    connection = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=None)
    transaction.__aexit__ = AsyncMock(return_value=None)
    connection.transaction = MagicMock(return_value=transaction)
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=connection)
    acquire.__aexit__ = AsyncMock(return_value=None)
    database = MagicMock()
    database.acquire = MagicMock(return_value=acquire)
    return database, connection


def batch_config_for_pretest():
    normal = BatchTestdata(1, {}, "1.in", "1.out")
    tagged = BatchTestdata(2, {"tags": ["system-test"]}, "2.in", "2.out")
    system = BatchTestdata(3, {}, "3.in", "3.out")
    cascaded = BatchTestdata(4, {}, "4.in", "4.out")
    subtasks = {
        0: SubtaskConfig(0, [normal, tagged], {1}, 30),
        1: SubtaskConfig(
            1, [system], set(), 30, metadata={"tags": ["system-test"]}
        ),
        2: SubtaskConfig(2, [tagged], set(), 20),
        3: SubtaskConfig(3, [cascaded], {0}, 20),
    }
    spec = BatchProblemSpec().get_default_config()
    return ProblemConfig(
        limits={"default": Limit(1000, 262144, 65536)},
        subtask_configs=subtasks,
        testdatas={1: normal, 2: tagged, 3: system, 4: cascaded},
        rate_precision=0,
        spec_config=spec,
    )


class TestBatchProblemSpec(unittest.IsolatedAsyncioTestCase):
    async def test_emit_pretest_removes_system_and_transitively_invalid_subtasks(self):
        spec = BatchProblemSpec()
        database, connection = fake_database()
        redis = AsyncMock()
        chal_service = SimpleNamespace(
            update_subtask_result=AsyncMock(),
            update_testdata_result=AsyncMock(),
            update_total_result=AsyncMock(),
        )
        judge_service = SimpleNamespace(send=AsyncMock())

        with (
            patch.object(ChalService, "inst", chal_service, create=True),
            patch.object(
                JudgeServerClusterService, "inst", judge_service, create=True
            ),
            patch("services.prospec.batch.os.path.isfile", return_value=True),
        ):
            result = await spec.emit_chal(
                database,
                redis,
                chal_id=40,
                pro_id=5,
                acct_id=7,
                contest_id=9,
                compiler_type=Compiler.GPP,
                config=batch_config_for_pretest(),
                priority=ChalConst.CONTEST_PRI,
                include_system_test=False,
            )

        self.assertEqual(result, (None, None))
        payload = judge_service.send.await_args.args[0]
        self.assertEqual(payload["subtasks"], [])
        self.assertEqual(payload["testdatas"], [])
        self.assertEqual(payload["limit"]["time"], 1_000_000_000)
        self.assertEqual(payload["limit"]["memory"], 268_435_456)
        self.assertEqual(payload["limit"]["output"], 67_108_864)
        judged_update = connection.execute.await_args_list[-1]
        self.assertEqual(judged_update.args[3], [])
        updated_subtasks = [
            call.args[1] for call in chal_service.update_subtask_result.await_args_list
        ]
        self.assertTrue(any(item.subtask_id == 1 for item in updated_subtasks))
        self.assertTrue(any(item.subtask_id == 2 for item in updated_subtasks))
        self.assertTrue(any(item.subtask_id == 0 for item in updated_subtasks))
        self.assertTrue(any(item.subtask_id == 3 for item in updated_subtasks))
        redis.hdel.assert_awaited_once_with("rate", "7")

    async def test_emit_returns_unknown_error_when_result_update_fails(self):
        spec = BatchProblemSpec()
        database, _ = fake_database()
        database.acquire.return_value.__aenter__.side_effect = RuntimeError("db down")

        result = await spec.emit_chal(
            database,
            AsyncMock(),
            chal_id=41,
            pro_id=5,
            acct_id=7,
            contest_id=0,
            compiler_type=Compiler.GPP,
            config=batch_config_for_pretest(),
            priority=ChalConst.NORMAL_PRI,
        )

        self.assertEqual(result, (("Eunk", "Unknown error"), None))

    async def test_add_challenge_handles_directory_and_file_failures(self):
        spec = BatchProblemSpec()
        database, connection = fake_database()
        connection.fetch.return_value = [{"chal_id": 51}]
        config = batch_config_for_pretest()

        for exception in (FileExistsError("exists"), OSError("mkdir failed")):
            with self.subTest(exception=type(exception).__name__), patch(
                "services.prospec.batch.os.mkdir", side_effect=exception
            ):
                result = await spec.add_chal(
                    database, AsyncMock(), 5, 7, 0, Compiler.GPP, "code", config
                )
                self.assertEqual(result, (("Eunk", "Unknown error"), None))

        with (
            patch("services.prospec.batch.os.mkdir"),
            patch("builtins.open", side_effect=OSError("write failed")),
            patch("services.prospec.batch.os.rmdir") as remove_directory,
        ):
            result = await spec.add_chal(
                database, AsyncMock(), 5, 7, 0, Compiler.GPP, "code", config
            )
        self.assertEqual(result, (("Eunk", "Unknown error"), None))
        remove_directory.assert_called_once_with("code/51")

        with (
            patch("services.prospec.batch.os.mkdir"),
            patch("builtins.open", side_effect=OSError("write failed")),
            patch(
                "services.prospec.batch.os.rmdir", side_effect=OSError("cleanup failed")
            ),
        ):
            result = await spec.add_chal(
                database, AsyncMock(), 5, 7, 0, Compiler.GPP, "code", config
            )
        self.assertEqual(result[0][0], "Eunk")

    async def test_unpack_validates_package_and_config_variants(self):
        spec = BatchProblemSpec()
        pack_service = SimpleNamespace(
            unpack=AsyncMock(return_value=(None, None)), clear=AsyncMock()
        )
        pro_service = SimpleNamespace(update_pro_config=AsyncMock())
        redis = AsyncMock()
        base = {
            "metadata": "",
            "check": "diff",
            "test": [{"data": ["one"], "weight": 100}],
        }

        async def unpack(conf=None, *, load_error=None, chmod_error=None):
            opener = mock_open(read_data=json.dumps(conf or {}))
            with (
                patch.object(PackService, "inst", pack_service, create=True),
                patch.object(ProService, "inst", pro_service, create=True),
                patch("builtins.open", opener),
                patch(
                    "services.prospec.batch.os.chmod",
                    side_effect=chmod_error,
                ),
                patch("services.prospec.batch.os.path.exists", return_value=False),
            ):
                if load_error is not None:
                    with patch("json.load", side_effect=load_error):
                        return await spec.unpack_pro(MagicMock(), redis, 6, "token")
                return await spec.unpack_pro(MagicMock(), redis, 6, "token")

        pack_service.unpack.return_value = (("Epack", "bad archive"), None)
        self.assertEqual((await unpack(base))[0][0], "Epack")
        pack_service.unpack.return_value = (None, None)

        decode_error = json.JSONDecodeError("bad", "x", 0)
        self.assertEqual((await unpack(base, load_error=decode_error))[0][0], "Econf")

        missing_limit = dict(base)
        self.assertEqual((await unpack(missing_limit))[0][0], "Econf")

        invalid_global = dict(base, timelimit="bad", memlimit="1")
        self.assertEqual((await unpack(invalid_global))[0][0], "Econf")

        missing_default = dict(
            base,
            limit={
                "g++": {"timelimit": "bad", "memlimit": "1024"},
                "unknown": {"time": "1", "memory": "1", "output": "1"},
                "clang++": {"unexpected": "shape"},
            },
        )
        self.assertEqual((await unpack(missing_default))[0][0], "Econf")

        modern_invalid = dict(
            base,
            limit={"default": {"time": "bad", "memory": "1", "output": "1"}},
        )
        self.assertEqual((await unpack(modern_invalid))[0][0], "Econf")

        successful = dict(
            base,
            compile="makefile",
            limit={
                "default": {"time": "1000", "memory": "262144", "output": "64"},
                "g++": {"timelimit": "2000", "memlimit": "524288"},
            },
            test=[
                {"data": ["../one", "one"], "weight": 40},
                {"data": ["two"], "weight": 60},
            ],
        )
        self.assertEqual(await unpack(successful), (None, None))
        config = pro_service.update_pro_config.await_args.args[2]
        self.assertTrue(config.spec_config.has_grader)
        self.assertEqual(
            config.spec_config.allow_compilers, {int(Compiler.CLANGPP), int(Compiler.GPP)}
        )
        self.assertEqual(len(config.testdatas), 2)
        self.assertEqual(config.limits["default"].output, 64)
        redis.delete.assert_awaited_with("prolist")

        legacy = dict(base, has_grader=False, timelimit="500", memlimit="1024")
        self.assertEqual(
            await unpack(legacy, chmod_error=FileExistsError("exists")),
            (None, None),
        )
        self.assertFalse(pro_service.update_pro_config.await_args.args[2].spec_config.has_grader)
        pack_service.clear.assert_awaited()

    async def test_allowed_paths_and_file_structure_deduplicate_graders(self):
        spec = BatchProblemSpec()
        config = spec.get_default_config()
        config.has_grader = True
        config.allow_compilers = {Compiler.GPP, Compiler.CLANGPP, Compiler.GCC}
        config.checker_type = CheckerType.CMS_TPS_TESTLIB

        def exists(path):
            return path.endswith("/cpp")

        allowed = None
        with patch("services.prospec.batch.os.path.exists", side_effect=exists):
            allowed = spec.get_allowed_file_paths(config, 8)
        self.assertEqual(allowed.count("res/grader/cpp"), 1)
        self.assertNotIn("res/grader/c", allowed)

        class FakeFileManager:
            def __init__(self, path):
                self.path = path

            def listdir(self, only_files=False):
                self.only_files = only_files
                return ["10.txt", "2.txt"]

        with (
            patch("services.prospec.batch.os.path.exists", side_effect=exists),
            patch("services.filemanager.FileManager", FakeFileManager),
        ):
            structure = spec.get_file_structure(config, 8)
        self.assertEqual(
            [entry["path"] for entry in structure],
            ["res/grader/cpp", "res/grader", "res/checker", "http"],
        )
        self.assertEqual(structure[0]["files"], ["2.txt", "10.txt"])

        config.has_grader = False
        config.checker_type = CheckerType.DIFF
        with patch("services.filemanager.FileManager", FakeFileManager):
            self.assertEqual(
                [entry["path"] for entry in spec.get_file_structure(config, 8)],
                ["http"],
            )


if __name__ == "__main__":
    unittest.main()
