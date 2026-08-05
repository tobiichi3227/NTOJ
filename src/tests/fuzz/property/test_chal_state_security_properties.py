"""Fail-closed properties for challenge state visibility."""

import asyncio
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, strategies as st

test_config = sys.modules.setdefault("config", SimpleNamespace())
test_config.BASE_URL = "/"
test_config.SITE_TITLE = "NTOJ Fuzz"

from handlers.chal import ChalStateCallback
from services.pro import ProService
from services.user import UserService

SECRET = "FUZZ_PRIVATE_JUDGE_MESSAGE"
small_leaf = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-100, max_value=100),
    st.text(alphabet="abc123", max_size=10),
)
malformed_sensitive_container = st.one_of(
    st.just(SECRET),
    st.lists(small_leaf, max_size=4).map(lambda values: [SECRET, *values]),
)
total_result_container = st.one_of(
    malformed_sensitive_container,
    st.builds(
        lambda extra: {
            "ce_message": SECRET,
            "ie_message": SECRET,
            "message_type": 2,
            "extra": extra,
        },
        small_leaf,
    ),
)
testdata_result_container = st.one_of(
    malformed_sensitive_container,
    st.builds(
        lambda value: {
            "1": value,
            "2": {"message": SECRET, "message_type": 2},
        },
        malformed_sensitive_container,
    ),
)


class ChalStateSecurityPropertiesTest(unittest.TestCase):
    @given(
        total_result=total_result_container,
        testdata_results=testdata_result_container,
    )
    def test_outsider_never_receives_sensitive_result_messages(
        self,
        total_result,
        testdata_results,
    ) -> None:
        async def exercise():
            callback = ChalStateCallback()
            connection = MagicMock()
            connection.acct_id = 2
            callback.conn_state[connection] = {
                "chal": SimpleNamespace(
                    chal_id=7,
                    pro_id=10,
                    acct_id=1,
                    contest_id=0,
                )
            }
            user_service = SimpleNamespace(
                info_acct=AsyncMock(
                    return_value=(
                        None,
                        SimpleNamespace(
                            acct_id=2,
                            is_kernel=lambda: False,
                        ),
                    )
                )
            )
            pro_service = SimpleNamespace(get_pro=AsyncMock(return_value=(None, object())))
            payload = {
                "chal_id": 7,
                "total_result": total_result,
                "testdata_results": testdata_results,
                "message": SECRET,
                "message_type": 2,
            }

            with (
                patch.object(UserService, "inst", user_service, create=True),
                patch.object(ProService, "inst", pro_service, create=True),
            ):
                return await callback.message(connection, json.dumps(payload))

        result = asyncio.run(exercise())
        self.assertIsNotNone(result)
        self.assertNotIn(SECRET, result)

    @given(st.one_of(small_leaf, st.lists(small_leaf, max_size=5)))
    def test_non_object_json_is_ignored(self, payload) -> None:
        async def exercise():
            callback = ChalStateCallback()
            connection = MagicMock()
            callback.conn_state[connection] = {"chal": SimpleNamespace(chal_id=7)}
            return await callback.message(connection, json.dumps(payload))

        self.assertIsNone(asyncio.run(exercise()))
