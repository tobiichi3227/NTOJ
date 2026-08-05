"""Adversarial protocol properties for Judge responses."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from hypothesis import given, strategies as st

import services.judge as judge_module
from services.chal import ChalConst, ChalService, MessageType
from services.judge import JudgeServerService
from services.rate import RateService

json_leaf = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-10_000, max_value=10_000),
    st.text(max_size=40),
)
json_value = st.recursive(
    json_leaf,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=20), children, max_size=5),
    ),
    max_leaves=20,
)


class JudgeProtocolPropertiesTest(unittest.TestCase):
    def _service_dependencies(self):
        chal_service = SimpleNamespace(
            update_total_result=AsyncMock(),
            update_subtask_result=AsyncMock(),
            update_testdata_result=AsyncMock(),
        )
        rate_service = SimpleNamespace(
            refresh_pro_ac_rate=AsyncMock(),
            refresh_pro_topcoder=AsyncMock(),
        )
        return chal_service, rate_service

    @given(json_value)
    def test_arbitrary_json_always_releases_worker_slot(self, payload) -> None:
        async def exercise() -> None:
            rs = AsyncMock()
            service = JudgeServerService(
                rs,
                "fuzz-judge",
                "ws://judge.invalid/ws",
                "/codes",
                "/problems",
                0,
            )
            chal_service, rate_service = self._service_dependencies()
            judge_module.update_chal_task_running_cnt = 1

            with (
                patch.object(ChalService, "inst", chal_service, create=True),
                patch.object(RateService, "inst", rate_service, create=True),
                patch.object(judge_module.logger, "error"),
            ):
                await service.response_handle(json.dumps(payload))

            self.assertEqual(judge_module.update_chal_task_running_cnt, 0)
            self.assertTrue(service.event.is_set())
            self.assertGreaterEqual(service.running_chal_cnt, 0)

        asyncio.run(exercise())

    def test_summary_cannot_make_running_count_negative(self) -> None:
        async def exercise() -> None:
            rs = AsyncMock()
            service = JudgeServerService(
                rs,
                "fuzz-judge",
                "ws://judge.invalid/ws",
                "/codes",
                "/problems",
                0,
            )
            service.running_chal_cnt = 0
            service.chal_map[9] = {"pro_id": 3, "contest_id": 0}
            chal_service, rate_service = self._service_dependencies()
            judge_module.update_chal_task_running_cnt = 1
            payload = {
                "chal_id": 9,
                "task": "summary",
                "result": {
                    "total_result": {
                        "status": ChalConst.STATE_AC,
                        "time": 0,
                        "memory": 0,
                        "score": "1",
                        "ce_message": "",
                        "ie_message": "",
                        "message_type": MessageType.NONE,
                    },
                    "subtask_results": {},
                    "testdata_results": {},
                },
            }

            with (
                patch.object(ChalService, "inst", chal_service, create=True),
                patch.object(RateService, "inst", rate_service, create=True),
            ):
                await service.response_handle(json.dumps(payload))

            self.assertEqual(service.running_chal_cnt, 0)
            self.assertEqual(judge_module.update_chal_task_running_cnt, 0)
            self.assertTrue(service.event.is_set())

        asyncio.run(exercise())
