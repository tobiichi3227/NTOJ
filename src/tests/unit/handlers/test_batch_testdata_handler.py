import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

from handlers.prospec.batch.testdata import (
    BatchTestdataHandler,
    batch_testdata_dispatcher,
)
from services.pack import PackService
from services.pro import ProService, ProType, SubtaskConfig
from services.prospec.batch import BatchTestdata
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
    def __init__(self, arguments=None):
        self.arguments = arguments or {}
        self.error = MagicMock(side_effect=lambda value: value)
        self.render = AsyncMock(return_value="rendered")
        self.add_log = AsyncMock(return_value=(None, 1))
        self.set_header = MagicMock()
        self.write = MagicMock()
        self.finish = MagicMock()
        self.acct = MagicMock(
            acct_id=1, acct_type=UserConst.ACCTTYPE_KERNEL, name="admin"
        )

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


def problem(*, with_testdata=True):
    first = BatchTestdata(0, inputfile="case.in", outputfile="case.out")
    second = BatchTestdata(1, inputfile="other.in", outputfile="other.out")
    testdatas = {0: first, 1: second} if with_testdata else {}
    subtasks = {
        0: SubtaskConfig(0, [first] if with_testdata else [], set(), 50),
        1: SubtaskConfig(1, [second] if with_testdata else [], set(), 50),
    }
    return SimpleNamespace(
        problem_type=ProType.BATCH,
        config=SimpleNamespace(testdatas=testdatas, subtask_configs=subtasks),
    )


class TestBatchTestdataHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pro = problem()
        self.pro_service = SimpleNamespace(
            get_pro=AsyncMock(return_value=(None, self.pro)),
            update_pro_config=AsyncMock(return_value=(None, None)),
        )
        self.pack_service = SimpleNamespace(clear=AsyncMock(return_value=(None, None)))
        for service, value in (
            (ProService, self.pro_service),
            (PackService, self.pack_service),
        ):
            service_patch = patch.object(service, "inst", value, create=True)
            service_patch.start()
            self.addCleanup(service_patch.stop)

    async def test_get_validation_service_render_and_download_errors(self):
        method = original(BatchTestdataHandler.get)
        self.assertEqual((await method(Subject({"proid": "bad"})))[0], "Eparam")

        self.pro_service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(Subject({"proid": "5"})), ("Edb", "failed"))
        self.pro_service.get_pro.return_value = (None, self.pro)

        subject = Subject({"proid": "5"})
        await method(subject)
        subject.render.assert_awaited_once()

        invalid_type = Subject(
            {"proid": "5", "download": "1", "type": "meta", "testdata_id": "0"}
        )
        self.assertEqual((await method(invalid_type))[0], "Eparam")

        missing = Subject(
            {"proid": "5", "download": "1", "type": "input", "testdata_id": "9"}
        )
        self.assertIsNone(await method(missing))
        missing.error.assert_called_with(("Enoext", "Testdata not found"))

        absent_file = Subject(
            {"proid": "5", "download": "1", "type": "output", "testdata_id": "0"}
        )
        with patch("handlers.prospec.batch.testdata.os.path.exists", return_value=False):
            self.assertEqual((await method(absent_file))[0], "Enoext")

    async def test_get_download_streams_bytes_and_handles_read_failure(self):
        method = original(BatchTestdataHandler.get)
        arguments = {
            "proid": "5",
            "download": "1",
            "type": "input",
            "testdata_id": "0",
        }
        subject = Subject(arguments)
        opened = MagicMock()
        opened.__enter__.return_value.read.side_effect = [b"abc", b""]
        with (
            patch("handlers.prospec.batch.testdata.os.path.exists", return_value=True),
            patch("builtins.open", return_value=opened),
        ):
            await method(subject)
        subject.write.assert_called_once_with(b"abc")
        subject.finish.assert_called_once()
        self.assertEqual(subject.set_header.call_count, 2)

        subject = Subject(arguments)
        opened = MagicMock()
        opened.__enter__.return_value.read.side_effect = OSError("read")
        with (
            patch("handlers.prospec.batch.testdata.os.path.exists", return_value=True),
            patch("builtins.open", return_value=opened),
        ):
            await method(subject)
        subject.error.assert_called_with(("Eunk", "Unknown error"))

    async def test_preview_validation_missing_file_size_and_escaped_success(self):
        method = BatchTestdataHandler.preview_action
        for arguments in (
            {"pro_id": "bad", "testdata_id": "0", "type": "input"},
            {"pro_id": "5", "testdata_id": "bad", "type": "input"},
            {"pro_id": "5", "testdata_id": "0", "type": "meta"},
        ):
            self.assertEqual((await method(Subject(arguments)))[0], "Eparam")

        valid = {"pro_id": "5", "testdata_id": "0", "type": "input"}
        self.pro_service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(Subject(valid)), ("Edb", "failed"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual(
            (await method(Subject({**valid, "testdata_id": "9"})))[0], "Enoext"
        )

        subject = Subject(valid)
        with patch("handlers.prospec.batch.testdata.os.path.exists", return_value=False):
            self.assertEqual((await method(subject))[0], "Enoext")
        subject.add_log.assert_awaited_once()

        opened = mock_open()
        opened.return_value.readlines.return_value = ["x\n"] * 26
        with (
            patch("handlers.prospec.batch.testdata.os.path.exists", return_value=True),
            patch("builtins.open", opened),
        ):
            self.assertEqual((await method(Subject(valid)))[0], "Efile")

        opened = mock_open()
        opened.return_value.readlines.return_value = ["<tag>&\n"]
        with (
            patch("handlers.prospec.batch.testdata.os.path.exists", return_value=True),
            patch("builtins.open", opened),
        ):
            result = await method(Subject({**valid, "type": "output"}))
        self.assertEqual(result, ("S", "&lt;tag&gt;&amp;\n"))

    async def test_update_file_validation_cleanup_failure_and_both_file_types(self):
        method = BatchTestdataHandler.update_single_file_action
        for arguments in (
            {"pro_id": "bad", "testdata_id": "0", "type": "input", "pack_token": "p"},
            {"pro_id": "5", "testdata_id": "bad", "type": "input", "pack_token": "p"},
            {"pro_id": "5", "testdata_id": "0", "type": "meta", "pack_token": "p"},
        ):
            self.assertEqual((await method(Subject(arguments)))[0], "Eparam")

        valid = {"pro_id": "5", "testdata_id": "0", "type": "input", "pack_token": "p"}
        self.pro_service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(Subject(valid)), ("Edb", "failed"))
        self.pro_service.get_pro.return_value = (None, self.pro)

        missing = Subject({**valid, "testdata_id": "9"})
        self.assertEqual((await method(missing))[0], "Enoext")
        self.pack_service.clear.assert_awaited_with("p")

        manager = MagicMock()
        manager.update_from_pack = AsyncMock(return_value=(("Eio", "failed"), None))
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            subject = Subject(valid)
            self.assertEqual(await method(subject), ("Eio", "failed"))
        subject.add_log.assert_awaited_once()

        for file_type, expected_name in (("input", "case.in"), ("output", "case.out")):
            manager = MagicMock()
            manager.update_from_pack = AsyncMock(return_value=(None, None))
            with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
                self.assertEqual(
                    await method(Subject({**valid, "type": file_type})), ("S", "")
                )
            manager.update_from_pack.assert_awaited_once_with(expected_name, "p")

    async def test_add_file_empty_input_error_output_error_and_success(self):
        method = BatchTestdataHandler.add_single_file_action
        invalid = {
            "pro_id": "bad",
            "filename": "new",
            "input_pack_token": "in",
            "output_pack_token": "out",
        }
        self.assertEqual((await method(Subject(invalid)))[0], "Eparam")
        valid = {**invalid, "pro_id": "5"}
        self.pro_service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(Subject(valid)), ("Edb", "failed"))
        self.pro_service.get_pro.return_value = (None, self.pro)

        manager = MagicMock()
        manager.copy_from_pack = AsyncMock(return_value=(("Eio", "input"), None))
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual(await method(Subject(valid)), ("Eio", "input"))
        self.pack_service.clear.assert_awaited_with("out")

        manager = MagicMock()
        manager.copy_from_pack = AsyncMock(
            side_effect=[(None, None), (("Eio", "output"), None)]
        )
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual(await method(Subject(valid)), ("Eio", "output"))
        manager.delete.assert_called_once_with("new.in")

        self.pro = problem(with_testdata=False)
        self.pro_service.get_pro.return_value = (None, self.pro)
        manager = MagicMock()
        manager.copy_from_pack = AsyncMock(return_value=(None, None))
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual(await method(Subject(valid)), ("S", ""))
        self.assertEqual(self.pro.config.testdatas[0].inputfile, "new.in")

    async def test_delete_file_validation_failure_and_subtask_cleanup(self):
        method = BatchTestdataHandler.delete_single_file_action
        for arguments in (
            {"pro_id": "bad", "testdata_id": "0"},
            {"pro_id": "5", "testdata_id": "bad"},
        ):
            self.assertEqual((await method(Subject(arguments)))[0], "Eparam")
        valid = {"pro_id": "5", "testdata_id": "0"}
        self.pro_service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(Subject(valid)), ("Edb", "failed"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual(
            (await method(Subject({"pro_id": "5", "testdata_id": "9"})))[0],
            "Enoext",
        )

        manager = MagicMock()
        manager.multiple_delete.return_value = (("Eio", "failed"), None)
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            subject = Subject(valid)
            self.assertEqual(await method(subject), ("Eio", "failed"))
        subject.add_log.assert_awaited_once()

        manager.multiple_delete.return_value = (None, None)
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual(await method(Subject(valid)), ("S", ""))
        self.assertNotIn(0, self.pro.config.testdatas)
        self.assertEqual(self.pro.config.subtask_configs[0].testdatas, [])
        self.assertEqual(len(self.pro.config.subtask_configs[1].testdatas), 1)

    async def test_metadata_validation_service_missing_and_tags(self):
        method = BatchTestdataHandler.update_metadata_action
        for arguments in (
            {"pro_id": "bad", "testdata_id": "0"},
            {"pro_id": "5", "testdata_id": "bad"},
        ):
            self.assertEqual((await method(Subject(arguments)))[0], "Eparam")
        valid = {"pro_id": "5", "testdata_id": "0", "tags": " sample, ,system-test "}
        self.pro_service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(Subject(valid)), ("Edb", "failed"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual(
            (await method(Subject({**valid, "testdata_id": "9"})))[0], "Enoext"
        )
        self.assertEqual(await method(Subject(valid)), ("S", ""))
        self.assertEqual(
            self.pro.config.testdatas[0].metadata["tags"],
            ["sample", "system-test"],
        )

    async def test_post_dispatches_requested_action(self):
        subject = Subject({"reqtype": "preview"})
        with patch.object(
            batch_testdata_dispatcher,
            "dispatch",
            new=AsyncMock(return_value="done"),
        ) as dispatch:
            self.assertEqual(await original(BatchTestdataHandler.post)(subject), "done")
        dispatch.assert_awaited_once_with(subject, "preview")


if __name__ == "__main__":
    unittest.main()
