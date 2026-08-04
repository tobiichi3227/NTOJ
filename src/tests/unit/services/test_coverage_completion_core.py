import contextlib
import datetime
import decimal
import io
import json
import os
import tempfile
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.board import BoardService
from services.bulletin import BulletinService
from services.filemanager import FileManager
from services.log import LogService, _Encoder
from services.rank import RankService
from services.rate import RateService
from utils.dbg import dbg_print
from utils.htmlgen import gen_page_title, markdown_escape, pro_idx_to_pro_alphabet
from utils.numeric import merge_list_to_str, parse_str_to_list


def database_fixture():
    connection = AsyncMock()
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=connection)
    acquire.__aexit__ = AsyncMock(return_value=None)
    database = MagicMock()
    database.acquire.return_value = acquire
    database.fetch = AsyncMock()
    return database, connection


class TestUtilityCoverageCompletion(unittest.TestCase):
    def test_debug_print_with_and_without_values(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            dbg_print("example.py", 12, answer=42)
            dbg_print()
        self.assertIn("example.py", output.getvalue())
        self.assertIn("answer: 42", output.getvalue())

    def test_numeric_reversed_and_disconnected_ranges(self):
        self.assertEqual(parse_str_to_list("3-1,bad"), [1, 2, 3])
        self.assertEqual(merge_list_to_str([1, 3]), "1,3")
        self.assertEqual(merge_list_to_str([1, 2, 4]), "1-2,4")

    def test_html_helpers_default_title_escape_and_large_index(self):
        self.assertIn("NTOJ", gen_page_title(""))
        self.assertEqual(markdown_escape("`a\\b`"), "\\`a\\\\b\\`")
        self.assertEqual(pro_idx_to_pro_alphabet(26), "pAA")


class TestSimpleServiceErrors(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db, self.connection = database_fixture()

    async def test_board_database_errors(self):
        service = BoardService(self.db, None)
        cases = (
            ("fetch", service.get_boardlist, ()),
            ("fetchrow", service.get_board, (1,)),
            ("fetch", service.add_board, ("name", 0, None, None, [], [])),
            ("fetch", service.update_board, (1, "name", 0, None, None, [], [])),
            ("execute", service.remove_board, (1,)),
        )
        for mock_name, method, args in cases:
            with self.subTest(method=method.__name__):
                target = getattr(self.connection, mock_name)
                target.side_effect = RuntimeError("database unavailable")
                error, value = await method(*args)
                self.assertEqual(error[0], "Eunk")
                self.assertIsNone(value)
                target.side_effect = None

    async def test_bulletin_database_errors(self):
        service = BulletinService(self.db, None)
        cases = (
            ("fetch", service.list_bulletin, ()),
            ("fetch", service.get_bulletin, (1,)),
            ("fetch", service.add_bulletin, ("title", "body", 1)),
            ("fetch", service.edit_bulletin, (1, "title", "body", 1, "White", False)),
            ("execute", service.del_bulletin, (1,)),
        )
        for mock_name, method, args in cases:
            with self.subTest(method=method.__name__):
                target = getattr(self.connection, mock_name)
                target.side_effect = RuntimeError("database unavailable")
                error, value = await method(*args)
                self.assertEqual(error[0], "Eunk")
                self.assertIsNone(value)
                target.side_effect = None

    async def test_rank_database_errors(self):
        service = RankService(self.db, None)
        self.connection.fetch.side_effect = RuntimeError("database unavailable")
        self.assertEqual((await service.get_pro_rank(1, 0, 10))[0][0], "Eunk")

        self.db.fetch.side_effect = RuntimeError("database unavailable")
        self.assertEqual((await service.get_user_rank(0, 10))[0][0], "Eunk")


@dataclass
class EncodedValue:
    value: int


class TestLogCoverageCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db, self.connection = database_fixture()
        self.service = LogService(self.db, None)

    def test_encoder_dataclass_decimal_and_unsupported_value(self):
        payload = json.dumps(
            {"data": EncodedValue(3), "decimal": decimal.Decimal("1.25")},
            cls=_Encoder,
        )
        self.assertEqual(json.loads(payload), {"data": {"value": 3}, "decimal": "1.25"})
        with self.assertRaises(TypeError):
            json.dumps(object(), cls=_Encoder)

    async def test_add_log_handler_without_request_and_database_error(self):
        handler = SimpleNamespace(acct=None, contest=SimpleNamespace(contest_id=9))
        self.connection.fetch.return_value = [{"log_id": 4}]
        self.assertEqual((await self.service.add_log("ok", handler=handler))[1], 4)

        self.connection.fetch.side_effect = RuntimeError("database unavailable")
        error, value = await self.service.add_log("failed")
        self.assertEqual(error[0], "Eunk")
        self.assertIsNone(value)

    async def test_view_list_and_type_database_errors(self):
        self.connection.fetch.side_effect = RuntimeError("database unavailable")
        for method, args in (
            (self.service.view_log, (1,)),
            (self.service.list_log, (0, 10)),
            (self.service.get_log_type, ()),
        ):
            with self.subTest(method=method.__name__):
                error, value = await method(*args)
                self.assertEqual(error[0], "Eunk")
                self.assertIsNone(value)

    async def test_list_log_with_both_filters(self):
        self.connection.fetch.side_effect = [
            [(1, "message", datetime.datetime(2025, 1, 1), 2, 3)],
            [{"count": 1}],
        ]
        error, result = await self.service.list_log(0, 10, "judge", 3)
        self.assertIsNone(error)
        self.assertEqual(result["lognum"], 1)
        self.assertEqual(result["loglist"][0]["contest_id"], 3)


class TestRateCoverageCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db, self.connection = database_fixture()
        self.redis = AsyncMock()
        self.redis.hget.return_value = None
        self.service = RateService(self.db, self.redis)
        self.account = SimpleNamespace(acct_id=7, is_kernel=MagicMock(return_value=False))

    async def test_account_rate_short_results_and_database_error(self):
        self.connection.fetch.return_value = []
        self.assertEqual((await self.service.get_acct_rate_and_chal_cnt(self.account))[0][0], "Eunk")

        self.connection.fetch.side_effect = [
            [{"ac_chal_cnt": 1, "all_chal_cnt": 2}],
            [],
        ]
        self.assertEqual((await self.service.get_acct_rate_and_chal_cnt(self.account))[0][0], "Eunk")

        self.connection.fetch.side_effect = RuntimeError("database unavailable")
        self.assertEqual((await self.service.get_acct_rate_and_chal_cnt(self.account))[0][0], "Eunk")

    async def test_refresh_single_account(self):
        self.assertIsNone(await self.service.refresh_acct_rate(7))
        self.redis.hdel.assert_awaited_once_with("rate", "7")

    async def test_problem_rate_topcoder_and_rate_map_database_errors(self):
        self.connection.fetchrow.side_effect = RuntimeError("database unavailable")
        self.assertEqual((await self.service.get_pro_ac_rate(1, 2))[0][0], "Eunk")

        self.connection.fetch.side_effect = RuntimeError("database unavailable")
        self.assertEqual((await self.service.get_pro_topcoder(1))[0][0], "Eunk")

        start = datetime.datetime(2025, 1, 1)
        end = datetime.datetime(2025, 1, 2)
        self.assertEqual(
            (await self.service.map_rate_acct(self.account, 0, start, end))[0][0],
            "Eunk",
        )
        self.assertEqual((await self.service.map_rate(0, start, end))[0][0], "Eunk")


class TestFileManagerCoverageCompletion(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.manager = FileManager(self.directory.name)
        self.path = os.path.join(self.directory.name, "file.txt")
        with open(self.path, "w") as stream:
            stream.write("text")

    def tearDown(self):
        self.directory.cleanup()

    def test_directory_is_not_a_safe_regular_file(self):
        os.mkdir(os.path.join(self.directory.name, "folder"))
        self.assertFalse(self.manager._is_safe_path("folder"))

    def test_delete_rename_and_multiple_delete_os_errors(self):
        with patch("services.filemanager.os.remove", side_effect=OSError("denied")):
            self.assertEqual(self.manager.delete("file.txt")[0][0], "Eunk")
            self.assertEqual(self.manager.multiple_delete(["file.txt"])[0][0], "Eunk")
        with patch("services.filemanager.os.rename", side_effect=OSError("denied")):
            self.assertEqual(self.manager.rename("file.txt", "new.txt")[0][0], "Eunk")

    def test_read_unicode_and_os_errors(self):
        unicode_error = UnicodeDecodeError("utf-8", b"x", 0, 1, "invalid")
        with patch("builtins.open", side_effect=unicode_error):
            self.assertEqual(self.manager.read("file.txt")[0][0], "Eunicode")
        with patch("builtins.open", side_effect=OSError("denied")):
            self.assertEqual(self.manager.read("file.txt")[0][0], "Eunk")


if __name__ == "__main__":
    unittest.main()
