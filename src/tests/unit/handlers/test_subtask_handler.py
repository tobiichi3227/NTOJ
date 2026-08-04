import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.manage.pro.subtask import ManageProSubtaskHandler, subtask_dispatcher
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
        self.acct = MagicMock(
            acct_id=1, acct_type=UserConst.ACCTTYPE_KERNEL, name="admin"
        )
        self.have_cycle = ManageProSubtaskHandler.have_cycle.__get__(self)

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


def problem():
    testdatas = {
        0: BatchTestdata(0, inputfile="a.in", outputfile="a.out"),
        1: BatchTestdata(1, inputfile="b.in", outputfile="b.out"),
    }
    return SimpleNamespace(
        problem_type=ProType.BATCH,
        config=SimpleNamespace(
            testdatas=testdatas,
            subtask_configs={
                0: SubtaskConfig(0, [testdatas[0]], set(), 40),
                1: SubtaskConfig(1, [testdatas[1]], {0}, 60),
            },
        ),
    )


class TestManageProblemSubtaskHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pro = problem()
        self.service = SimpleNamespace(
            get_pro=AsyncMock(return_value=(None, self.pro)),
            update_pro_config=AsyncMock(return_value=(None, None)),
        )
        service_patch = patch.object(ProService, "inst", self.service, create=True)
        service_patch.start()
        self.addCleanup(service_patch.stop)

    async def test_get_validation_service_error_and_render(self):
        method = original(ManageProSubtaskHandler.get)
        self.assertEqual((await method(Subject({"proid": "bad"})))[0], "Eparam")

        self.service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(Subject({"proid": "5"})), ("Edb", "failed"))

        self.service.get_pro.return_value = (None, self.pro)
        subject = Subject({"proid": "5"})
        await method(subject)
        subject.render.assert_awaited_once()

    async def test_update_rate_validation_not_found_error_and_success(self):
        method = ManageProSubtaskHandler.update_rate_action
        for arguments in (
            {"pro_id": "bad", "subtask": "0", "rate": "10"},
            {"pro_id": "5", "subtask": "bad", "rate": "10"},
            {"pro_id": "5", "subtask": "0", "rate": "bad"},
        ):
            self.assertEqual((await method(Subject(arguments)))[0], "Eparam")

        self.service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(
            await method(Subject({"pro_id": "5", "subtask": "0", "rate": "10"})),
            ("Edb", "failed"),
        )
        self.service.get_pro.return_value = (None, self.pro)
        self.assertEqual(
            (await method(Subject({"pro_id": "5", "subtask": "9", "rate": "10"})))[0],
            "Enoext",
        )

        subject = Subject({"pro_id": "5", "subtask": "0", "rate": "75"})
        self.assertEqual(await method(subject), ("S", ""))
        self.assertEqual(self.pro.config.subtask_configs[0].rate, 75)
        self.service.update_pro_config.assert_awaited()
        subject.add_log.assert_awaited_once()

    async def test_dependencies_validate_missing_cycle_and_success(self):
        method = ManageProSubtaskHandler.set_dep_subtasks_action
        for arguments in (
            {"pro_id": "bad", "subtask": "0", "dep_subtasks": ""},
            {"pro_id": "5", "subtask": "bad", "dep_subtasks": ""},
        ):
            self.assertEqual((await method(Subject(arguments)))[0], "Eparam")

        valid = {"pro_id": "5", "subtask": "0", "dep_subtasks": ""}
        self.service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(Subject(valid)), ("Edb", "failed"))
        self.service.get_pro.return_value = (None, self.pro)

        self.assertEqual(
            (await method(Subject({**valid, "subtask": "9"})))[0], "Enoext"
        )
        self.assertEqual(
            (await method(Subject({**valid, "dep_subtasks": "4"})))[0], "Eparam"
        )
        self.assertEqual(
            (await method(Subject({**valid, "dep_subtasks": "1"})))[0], "Eparam"
        )

        subject = Subject({**valid, "subtask": "1", "dep_subtasks": ""})
        self.assertEqual(await method(subject), ("S", ""))
        self.assertEqual(self.pro.config.subtask_configs[1].dependency_subtasks, set())
        subject.add_log.assert_awaited_once()

    async def test_add_and_delete_validation_errors_and_success(self):
        add = ManageProSubtaskHandler.add_subtask_action
        self.assertEqual(
            (await add(Subject({"pro_id": "bad", "rate": "5"})))[0], "Eparam"
        )
        self.assertEqual(
            (await add(Subject({"pro_id": "5", "rate": "bad"})))[0], "Eparam"
        )
        self.service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(
            await add(Subject({"pro_id": "5", "rate": "5"})), ("Edb", "failed")
        )
        self.service.get_pro.return_value = (None, self.pro)
        self.assertEqual(await add(Subject({"pro_id": "5", "rate": "5"})), ("S", ""))
        self.assertEqual(self.pro.config.subtask_configs[2].rate, 5)

        delete = ManageProSubtaskHandler.delete_subtask_action
        for arguments in (
            {"pro_id": "bad", "subtask": "0"},
            {"pro_id": "5", "subtask": "bad"},
        ):
            self.assertEqual((await delete(Subject(arguments)))[0], "Eparam")
        self.service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(
            await delete(Subject({"pro_id": "5", "subtask": "0"})),
            ("Edb", "failed"),
        )
        self.service.get_pro.return_value = (None, self.pro)
        self.assertEqual(
            (await delete(Subject({"pro_id": "5", "subtask": "9"})))[0],
            "Enoext",
        )
        self.assertEqual(
            await delete(Subject({"pro_id": "5", "subtask": "1"})), ("S", "")
        )
        self.assertEqual(list(self.pro.config.subtask_configs), [0, 1])

    async def test_set_testdata_validation_filtering_and_success(self):
        method = ManageProSubtaskHandler.set_testdata_action
        for arguments in (
            {"pro_id": "bad", "subtask": "0", "testdatas": "1"},
            {"pro_id": "5", "subtask": "bad", "testdatas": "1"},
        ):
            self.assertEqual((await method(Subject(arguments)))[0], "Eparam")
        valid = {"pro_id": "5", "subtask": "0", "testdatas": "1,99"}
        self.service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(Subject(valid)), ("Edb", "failed"))
        self.service.get_pro.return_value = (None, self.pro)
        self.assertEqual(
            (await method(Subject({**valid, "subtask": "9"})))[0], "Enoext"
        )

        subject = Subject(valid)
        self.assertEqual(await method(subject), ("S", ""))
        self.assertEqual(
            [item.testdata_id for item in self.pro.config.subtask_configs[0].testdatas],
            [0],
        )

    async def test_metadata_validation_missing_error_and_tag_parsing(self):
        method = ManageProSubtaskHandler.update_metadata_action
        for arguments in (
            {"pro_id": "bad", "subtask": "0"},
            {"pro_id": "5", "subtask": "bad"},
        ):
            self.assertEqual((await method(Subject(arguments)))[0], "Eparam")
        valid = {"pro_id": "5", "subtask": "0", "tags": " sample, ,system-test "}
        self.service.get_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(Subject(valid)), ("Edb", "failed"))
        self.service.get_pro.return_value = (None, self.pro)
        self.assertEqual(
            (await method(Subject({**valid, "subtask": "9"})))[0], "Enoext"
        )

        self.assertEqual(await method(Subject(valid)), ("S", ""))
        self.assertEqual(
            self.pro.config.subtask_configs[0].metadata["tags"],
            ["sample", "system-test"],
        )

    async def test_post_dispatches_and_cycle_detector_handles_graph_shapes(self):
        subject = Subject({"reqtype": "addsubtask"})
        with patch.object(
            subtask_dispatcher, "dispatch", new=AsyncMock(return_value="done")
        ) as dispatch:
            self.assertEqual(await original(ManageProSubtaskHandler.post)(subject), "done")
        dispatch.assert_awaited_once_with(subject, "addsubtask")

        handler = object.__new__(ManageProSubtaskHandler)
        acyclic = {
            0: SubtaskConfig(0, [], set(), 1),
            1: SubtaskConfig(1, [], {0}, 1),
            2: SubtaskConfig(2, [], {1}, 1),
        }
        cyclic = {
            0: SubtaskConfig(0, [], {1}, 1),
            1: SubtaskConfig(1, [], {0}, 1),
        }
        self.assertFalse(handler.have_cycle(acyclic))
        self.assertTrue(handler.have_cycle(cyclic))


if __name__ == "__main__":
    unittest.main()
