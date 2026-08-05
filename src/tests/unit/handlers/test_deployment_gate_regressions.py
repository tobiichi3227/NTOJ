import datetime
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import services.judge as judge_module
from handlers.chal import ChalStateCallback
from handlers.prospec.batch.submit import BatchSubmitHandler
from services.chal import Compiler
from services.filemanager import FileManager
from services.judge import JudgeServerService
from tests.unit.handlers.test_batch_submit import Subject, problem
from tests.unit.handlers.test_chal_callbacks import CallbackTestCase, challenge
from utils.numeric import parse_str_to_list


class TestChallengePayloadRegression(CallbackTestCase):
    async def test_state_callback_rejects_invalid_and_non_object_json(self):
        callback = ChalStateCallback()
        connection = self.connection(2)
        callback.conn_state[connection] = {"chal": challenge(owner=1)}

        for payload in ("{", None, "[]", '"text"', "1"):
            with self.subTest(payload=payload):
                self.assertIsNone(await callback.message(connection, payload))


class TestSubmitGuardRegression(unittest.IsolatedAsyncioTestCase):
    async def test_lock_contention_returns_busy_without_releasing_another_lock(self):
        subject = Subject()
        subject.rs.set.return_value = False

        with (
            patch(
                "handlers.prospec.batch.submit.SUBMIT_GUARD_LOCK_RETRIES",
                2,
            ),
            patch(
                "handlers.prospec.batch.submit.asyncio.sleep",
                new_callable=AsyncMock,
            ) as sleep,
        ):
            result = await BatchSubmitHandler._is_allow_submit(
                subject,
                "code",
                Compiler.GPP,
                problem(),
            )

        self.assertEqual(
            result,
            ("Einternal", "Submit check is busy, please retry"),
        )
        self.assertEqual(subject.rs.set.await_count, 2)
        self.assertEqual(sleep.await_count, 2)
        subject.rs.eval.assert_not_awaited()

    async def test_contest_nonmember_checks_duplicates_without_cooldown(self):
        contest = MagicMock(
            contest_id=22,
            submission_cd_time=5,
            allow_compilers={Compiler.GPP},
            contest_start=datetime.datetime(2025, 1, 1),
            contest_end=datetime.datetime(2025, 1, 1, 2),
        )
        contest.member_is_status.return_value = False
        subject = Subject(contest=contest)
        subject.rs.set.return_value = True
        subject.rs.sismember.return_value = False

        self.assertIsNone(
            await BatchSubmitHandler._is_allow_submit(
                subject,
                "contest code",
                Compiler.GPP,
                problem(),
            )
        )

        subject.rs.get.assert_not_awaited()
        subject.rs.sadd.assert_awaited_once()
        subject.rs.expire.assert_awaited_once()
        subject.rs.eval.assert_awaited_once()


class TestFileManagerRegression(unittest.TestCase):
    def test_path_resolution_errors_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FileManager(directory)

            with patch(
                "services.filemanager.os.path.abspath",
                side_effect=OSError("unresolvable"),
            ):
                self.assertFalse(manager._is_safe_path("file.txt"))

            with patch(
                "services.filemanager.os.path.exists",
                side_effect=OSError("unreadable"),
            ):
                self.assertFalse(manager._is_safe_path("file.txt"))


class TestJudgeResponseRegression(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_response_releases_the_global_worker_slot(self):
        service = JudgeServerService(
            AsyncMock(),
            "judge-a",
            "ws://judge-a/ws",
            "/codes",
            "/problems",
            3,
        )
        service.event.clear()
        judge_module.update_chal_task_running_cnt = 0
        self.addAsyncCleanup(self._reset_worker_count)

        with patch.object(judge_module.logger, "error") as log_error:
            await service.response_handle("not-json")

        log_error.assert_called_once()
        self.assertEqual(judge_module.update_chal_task_running_cnt, 0)
        self.assertTrue(service.event.is_set())

    async def _reset_worker_count(self):
        judge_module.update_chal_task_running_cnt = 0


class TestNumericParserRegression(unittest.TestCase):
    def test_limits_and_unicode_numeric_input(self):
        with self.assertRaisesRegex(ValueError, "must not be negative"):
            parse_str_to_list("1", max_items=-1)

        self.assertEqual(parse_str_to_list("²"), [])

        with self.assertRaisesRegex(ValueError, "exceeds"):
            parse_str_to_list("1-3", max_items=2)


if __name__ == "__main__":
    unittest.main()
