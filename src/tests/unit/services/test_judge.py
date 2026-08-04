import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import services.judge as judge_module
from services.chal import ChalConst, ChalService, MessageType
from services.judge import JudgeServerClusterService, JudgeServerService
from services.log import LogService
from services.rate import RateService


class TestJudgeServerService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rs = AsyncMock()
        self.service = JudgeServerService(
            self.rs,
            "judge-a",
            "ws://judge-a/ws",
            "/codes",
            "/problems",
            3,
        )

    async def asyncTearDown(self):
        judge_module.update_chal_task_running_cnt = 0

    async def test_start_schedules_connection_and_worker(self):
        created = []

        def capture(coro):
            created.append(coro)
            return MagicMock()

        with patch.object(asyncio, "create_task", side_effect=capture):
            await self.service.start()

        self.assertEqual(len(created), 2)
        self.assertTrue(self.service.event.is_set())
        for coro in created:
            coro.close()

    async def test_connect_failure_marks_server_offline(self):
        with patch.object(
            judge_module,
            "websocket_connect",
            new=AsyncMock(side_effect=OSError("refused")),
        ):
            await self.service.connect_server()

        self.assertFalse(self.service.status)

    async def test_connect_receives_message_then_handles_disconnect(self):
        ws = AsyncMock()
        ws.read_message.side_effect = ["payload", None]
        self.service.response_handle = MagicMock(return_value="queued-task")
        self.service.offline_notice = AsyncMock()

        with patch.object(
            judge_module, "websocket_connect", new=AsyncMock(return_value=ws)
        ):
            await self.service.connect_server()

        self.assertEqual(await self.service.queue.get(), "queued-task")
        self.service.response_handle.assert_called_once_with("payload")
        self.service.offline_notice.assert_awaited_once()
        self.assertFalse(self.service.status)
        self.assertEqual(self.service.running_chal_cnt, 0)

    async def test_execute_response_normalizes_units_and_ac_state(self):
        chal_service = MagicMock()
        chal_service.update_testdata_result = AsyncMock()
        result = {
            "id": 7,
            "status": ChalConst.STATE_AC,
            "time": 2_500_000,
            "memory": 4096,
            "message": "accepted",
            "message_type": MessageType.TEXT,
        }
        judge_module.update_chal_task_running_cnt = 1

        with patch.object(ChalService, "inst", chal_service, create=True):
            await self.service.response_handle(
                json.dumps({"chal_id": 11, "task": "execute", "testdata_result": result})
            )

        saved = chal_service.update_testdata_result.await_args.args[1]
        self.assertEqual((saved.time, saved.memory), (2, 4))
        self.assertEqual(saved.state, ChalConst.STATE_JUDGE)
        published = json.loads(self.rs.publish.await_args_list[0].args[1])
        self.assertEqual(published["status"], ChalConst.STATE_JUDGE)
        self.assertEqual(judge_module.update_chal_task_running_cnt, 0)
        self.assertTrue(self.service.event.is_set())

    async def test_scoring_response_keeps_final_state(self):
        chal_service = MagicMock()
        chal_service.update_testdata_result = AsyncMock()
        result = {
            "id": 8,
            "status": ChalConst.STATE_WA,
            "time": 8_900_000,
            "memory": 9216,
            "message": "wrong",
            "message_type": MessageType.TEXT,
        }
        judge_module.update_chal_task_running_cnt = 1

        with patch.object(ChalService, "inst", chal_service, create=True):
            await self.service.response_handle(
                json.dumps({"chal_id": 12, "task": "scoring", "testdata_result": result})
            )

        saved = chal_service.update_testdata_result.await_args.args[1]
        self.assertEqual((saved.state, saved.time, saved.memory), (ChalConst.STATE_WA, 8, 9))

    async def test_summary_updates_all_results_and_contest_caches(self):
        chal_service = MagicMock()
        chal_service.update_total_result = AsyncMock()
        chal_service.update_subtask_result = AsyncMock()
        chal_service.update_testdata_result = AsyncMock()
        rate_service = MagicMock()
        rate_service.refresh_pro_ac_rate = AsyncMock()
        rate_service.refresh_pro_topcoder = AsyncMock()
        self.service.running_chal_cnt = 2
        self.service.chal_map[13] = {"pro_id": 29, "contest_id": 5}
        judge_module.update_chal_task_running_cnt = 1
        payload = {
            "chal_id": 13,
            "task": "summary",
            "result": {
                "total_result": {
                    "status": ChalConst.STATE_CE,
                    "time": 12_000_000,
                    "memory": 6144,
                    "score": "0.25",
                    "ce_message": "compile failed",
                    "ie_message": "",
                    "message_type": MessageType.TEXT,
                },
                "subtask_results": {
                    "2": {
                        "status": ChalConst.STATE_PC,
                        "time": 10_000_000,
                        "memory": 4096,
                        "score": "0.5",
                    }
                },
                "testdata_results": {
                    "7": {
                        "id": 7,
                        "status": ChalConst.STATE_WA,
                        "time": 3_000_000,
                        "memory": 2048,
                        "message": "mismatch",
                        "message_type": MessageType.TEXT,
                    }
                },
            },
        }

        with (
            patch.object(ChalService, "inst", chal_service, create=True),
            patch.object(RateService, "inst", rate_service, create=True),
        ):
            await self.service.response_handle(json.dumps(payload))

        total = chal_service.update_total_result.await_args.args[1]
        subtask = chal_service.update_subtask_result.await_args.args[1]
        testdata = chal_service.update_testdata_result.await_args.args[1]
        self.assertEqual((total.time, total.memory, str(total.rate)), (12, 6, "0.25"))
        self.assertEqual(total.message, "compile failed")
        self.assertEqual((subtask.subtask_id, subtask.time, subtask.memory), (2, 10, 4))
        self.assertEqual((testdata.testdata_id, testdata.time, testdata.memory), (7, 3, 2))
        self.assertEqual(testdata.message_type, MessageType.TEXT)
        self.assertEqual(self.service.running_chal_cnt, 1)
        self.assertNotIn(13, self.service.chal_map)
        self.rs.hdel.assert_awaited_once_with("contest_5_scores", "29")
        topics = [call.args[0] for call in self.rs.publish.await_args_list]
        self.assertIn("contestnewchalsub", topics)
        self.assertIn("judgechalcnt_sub", topics)
        rate_service.refresh_pro_ac_rate.assert_awaited_once_with(29, 5)
        rate_service.refresh_pro_topcoder.assert_awaited_once_with(29)

    async def test_summary_internal_error_does_not_touch_contest_cache(self):
        chal_service = MagicMock()
        chal_service.update_total_result = AsyncMock()
        chal_service.update_subtask_result = AsyncMock()
        chal_service.update_testdata_result = AsyncMock()
        rate_service = MagicMock()
        rate_service.refresh_pro_ac_rate = AsyncMock()
        rate_service.refresh_pro_topcoder = AsyncMock()
        self.service.running_chal_cnt = 1
        self.service.chal_map[14] = {"pro_id": 30, "contest_id": 0}
        judge_module.update_chal_task_running_cnt = 1
        payload = {
            "chal_id": 14,
            "task": "summary",
            "result": {
                "total_result": {
                    "status": ChalConst.STATE_JE,
                    "time": 0,
                    "memory": 0,
                    "score": "0",
                    "ce_message": "",
                    "ie_message": "judge crashed",
                    "message_type": MessageType.TEXT,
                },
                "subtask_results": {},
                "testdata_results": {},
            },
        }

        with (
            patch.object(ChalService, "inst", chal_service, create=True),
            patch.object(RateService, "inst", rate_service, create=True),
        ):
            await self.service.response_handle(json.dumps(payload))

        total = chal_service.update_total_result.await_args.args[1]
        self.assertEqual(total.message, "judge crashed")
        self.rs.hdel.assert_not_awaited()
        topics = [call.args[0] for call in self.rs.publish.await_args_list]
        self.assertNotIn("contestnewchalsub", topics)

    async def test_disconnect_branches(self):
        self.service.status = False
        self.assertEqual(
            await self.service.disconnect_server(),
            ("Ejudge", "Judge already disconnected"),
        )

        self.service.status = True
        self.service.ws = MagicMock()
        self.service.main_task = MagicMock()
        self.service.loop_task = MagicMock()
        self.assertIsNone(await self.service.disconnect_server())
        self.service.ws.close.assert_called_once()
        self.assertIsNone(self.service.main_task)
        self.assertIsNone(self.service.loop_task)

        self.service.status = True
        self.service.ws = MagicMock()
        self.service.ws.close.side_effect = RuntimeError("close failed")
        self.assertEqual(
            await self.service.disconnect_server(),
            ("Ejudge", "Disconnect judge failed"),
        )

    async def test_status_send_and_offline_notice(self):
        err, status = self.service.get_server_status()
        self.assertIsNone(err)
        self.assertEqual(status["judge_id"], 3)

        self.service.ws = AsyncMock()
        data = {"chal_id": 20, "code_path": "20.cpp", "res_path": "20"}
        await self.service.send(data)
        sent = json.loads(self.service.ws.write_message.await_args.args[0])
        self.assertEqual(sent["code_path"], "/codes/20.cpp")
        self.assertEqual(sent["res_path"], "/problems/20")
        self.assertEqual(self.service.running_chal_cnt, 1)

        self.service.status = False
        await self.service.send({"chal_id": 21, "code_path": "x", "res_path": "y"})
        self.assertEqual(self.service.ws.write_message.await_count, 1)

        log_service = MagicMock()
        log_service.add_log = AsyncMock()
        with patch.object(LogService, "inst", log_service, create=True):
            await self.service.offline_notice()
        log_service.add_log.assert_awaited_once_with(
            "Judge judge-a offline", "judge.offline"
        )


class TestJudgeServerClusterService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rs = AsyncMock()

    async def test_constructor_filters_invalid_config_and_uses_default_name(self):
        cluster = JudgeServerClusterService(
            self.rs,
            [
                {},
                {"url": "ws://a", "problems_path": "/p"},
                {"url": "ws://b", "codes_path": "/c"},
                {
                    "url": "ws://ok",
                    "codes_path": "/codes",
                    "problems_path": "/problems",
                },
            ],
        )
        self.assertEqual(len(cluster.servers), 1)
        self.assertEqual(cluster.servers[0].server_name, "JudgeServer-3")
        self.assertEqual(cluster.servers[0].judge_id, 3)

    async def test_start_disconnect_all_and_status_queries(self):
        cluster = JudgeServerClusterService(self.rs, [])
        online = MagicMock()
        online.start = AsyncMock()
        online.disconnect_server = AsyncMock()
        online.get_server_status.return_value = (
            None,
            {"name": "a", "judge_id": 0, "status": True, "running_chal_cnt": 2},
        )
        offline = MagicMock()
        offline.start = AsyncMock()
        offline.disconnect_server = AsyncMock()
        offline.get_server_status.return_value = (
            None,
            {"name": "b", "judge_id": 1, "status": False, "running_chal_cnt": 0},
        )
        cluster.servers = [online, offline]

        await cluster.start()
        self.assertEqual(cluster.queue.qsize(), 2)
        self.assertTrue(cluster.is_server_online())
        self.assertEqual(len(cluster.get_servers_status()), 2)
        self.assertEqual(cluster.get_server_status(1)[1]["name"], "b")
        self.assertEqual(
            cluster.get_server_status(-1),
            (("Eparam", "Invalid judge index"), None),
        )

        await cluster.disconnect_all_server()
        online.disconnect_server.assert_awaited_once()
        offline.disconnect_server.assert_awaited_once()

        online.get_server_status.return_value = (
            None,
            {"name": "a", "judge_id": 0, "status": False, "running_chal_cnt": 0},
        )
        self.assertFalse(cluster.is_server_online())

    async def test_connect_and_disconnect_contracts(self):
        cluster = JudgeServerClusterService(self.rs, [])
        server = MagicMock()
        server.status = False
        server.start = AsyncMock()
        server.disconnect_server = AsyncMock(return_value=None)
        cluster.servers = [server]

        self.assertEqual(
            await cluster.connect_server(4), ("Eparam", "Invalid judge index")
        )
        server.start.side_effect = lambda: setattr(server, "status", True)
        self.assertIsNone(await cluster.connect_server(0))
        self.assertEqual(cluster.queue.qsize(), 1)

        self.assertEqual(
            await cluster.disconnect_server(-1), ("Eparam", "Invalid judge index")
        )
        server.disconnect_server.return_value = ("Ejudge", "failed")
        self.assertEqual(
            await cluster.disconnect_server(0), ("Ejudge", "failed")
        )
        server.disconnect_server.return_value = None
        self.assertIsNone(await cluster.disconnect_server(0))

        server.status = False
        server.start.side_effect = None
        self.assertEqual(
            await cluster.connect_server(0), ("Ejudge", "Connect judge failed")
        )

    async def test_send_skips_offline_server_and_records_challenge(self):
        cluster = JudgeServerClusterService(self.rs, [])
        offline = MagicMock()
        offline.chal_map = {}
        offline.get_server_status.return_value = (
            None,
            {"judge_id": 0, "status": False, "running_chal_cnt": 0},
        )
        online = MagicMock()
        online.chal_map = {}
        online.send = AsyncMock()
        online.get_server_status.return_value = (
            None,
            {"judge_id": 1, "status": True, "running_chal_cnt": 4},
        )
        cluster.servers = [offline, online]
        cluster.is_server_online = MagicMock(return_value=True)
        await cluster.queue.put([0, 0])
        await cluster.queue.put([1, 1])
        data = {"chal_id": 50, "code_path": "50.cpp", "res_path": "50"}

        await cluster.send(data, pro_id=8, contest_id=9)

        online.send.assert_awaited_once_with(data)
        self.assertEqual(online.chal_map[50], {"pro_id": 8, "contest_id": 9})
        self.assertEqual(await cluster.queue.get(), [4, 1])

    async def test_send_returns_when_all_offline_or_challenge_is_duplicate(self):
        cluster = JudgeServerClusterService(self.rs, [])
        cluster.is_server_online = MagicMock(return_value=False)
        await cluster.send({"chal_id": 60}, 1, 0)
        self.assertEqual(cluster.queue.qsize(), 0)

        server = MagicMock()
        server.chal_map = {60: {"pro_id": 1, "contest_id": 0}}
        server.send = AsyncMock()
        server.get_server_status.return_value = (
            None,
            {"judge_id": 0, "status": True, "running_chal_cnt": 3},
        )
        cluster.servers = [server]
        cluster.is_server_online.return_value = True
        await cluster.queue.put([3, 0])

        await cluster.send({"chal_id": 60}, 1, 0)

        server.send.assert_not_awaited()
        self.assertEqual(await cluster.queue.get(), [3, 0])


if __name__ == "__main__":
    unittest.main()
