import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

from handlers.prospec.batch.testdata import BatchTestdataHandler
from services.pack import PackService
from services.pro import ProConst, ProService, SubtaskConfig
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
        self.acct = MagicMock(
            acct_id=1, acct_type=UserConst.ACCTTYPE_KERNEL, name="admin"
        )
        self.error = MagicMock(side_effect=lambda value: value)
        self.render = AsyncMock(return_value="rendered")
        self.add_log = AsyncMock(return_value=(None, 1))
        self.set_header = MagicMock()
        self.write = MagicMock()
        self.finish = MagicMock()

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


def problem(*, empty=False):
    first = BatchTestdata(
        testdata_id=0,
        inputfile="zero.in",
        outputfile="zero.out",
        metadata={"tags": []},
    )
    second = BatchTestdata(
        testdata_id=1,
        inputfile="one.in",
        outputfile="one.out",
        metadata={"tags": []},
    )
    testdatas = {} if empty else {0: first, 1: second}
    subtasks = (
        {}
        if empty
        else {
            0: SubtaskConfig(0, [first], set(), 50),
            1: SubtaskConfig(1, [second], set(), 50),
        }
    )
    return SimpleNamespace(
        problem_type=1,
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
            active_patch = patch.object(service, "inst", value, create=True)
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def test_get_validation_service_render_and_download_failures(self):
        get = original(BatchTestdataHandler.get)
        self.assertEqual((await get(Subject({"proid": "bad"})))[0], "Eparam")

        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(await get(Subject({"proid": "5"})), ("Enoext", "missing"))
        self.pro_service.get_pro.return_value = (None, self.pro)

        subject = Subject({"proid": "5"})
        await get(subject)
        subject.render.assert_awaited_once()

        subject = Subject({"proid": "5", "download": "1", "type": "bad"})
        self.assertEqual((await get(subject))[0], "Eparam")

        subject = Subject(
            {"proid": "5", "download": "1", "type": "input", "testdata_id": "8"}
        )
        self.assertIsNone(await get(subject))
        subject.error.assert_called_with(("Enoext", "Testdata not found"))

        subject = Subject(
            {"proid": "5", "download": "1", "type": "output", "testdata_id": "0"}
        )
        with patch("handlers.prospec.batch.testdata.os.path.exists", return_value=False):
            self.assertEqual((await get(subject))[0], "Enoext")

    async def test_get_streams_input_and_handles_read_error(self):
        get = original(BatchTestdataHandler.get)
        arguments = {
            "proid": "5",
            "download": "1",
            "type": "input",
            "testdata_id": "0",
        }
        subject = Subject(arguments)
        stream = MagicMock()
        stream.__enter__.return_value.read.side_effect = [b"content", b""]
        with (
            patch("handlers.prospec.batch.testdata.os.path.exists", return_value=True),
            patch("builtins.open", return_value=stream),
        ):
            await get(subject)
        subject.write.assert_called_once_with(b"content")
        subject.finish.assert_called_once()
        subject.set_header.assert_any_call("Content-Type", "application/octet-stream")

        subject = Subject(arguments)
        broken = MagicMock()
        broken.__enter__.return_value.read.side_effect = OSError("read")
        with (
            patch("handlers.prospec.batch.testdata.os.path.exists", return_value=True),
            patch("builtins.open", return_value=broken),
        ):
            await get(subject)
        subject.error.assert_called_with(("Eunk", "Unknown error"))

    async def test_preview_validates_and_covers_missing_large_and_escaped_content(self):
        preview = BatchTestdataHandler.preview_action
        self.assertEqual(
            (await preview(Subject({"pro_id": "bad", "testdata_id": "0", "type": "input"})))[0],
            "Eparam",
        )
        self.assertEqual(
            (await preview(Subject({"pro_id": "5", "testdata_id": "bad", "type": "input"})))[0],
            "Eparam",
        )
        self.assertEqual(
            (await preview(Subject({"pro_id": "5", "testdata_id": "0", "type": "bad"})))[0],
            "Eparam",
        )

        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(
            await preview(Subject({"pro_id": "5", "testdata_id": "0", "type": "input"})),
            ("Edb", "down"),
        )
        self.pro_service.get_pro.return_value = (None, self.pro)

        missing = Subject({"pro_id": "5", "testdata_id": "8", "type": "input"})
        self.assertEqual((await preview(missing))[0], "Enoext")

        missing_file = Subject({"pro_id": "5", "testdata_id": "0", "type": "output"})
        with patch("handlers.prospec.batch.testdata.os.path.exists", return_value=False):
            self.assertEqual((await preview(missing_file))[0], "Enoext")
        missing_file.add_log.assert_awaited_once()

        large = Subject({"pro_id": "5", "testdata_id": "0", "type": "input"})
        with (
            patch("handlers.prospec.batch.testdata.os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="x\n" * 26)),
        ):
            self.assertEqual((await preview(large))[0], "Efile")

        escaped = Subject({"pro_id": "5", "testdata_id": "0", "type": "output"})
        with (
            patch("handlers.prospec.batch.testdata.os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="<tag>&\n")),
        ):
            result = await preview(escaped)
        self.assertEqual(result[0], "S")
        self.assertEqual(result[1], "&lt;tag&gt;&amp;\n")

    async def test_update_single_file_missing_failure_and_success(self):
        update = BatchTestdataHandler.update_single_file_action
        base = {"pro_id": "5", "testdata_id": "0", "type": "input", "pack_token": "p"}
        self.assertEqual((await update(Subject({**base, "pro_id": "bad"})))[0], "Eparam")
        self.assertEqual((await update(Subject({**base, "testdata_id": "bad"})))[0], "Eparam")
        self.assertEqual((await update(Subject({**base, "type": "bad"})))[0], "Eparam")

        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(await update(Subject(base)), ("Edb", "down"))
        self.pro_service.get_pro.return_value = (None, self.pro)

        missing = Subject({**base, "testdata_id": "8"})
        self.assertEqual((await update(missing))[0], "Enoext")
        self.pack_service.clear.assert_awaited_with("p")

        manager = MagicMock()
        manager.update_from_pack = AsyncMock(return_value=(("Efile", "bad"), None))
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual((await update(Subject(base)))[0], "Efile")

        manager.update_from_pack.return_value = (None, None)
        output = Subject({**base, "type": "output"})
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual(await update(output), ("S", ""))
        manager.update_from_pack.assert_awaited_with("zero.out", "p")
        self.pro_service.update_pro_config.assert_awaited()

    async def test_add_single_file_rollbacks_and_success_for_empty_config(self):
        add = BatchTestdataHandler.add_single_file_action
        base = {
            "pro_id": "5",
            "filename": "sample",
            "input_pack_token": "in-pack",
            "output_pack_token": "out-pack",
        }
        self.assertEqual((await add(Subject({**base, "pro_id": "bad"})))[0], "Eparam")
        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(await add(Subject(base)), ("Edb", "down"))

        empty = problem(empty=True)
        self.pro_service.get_pro.return_value = (None, empty)
        manager = MagicMock()
        manager.copy_from_pack = AsyncMock(side_effect=[(("Efile", "input"), None)])
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual((await add(Subject(base)))[0], "Efile")
        self.pack_service.clear.assert_awaited_with("out-pack")

        manager.copy_from_pack.side_effect = [(None, None), (("Efile", "output"), None)]
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual((await add(Subject(base)))[0], "Efile")
        manager.delete.assert_called_with("sample.in")

        manager.copy_from_pack.side_effect = [(None, None), (None, None)]
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual(await add(Subject(base)), ("S", ""))
        self.assertEqual(empty.config.testdatas[0].outputfile, "sample.out")

    async def test_delete_single_file_failure_and_removes_subtask_references(self):
        delete = BatchTestdataHandler.delete_single_file_action
        base = {"pro_id": "5", "testdata_id": "0"}
        self.assertEqual((await delete(Subject({**base, "pro_id": "bad"})))[0], "Eparam")
        self.assertEqual((await delete(Subject({**base, "testdata_id": "bad"})))[0], "Eparam")

        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(await delete(Subject(base)), ("Edb", "down"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual((await delete(Subject({**base, "testdata_id": "8"})))[0], "Enoext")

        manager = MagicMock()
        manager.multiple_delete.return_value = (("Efile", "delete"), None)
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual((await delete(Subject(base)))[0], "Efile")

        manager.multiple_delete.return_value = (None, None)
        with patch("handlers.prospec.batch.testdata.FileManager", return_value=manager):
            self.assertEqual(await delete(Subject(base)), ("S", ""))
        self.assertNotIn(0, self.pro.config.testdatas)
        self.assertEqual(self.pro.config.subtask_configs[0].testdatas, [])
        self.assertEqual(len(self.pro.config.subtask_configs[1].testdatas), 1)

    async def test_update_metadata_validation_error_and_tag_parsing(self):
        update = BatchTestdataHandler.update_metadata_action
        base = {"pro_id": "5", "testdata_id": "0", "tags": " sample, ,system-test "}
        self.assertEqual((await update(Subject({**base, "pro_id": "bad"})))[0], "Eparam")
        self.assertEqual((await update(Subject({**base, "testdata_id": "bad"})))[0], "Eparam")
        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(await update(Subject(base)), ("Edb", "down"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual((await update(Subject({**base, "testdata_id": "8"})))[0], "Enoext")
        self.assertEqual(await update(Subject(base)), ("S", ""))
        self.assertEqual(self.pro.config.testdatas[0].metadata["tags"], ["sample", "system-test"])


if __name__ == "__main__":
    unittest.main()
