import datetime
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.board import BoardHandler
from handlers.manage.board import ManageBoardHandler, board_dispatcher, trantime
from services.board import BoardConst, BoardService
from services.pro import ProConst, ProService
from services.rate import RateService
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
    def __init__(self, arguments=None):
        self.arguments = arguments or {}
        self.error = MagicMock(side_effect=lambda value: value)
        self.render = AsyncMock(return_value="rendered")
        self.add_log = AsyncMock(return_value=(None, 1))
        self.acct = MagicMock(
            acct_id=1, acct_type=UserConst.ACCTTYPE_KERNEL, name="admin"
        )
        self.acct.is_kernel.return_value = False

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


class TestBoardHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.board_service = SimpleNamespace(
            get_boardlist=AsyncMock(return_value=(None, [{"board_id": 1}])),
            get_board=AsyncMock(),
        )
        self.pro_service = SimpleNamespace(list_pro=AsyncMock())
        self.user_service = SimpleNamespace(list_acct=AsyncMock())
        self.rate_service = SimpleNamespace(map_rate=AsyncMock())
        for service, value in (
            (BoardService, self.board_service),
            (ProService, self.pro_service),
            (UserService, self.user_service),
            (RateService, self.rate_service),
        ):
            active_patch = patch.object(service, "inst", value, create=True)
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def test_list_validation_missing_and_hidden_board(self):
        method = original(BoardHandler.get)
        subject = Subject()
        await method(subject, None)
        subject.render.assert_awaited_once_with(
            "board-list", "Board List", boardlist=[{"board_id": 1}]
        )

        self.assertEqual(
            await method(Subject(), "bad"), ("Eparam", "Invalid board id")
        )
        self.board_service.get_board.return_value = (("Enoext", "missing"), None)
        self.assertEqual(await method(Subject(), "3"), ("Enoext", "missing"))

        self.board_service.get_board.return_value = (
            None,
            {
                "status": BoardConst.STATUS_HIDDEN,
                "name": "hidden",
                "start": None,
                "end": None,
                "pro_list": [],
                "acct_list": [],
            },
        )
        self.assertEqual((await method(Subject(), "3"))[0], "Eacces")

    async def test_board_ranking_accumulates_rates_submissions_and_ties(self):
        method = original(BoardHandler.get)
        meta = {
            "status": BoardConst.STATUS_HIDDEN,
            "name": "Final",
            "start": datetime.datetime(2025, 1, 1),
            "end": datetime.datetime(2025, 1, 2),
            "pro_list": [1, 2],
            "acct_list": [1, 2, 3],
        }
        self.board_service.get_board.return_value = (None, meta)
        self.pro_service.list_pro.return_value = (
            None,
            [SimpleNamespace(pro_id=1), SimpleNamespace(pro_id=2), SimpleNamespace(pro_id=9)],
        )
        accounts = [
            SimpleNamespace(acct_id=1),
            SimpleNamespace(acct_id=2),
            SimpleNamespace(acct_id=3),
            SimpleNamespace(acct_id=99),
        ]
        self.user_service.list_acct.return_value = (None, accounts)
        self.rate_service.map_rate.return_value = (
            None,
            {
                1: {1: {"rate": 50, "count": 2}, 2: {"rate": 50, "count": 1}},
                2: {1: {"rate": 100, "count": 5}, 2: {"rate": 0, "count": 0}},
                3: {1: {"rate": 100, "count": 5}},
            },
        )
        subject = Subject()
        subject.acct.is_kernel.return_value = True

        await method(subject, "4")

        self.user_service.list_acct.assert_awaited_with(
            min_type=UserConst.ACCTTYPE_KERNEL
        )
        rendered = subject.render.await_args.kwargs
        self.assertEqual([pro.pro_id for pro in rendered["prolist"]], [1, 2])
        self.assertEqual(len(rendered["acctlist"]), 3)
        self.assertEqual(rendered["acctlist"][0].rank, 1)
        self.assertEqual(rendered["acctlist"][1].rank, 2)
        self.assertEqual(rendered["acctlist"][2].rank, 2)
        self.assertEqual(rendered["pro_sc_sub"][1], (250, 12))
        self.assertEqual(rendered["pro_sc_sub"][2], (50, 1))


class TestManageBoardHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = SimpleNamespace(
            get_boardlist=AsyncMock(return_value=(None, [])),
            get_board=AsyncMock(),
            add_board=AsyncMock(),
            update_board=AsyncMock(),
            remove_board=AsyncMock(),
        )
        active_patch = patch.object(BoardService, "inst", self.service, create=True)
        active_patch.start()
        self.addCleanup(active_patch.stop)

    def test_time_parser_empty_valid_and_invalid(self):
        self.assertEqual(trantime(""), (None, None))
        err, value = trantime("2025-01-02T03:04:05.000Z")
        self.assertIsNone(err)
        self.assertEqual(value.tzinfo, datetime.timezone.utc)
        self.assertEqual(trantime("bad")[0][0], "Eparam")

    async def test_get_pages_and_update_validation(self):
        method = original(ManageBoardHandler.get)
        subject = Subject()
        await method(subject, None)
        subject.render.assert_awaited_once()
        subject = Subject()
        await method(subject, "add")
        subject.render.assert_awaited_once()
        self.assertEqual(
            (await method(Subject({"boardid": "bad"}), "update"))[0], "Eparam"
        )
        self.service.get_board.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (await method(Subject({"boardid": "2"}), "update"))[0], "Enoext"
        )
        self.service.get_board.return_value = (None, {"name": "Board"})
        subject = Subject({"boardid": "2"})
        await method(subject, "update")
        subject.render.assert_awaited_once()

    async def test_post_dispatches_requested_action(self):
        method = original(ManageBoardHandler.post)
        subject = Subject({"reqtype": "add"})
        with patch.object(
            board_dispatcher, "dispatch", new=AsyncMock(return_value="dispatched")
        ) as dispatch:
            self.assertEqual(await method(subject, None), "dispatched")
        dispatch.assert_awaited_once_with(subject, "add")

    def valid_arguments(self):
        return {
            "status": "0",
            "name": "Board",
            "start": "2025-01-02T03:04:05.000Z",
            "end": "",
            "acct_list": "1,2",
            "pro_list": "3,4",
        }

    async def test_add_board_validation_service_error_and_success(self):
        self.assertEqual(
            (await ManageBoardHandler.add_board(Subject({"status": "bad"})))[0],
            "Eparam",
        )
        arguments = self.valid_arguments()
        arguments["start"] = "bad"
        self.assertEqual(
            (await ManageBoardHandler.add_board(Subject(arguments)))[0], "Eparam"
        )
        arguments = self.valid_arguments()
        arguments["end"] = "bad"
        self.assertEqual(
            (await ManageBoardHandler.add_board(Subject(arguments)))[0], "Eparam"
        )

        arguments = self.valid_arguments()
        subject = Subject(arguments)
        self.service.add_board.return_value = (("Edb", "failed"), None)
        self.assertEqual(await ManageBoardHandler.add_board(subject), ("Edb", "failed"))
        self.service.add_board.return_value = (None, 12)
        await ManageBoardHandler.add_board(subject)
        subject.error.assert_called_with(("S", 12))
        subject.add_log.assert_awaited()

    async def test_update_and_remove_validation_errors_and_success(self):
        arguments = self.valid_arguments()
        arguments["board_id"] = "bad"
        self.assertEqual(
            (await ManageBoardHandler.update_board(Subject(arguments)))[0], "Eparam"
        )
        arguments["board_id"] = "1"
        arguments["status"] = "bad"
        self.assertEqual(
            (await ManageBoardHandler.update_board(Subject(arguments)))[0], "Eparam"
        )
        arguments = self.valid_arguments() | {"board_id": "1"}
        arguments["start"] = "bad"
        self.assertEqual(
            (await ManageBoardHandler.update_board(Subject(arguments)))[0], "Eparam"
        )
        arguments = self.valid_arguments() | {"board_id": "1"}
        arguments["end"] = "bad"
        self.assertEqual(
            (await ManageBoardHandler.update_board(Subject(arguments)))[0], "Eparam"
        )

        arguments = self.valid_arguments() | {"board_id": "1"}
        subject = Subject(arguments)
        self.service.update_board.return_value = (("Edb", "failed"), None)
        self.assertEqual(
            await ManageBoardHandler.update_board(subject), ("Edb", "failed")
        )
        self.service.update_board.return_value = (None, None)
        await ManageBoardHandler.update_board(subject)
        subject.error.assert_called_with(("S", ""))

        self.assertEqual(
            (await ManageBoardHandler.remove_board(Subject({"board_id": "bad"})))[0],
            "Eparam",
        )
        subject = Subject({"board_id": "1"})
        self.service.remove_board.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            await ManageBoardHandler.remove_board(subject), ("Enoext", "missing")
        )
        self.service.remove_board.return_value = (None, None)
        await ManageBoardHandler.remove_board(subject)
        subject.error.assert_called_with(("S", ""))
        subject.add_log.assert_awaited()


if __name__ == "__main__":
    unittest.main()
