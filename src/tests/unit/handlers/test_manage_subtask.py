import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.manage.pro.subtask import ManageProSubtaskHandler
from services.pro import ProService, SubtaskConfig
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
        self.have_cycle = ManageProSubtaskHandler.have_cycle.__get__(self)

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


def problem():
    zero = BatchTestdata(0, inputfile="zero.in", outputfile="zero.out")
    one = BatchTestdata(1, inputfile="one.in", outputfile="one.out")
    return SimpleNamespace(
        problem_type=1,
        config=SimpleNamespace(
            testdatas={0: zero, 1: one},
            subtask_configs={
                0: SubtaskConfig(0, [zero], set(), 40),
                1: SubtaskConfig(1, [one], set(), 60),
            },
        ),
    )


class TestManageProSubtaskHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pro = problem()
        self.pro_service = SimpleNamespace(
            get_pro=AsyncMock(return_value=(None, self.pro)),
            update_pro_config=AsyncMock(return_value=(None, None)),
        )
        active_patch = patch.object(ProService, "inst", self.pro_service, create=True)
        active_patch.start()
        self.addCleanup(active_patch.stop)

    async def test_get_validation_service_error_and_render(self):
        get = original(ManageProSubtaskHandler.get)
        self.assertEqual((await get(Subject({"proid": "bad"})))[0], "Eparam")
        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(await get(Subject({"proid": "5"})), ("Enoext", "missing"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        subject = Subject({"proid": "5"})
        await get(subject)
        subject.render.assert_awaited_once()

    async def test_update_rate_validation_missing_service_and_success(self):
        update = ManageProSubtaskHandler.update_rate_action
        base = {"pro_id": "5", "subtask": "0", "rate": "70"}
        self.assertEqual((await update(Subject({**base, "pro_id": "bad"})))[0], "Eparam")
        self.assertEqual((await update(Subject({**base, "subtask": "bad"})))[0], "Eparam")
        self.assertEqual((await update(Subject({**base, "rate": "bad"})))[0], "Eparam")
        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(await update(Subject(base)), ("Edb", "down"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual((await update(Subject({**base, "subtask": "8"})))[0], "Enoext")
        self.assertEqual(await update(Subject(base)), ("S", ""))
        self.assertEqual(self.pro.config.subtask_configs[0].rate, 70)

    async def test_set_dependencies_validates_targets_detects_cycle_and_saves(self):
        update = ManageProSubtaskHandler.set_dep_subtasks_action
        base = {"pro_id": "5", "subtask": "1", "dep_subtasks": "1"}
        self.assertEqual((await update(Subject({**base, "pro_id": "bad"})))[0], "Eparam")
        self.assertEqual((await update(Subject({**base, "subtask": "bad"})))[0], "Eparam")
        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(await update(Subject(base)), ("Edb", "down"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual((await update(Subject({**base, "subtask": "8"})))[0], "Enoext")
        self.assertEqual(
            (await update(Subject({**base, "dep_subtasks": "9"})))[0], "Eparam"
        )

        self.pro.config.subtask_configs[0].dependency_subtasks = {1}
        self.assertEqual((await update(Subject(base)))[1], "Dependency subtasks have cycle")
        self.pro.config.subtask_configs[0].dependency_subtasks = set()
        self.assertEqual(await update(Subject(base)), ("S", ""))
        self.assertEqual(self.pro.config.subtask_configs[1].dependency_subtasks, {0})

    async def test_add_subtask_validation_service_error_and_success(self):
        add = ManageProSubtaskHandler.add_subtask_action
        base = {"pro_id": "5", "rate": "25"}
        self.assertEqual((await add(Subject({**base, "pro_id": "bad"})))[0], "Eparam")
        self.assertEqual((await add(Subject({**base, "rate": "bad"})))[0], "Eparam")
        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(await add(Subject(base)), ("Edb", "down"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual(await add(Subject(base)), ("S", ""))
        self.assertEqual(self.pro.config.subtask_configs[2].rate, 25)

    async def test_delete_subtask_validation_service_missing_and_reindexes(self):
        delete = ManageProSubtaskHandler.delete_subtask_action
        base = {"pro_id": "5", "subtask": "0"}
        self.assertEqual((await delete(Subject({**base, "pro_id": "bad"})))[0], "Eparam")
        self.assertEqual((await delete(Subject({**base, "subtask": "bad"})))[0], "Eparam")
        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(await delete(Subject(base)), ("Edb", "down"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual((await delete(Subject({**base, "subtask": "8"})))[0], "Enoext")
        self.assertEqual(await delete(Subject(base)), ("S", ""))
        self.assertEqual(list(self.pro.config.subtask_configs), [0])

    async def test_set_testdata_skips_unknown_ids_and_updates_known_ones(self):
        update = ManageProSubtaskHandler.set_testdata_action
        base = {"pro_id": "5", "subtask": "0", "testdatas": "2,9"}
        self.assertEqual((await update(Subject({**base, "pro_id": "bad"})))[0], "Eparam")
        self.assertEqual((await update(Subject({**base, "subtask": "bad"})))[0], "Eparam")
        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(await update(Subject(base)), ("Edb", "down"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual((await update(Subject({**base, "subtask": "8"})))[0], "Enoext")
        self.assertEqual(await update(Subject(base)), ("S", ""))
        self.assertEqual(
            [item.testdata_id for item in self.pro.config.subtask_configs[0].testdatas],
            [1],
        )

    async def test_update_metadata_validation_service_missing_and_tag_parsing(self):
        update = ManageProSubtaskHandler.update_metadata_action
        base = {"pro_id": "5", "subtask": "0", "tags": " sample, ,system-test "}
        self.assertEqual((await update(Subject({**base, "pro_id": "bad"})))[0], "Eparam")
        self.assertEqual((await update(Subject({**base, "subtask": "bad"})))[0], "Eparam")
        self.pro_service.get_pro.return_value = (("Edb", "down"), None)
        self.assertEqual(await update(Subject(base)), ("Edb", "down"))
        self.pro_service.get_pro.return_value = (None, self.pro)
        self.assertEqual((await update(Subject({**base, "subtask": "8"})))[0], "Enoext")
        self.assertEqual(await update(Subject(base)), ("S", ""))
        self.assertEqual(
            self.pro.config.subtask_configs[0].metadata["tags"],
            ["sample", "system-test"],
        )

    def test_cycle_detection_for_acyclic_self_and_transitive_graphs(self):
        handler = object.__new__(ManageProSubtaskHandler)
        acyclic = {
            0: SubtaskConfig(0, [], set(), 50),
            1: SubtaskConfig(1, [], {0}, 50),
        }
        self.assertFalse(handler.have_cycle(acyclic))
        acyclic[0].dependency_subtasks = {0}
        self.assertTrue(handler.have_cycle(acyclic))
        acyclic[0].dependency_subtasks = {1}
        self.assertTrue(handler.have_cycle(acyclic))


if __name__ == "__main__":
    unittest.main()
