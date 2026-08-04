import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from msgpack import packb

from handlers.bulletin import BulletinCallback
from handlers.index import DevInfoHandler, IndexHandler
from handlers.log import LogHandler
from handlers.manage.proclass import ManageProClassHandler
from handlers.pack import PackHandler
from services.chal import ChalSearchingParam
from services.code import CodeService
from services.contests import ContestService
from services.filemanager import FileManager
from services.log import LogService
from services.pack import PackService
from services.ques import QuestionService
from services.user import UserConst, UserService
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Subject,
    original,
)


def database(connection=None, enter_error=None):
    connection = connection or AsyncMock()
    acquire = MagicMock()
    if enter_error is None:
        acquire.__aenter__ = AsyncMock(return_value=connection)
    else:
        acquire.__aenter__ = AsyncMock(side_effect=enter_error)
    acquire.__aexit__ = AsyncMock(return_value=None)
    db = MagicMock()
    db.acquire.return_value = acquire
    return db, connection


class TestRemainingServiceEdges(unittest.IsolatedAsyncioTestCase):
    async def test_code_database_and_file_os_errors(self):
        db, _ = database(enter_error=RuntimeError("database"))
        service = CodeService(db, AsyncMock())
        account = SimpleNamespace(
            acct_id=1,
            name="owner",
            is_kernel=MagicMock(return_value=False),
        )
        result = await service.get_code(1, account, "127.0.0.1")
        self.assertEqual(result[0][0], "Eunk")

        db, connection = database()
        connection.fetch.return_value = [
            {
                "acct_id": 1,
                "pro_id": 2,
                "contest_id": 0,
                "compiler_type": 3,
            }
        ]
        service = CodeService(db, AsyncMock())
        with patch("builtins.open", side_effect=OSError("io")):
            error, code, _ = await service.get_code(
                1, account, "127.0.0.1"
            )
        self.assertIsNone(error)
        self.assertIn("Failed to read", code)

    async def test_code_contest_non_admin_is_denied(self):
        db, connection = database()
        connection.fetch.return_value = [
            {
                "acct_id": 2,
                "pro_id": 3,
                "contest_id": 9,
                "compiler_type": 3,
            }
        ]
        account = SimpleNamespace(
            acct_id=1,
            name="member",
            is_kernel=MagicMock(return_value=False),
        )
        contests = SimpleNamespace(
            get_contest=AsyncMock(
                return_value=(
                    None,
                    SimpleNamespace(
                        is_admin=MagicMock(return_value=False)
                    ),
                )
            )
        )
        with patch.object(
            ContestService, "inst", contests, create=True
        ):
            result = await CodeService(
                db, AsyncMock()
            ).get_code(1, account, "127.0.0.1")
        self.assertEqual(result[0][0], "Eacces")

    async def test_question_inactive_trim_and_nonempty_remove(self):
        redis = AsyncMock()
        service = QuestionService(MagicMock(), redis)

        redis.get.return_value = b""
        self.assertEqual(
            (await service.set_ques(1, "question"))[0],
            "Eacces",
        )

        redis.get.side_effect = [
            packb(True),
            packb(
                [{"Q": str(index), "A": None} for index in range(11)]
            ),
        ]
        self.assertIsNone(await service.set_ques(1, "latest"))
        stored = redis.set.await_args_list[-1].args[1]
        from msgpack import unpackb

        self.assertEqual(len(unpackb(stored)), 10)

        redis.reset_mock()
        redis.get.side_effect = [
            packb(True),
            packb(
                [
                    {"Q": "first", "A": None},
                    {"Q": "second", "A": None},
                ]
            ),
        ]
        self.assertIsNone(await service.rm_ques(1, 0))
        self.assertEqual(redis.set.await_count, 1)

    def test_filemanager_exists_rejects_unsafe_path(self):
        manager = FileManager("/tmp/safe")
        with patch.object(
            manager, "_is_safe_path", return_value=False
        ):
            self.assertFalse(manager.exists("../outside"))

    def test_challenge_search_nonzero_contest_and_explicit_status(self):
        query = ChalSearchingParam(
            pro=None,
            acct=None,
            state=0,
            compiler=-1,
            allow_pro_statuses=[1, 2],
            contest=9,
        ).get_sql_query_str()
        self.assertIn('"contest_id"=9', query)
        self.assertIn('"problem"."status" IN (1,2)', query)

    async def test_pack_dfs_stops_after_first_illegal_file(self):
        import services.pack as module

        redis = AsyncMock()
        redis.delete.return_value = 1
        service = PackService(MagicMock(), redis)
        service._run_and_wait_process = AsyncMock(return_value=0)
        temporary = MagicMock()
        temporary.__enter__.return_value = "/tmp/work"

        def listdir(path):
            if path == "/tmp/work":
                return ["bad", "nested"]
            raise AssertionError("dfs should stop before listing nested")

        def isdir(path):
            return path.endswith("/nested")

        with (
            patch.object(
                module.tempfile,
                "TemporaryDirectory",
                return_value=temporary,
            ),
            patch.object(module.os, "remove"),
            patch.object(module.os, "listdir", side_effect=listdir),
            patch.object(module.os.path, "isdir", side_effect=isdir),
            patch.object(
                module.os.path,
                "islink",
                side_effect=lambda path: path.endswith("/bad"),
            ),
        ):
            result = await service.unpack(
                "12345678-1234-5678-1234-567812345678",
                "/dst",
            )
        self.assertEqual(result[0][0], "Eparam")

    async def test_user_impossible_motto_bound_is_documented_by_validation(self):
        service = UserService(MagicMock(), AsyncMock())
        account = SimpleNamespace(
            acct_type=999,
            name="user",
            motto="",
        )
        result = await service.update_acct(account)
        self.assertEqual(result[0][0], "Eparam")


class TestRemainingSmallHandlerEdges(
    unittest.IsolatedAsyncioTestCase
):
    async def test_index_frontend_404_and_dev_info(self):
        subject = Subject()
        subject.request = SimpleNamespace(
            headers={"req-by-frontend": "1"}
        )
        await original(IndexHandler.get)(subject, "")
        subject.render.assert_awaited_once_with(
            "404", "Page Not Found"
        )

        subject = Subject()
        await original(DevInfoHandler.get)(subject)
        subject.render.assert_awaited_once_with(
            "dev-info", "Dev Info"
        )

    async def test_bulletin_callback_register_message_unregister(self):
        callback = BulletinCallback()
        self.assertIsNone(await callback.register(object()))
        self.assertEqual(
            await callback.message(object(), {"id": 1}),
            {"id": 1},
        )
        self.assertIsNone(await callback.unregister(object()))

    async def test_log_negative_page_offset(self):
        logs = SimpleNamespace(
            get_log_type=AsyncMock(return_value=(None, [])),
            list_log=AsyncMock(
                return_value=(
                    None,
                    {"lognum": 0, "loglist": []},
                )
            ),
        )
        subject = Subject(arguments={"pageoff": "-1"})
        with patch.object(LogService, "inst", logs, create=True):
            await original(LogHandler.get)(subject)
        logs.list_log.assert_awaited_once_with(0, 50, None)

    async def test_proclass_invalid_page_offset(self):
        result = await original(ManageProClassHandler.get)(
            Subject(arguments={"pageoff": "bad"}),
            None,
        )
        self.assertEqual(result[0], "Eparam")

    async def test_pack_chunk_remove_error_and_unknown_state(self):
        subject = SimpleNamespace(
            state=PackHandler.STATE_DTAT,
            output=MagicMock(),
            remain=1,
            pack_token="token",
            write_message=MagicMock(),
        )
        with patch(
            "handlers.pack.os.remove",
            side_effect=OSError("io"),
        ):
            await PackHandler.on_message(subject, b"too large")
        subject.write_message.assert_called_with("Echunk")

        idle = SimpleNamespace(state=999)
        self.assertIsNone(
            await PackHandler.on_message(idle, b"ignored")
        )


if __name__ == "__main__":
    unittest.main()
