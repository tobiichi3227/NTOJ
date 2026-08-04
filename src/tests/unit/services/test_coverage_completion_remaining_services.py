import asyncio
import json
import pickle
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from msgpack import packb

import services.judge as judge_module
from services.judge import JudgeServerClusterService, JudgeServerService
from services.log import LogService
from services.rate import RateService
from services.user import UserService
from tests.unit.services.test_user_branches import Request, account, database


class TestCachedRateCompletion(unittest.IsolatedAsyncioTestCase):
    async def test_problem_rate_and_topcoder_cache_hits(self):
        redis = AsyncMock()
        redis.hget.side_effect = [
            packb(
                {
                    "all_chal_cnt": 8,
                    "ac_chal_cnt": 5,
                    "user_all_chal_cnt": 4,
                    "user_ac_chal_cnt": 3,
                }
            ),
            packb(17),
        ]
        service = RateService(MagicMock(), redis)

        err, rate = await service.get_pro_ac_rate(9, 2)
        self.assertIsNone(err)
        self.assertEqual(rate["ac_chal_cnt"], 5)

        err, topcoder = await service.get_pro_topcoder(9)
        self.assertIsNone(err)
        self.assertEqual(topcoder, 17)


class TestCachedUserCompletion(unittest.IsolatedAsyncioTestCase):
    async def test_info_sign_updates_changed_ip_from_cached_account(self):
        db, connection = database()
        redis = AsyncMock()
        redis.hget.return_value = packb({"time": time.time()})
        redis.get.return_value = pickle.dumps(account(lastip="10.0.0.1"))
        logs = SimpleNamespace(add_log=AsyncMock())
        service = UserService(db, redis)

        with patch.object(LogService, "inst", logs, create=True):
            result = await service.info_sign(
                Request(SimpleNamespace(remote_ip="10.0.0.2"))
            )

        self.assertEqual(result, (None, 1, "10.0.0.2"))
        logs.add_log.assert_awaited_once()
        connection.execute.assert_awaited_once()
        self.assertEqual(redis.delete.await_count, 2)

    async def test_private_account_list_keeps_mail(self):
        db, connection = database()
        connection.fetch.return_value = [
            (
                1,
                account().acct_type,
                "user",
                "user@example.com",
                "127.0.0.1",
                "",
            )
        ]
        redis = AsyncMock()
        redis.hget.return_value = None

        err, values = await UserService(db, redis).list_acct(
            private=True
        )

        self.assertIsNone(err)
        self.assertEqual(values[0].mail, "user@example.com")

    async def test_non_admin_password_change_accepts_valid_old_password(self):
        db, connection = database()
        connection.fetch.return_value = [{"password": "encoded"}]
        service = UserService(db, AsyncMock())
        with (
            patch(
                "services.user.base64.b64decode",
                return_value=b"current",
            ),
            patch(
                "services.user.bcrypt.hashpw",
                side_effect=[b"current", b"different", b"new-hash"],
            ),
            patch("services.user.bcrypt.gensalt", return_value=b"salt"),
        ):
            result = await service.update_pw(1, "old", "new", False)

        self.assertEqual(result, (None, None))
        connection.execute.assert_awaited_once()

class TestJudgeLoopCompletion(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.redis = AsyncMock()
        self.service = JudgeServerService(
            self.redis,
            "judge-a",
            "ws://judge-a/ws",
            "/codes",
            "/problems",
            3,
        )

    def tearDown(self):
        judge_module.update_chal_task_running_cnt = 0

    async def test_worker_clears_event_at_concurrency_limit_and_exits(self):
        judge_module.update_chal_task_running_cnt = (
            judge_module.MAX_UPDATE_CHAL_TASK_CNT
        )
        event = SimpleNamespace(
            wait=AsyncMock(side_effect=[True, False]),
            clear=MagicMock(),
        )
        self.service.event = event

        await self.service.update_chal_task_loop()

        event.clear.assert_called_once()

    async def test_connect_logs_bad_response_then_exits_when_status_changes(self):
        websocket = AsyncMock()

        async def read_message():
            self.service.status = False
            return "payload"

        websocket.read_message.side_effect = read_message
        self.service.response_handle = MagicMock(
            side_effect=RuntimeError("bad response")
        )

        with (
            patch.object(
                judge_module,
                "websocket_connect",
                new=AsyncMock(return_value=websocket),
            ),
            patch.object(judge_module.logger, "error") as log_error,
        ):
            await self.service.connect_server()

        log_error.assert_called_once()
        self.assertFalse(self.service.status)

    async def test_unknown_response_task_only_releases_worker_slot(self):
        judge_module.update_chal_task_running_cnt = 1

        await self.service.response_handle(
            json.dumps({"chal_id": 88, "task": "future-task"})
        )

        self.assertEqual(judge_module.update_chal_task_running_cnt, 0)
        self.assertTrue(self.service.event.is_set())

    async def test_cluster_connect_keeps_already_online_server(self):
        cluster = JudgeServerClusterService(self.redis, [])
        server = SimpleNamespace(status=True, start=AsyncMock())
        cluster.servers = [server]

        self.assertIsNone(await cluster.connect_server(0))

        server.start.assert_not_awaited()
        self.assertEqual(await cluster.queue.get(), [0, 0])


if __name__ == "__main__":
    unittest.main()
