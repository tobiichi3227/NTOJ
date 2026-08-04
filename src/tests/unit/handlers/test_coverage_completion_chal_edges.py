import json
import unittest
from types import SimpleNamespace

from handlers.chal import ChalHandler, ChalListHandler, ChalStateCallback
from services.chal import ChalConst, ChalSearchingParamBuilder, TestdataResult, MessageType
from services.contests import ChallengeResultStyle
from services.pro import ProConst
from tests.unit.handlers.test_chal_callbacks import (
    CallbackTestCase,
    account,
    challenge,
    contest,
)
from tests.unit.handlers.test_chal_handlers import (
    Subject,
    challenge as handler_challenge,
    contest as handler_contest,
    original,
)


class TestChallengeCallbackCompletion(CallbackTestCase):
    def summary(self):
        return json.dumps(
            {
                "chal_id": 7,
                "total_result": {
                    "state": ChalConst.STATE_AC,
                    "ce_message": "secret",
                    "ie_message": "secret",
                    "message_type": MessageType.TEXT.value,
                },
                "testdata_results": {
                    "1": {"status": ChalConst.STATE_AC},
                    "bad": {"status": ChalConst.STATE_WA},
                },
                "subtask_results": {
                    "1": {"state": ChalConst.STATE_AC},
                    "bad": {"state": ChalConst.STATE_WA},
                },
            }
        )

    def prepare(self, *, style, system_test=True):
        callback = ChalStateCallback()
        conn = self.connection(2)
        callback.conn_state[conn] = {
            "chal": challenge(owner=2, contest_id=4)
        }
        self.user_service.info_acct.return_value = (
            None,
            account(2),
        )
        value = contest(
            running=True,
            style=style,
            system_test=system_test,
        )
        self.contest_service.get_contest.return_value = (
            None,
            value,
        )
        problem = self.problem_with_system_flags()
        self.pro_service.get_pro.return_value = (
            None,
            problem,
        )
        return callback, conn, value, problem

    async def test_sanitize_fallback_also_scrubs_total_result(self):
        callback = ChalStateCallback()
        conn = self.connection(2)
        callback.conn_state[conn] = {
            "chal": challenge(owner=1)
        }
        self.user_service.info_acct.return_value = (
            None,
            account(2),
        )
        raw = json.dumps(
            {
                "chal_id": 7,
                "total_result": {
                    "ce_message": "compiler secret",
                    "ie_message": "internal secret",
                    "message_type": MessageType.TEXT.value,
                },
                "testdata_results": [],
                "message": "summary secret",
            }
        )
        payload = json.loads(await callback.message(conn, raw))
        self.assertEqual(payload["message"], "")
        self.assertEqual(
            payload["total_result"]["ce_message"],
            "",
        )
        self.assertEqual(
            payload["total_result"]["ie_message"],
            "",
        )
        self.assertEqual(
            payload["total_result"]["message_type"],
            MessageType.NONE.value,
        )

    async def test_state_count_nested_contest_and_problem_errors(self):
        callback, conn, value, problem = self.prepare(
            style=ChallengeResultStyle.STATE_COUNT
        )
        self.chal_service.get_testdata_results.return_value = (
            None,
            {
                1: TestdataResult(
                    1,
                    ChalConst.STATE_AC,
                    1,
                    1,
                    "",
                    MessageType.NONE,
                )
            },
        )
        single = json.dumps(
            {"chal_id": 7, "id": 1, "status": 1}
        )

        self.contest_service.get_contest.side_effect = [
            (None, value),
            (("Edb", "contest"), None),
        ]
        self.assertIsNone(await callback.message(conn, single))

        self.contest_service.get_contest.side_effect = None
        self.contest_service.get_contest.return_value = (
            None,
            value,
        )
        self.pro_service.get_pro.side_effect = [
            (None, problem),
            (None, problem),
            (("Edb", "problem"), None),
        ]
        self.assertIsNone(await callback.message(conn, single))


    async def test_filter_bad_single_id_and_missing_problem(self):
        callback, conn, value, problem = self.prepare(
            style=ChallengeResultStyle.FULL
        )
        bad_single = json.dumps(
            {"chal_id": 7, "id": "bad", "status": 1}
        )
        payload = json.loads(
            await callback.message(conn, bad_single)
        )
        self.assertEqual(payload["id"], "bad")

        self.pro_service.get_pro.side_effect = [
            (None, problem),
            (("Edb", "problem"), None),
        ]
        payload = json.loads(
            await callback.message(
                conn,
                json.dumps(
                    {"chal_id": 7, "id": 1, "status": 1}
                ),
            )
        )
        self.assertEqual(payload["id"], 1)

    async def test_duplicate_state_count_and_ended_owner(self):
        callback, conn, value, _ = self.prepare(
            style=ChallengeResultStyle.STATE_COUNT,
            system_test=False,
        )
        self.chal_service.get_testdata_results.return_value = (
            None,
            {
                1: TestdataResult(
                    1,
                    ChalConst.STATE_AC,
                    1,
                    1,
                    "",
                    MessageType.NONE,
                ),
                2: TestdataResult(
                    2,
                    ChalConst.STATE_AC,
                    1,
                    1,
                    "",
                    MessageType.NONE,
                ),
            },
        )
        payload = json.loads(
            await callback.message(
                conn,
                json.dumps(
                    {"chal_id": 7, "id": 1, "status": 1}
                ),
            )
        )
        self.assertEqual(
            payload["state_count"][str(ChalConst.STATE_AC)],
            2,
        )

        callback.conn_state[conn] = {
            "chal": challenge(owner=2, contest_id=4)
        }
        ended = contest(
            ended=True,
            style=ChallengeResultStyle.FULL,
        )
        self.contest_service.get_contest.return_value = (
            None,
            ended,
        )
        self.pro_service.get_pro.side_effect = None
        self.pro_service.get_pro.return_value = (
            None,
            self.problem_with_system_flags(),
        )
        payload = json.loads(
            await callback.message(conn, self.summary())
        )
        self.assertEqual(payload["chal_id"], 7)


    async def test_sanitize_without_optional_message_fields(self):
        callback = ChalStateCallback()
        conn = self.connection(2)
        callback.conn_state[conn] = {
            "chal": challenge(owner=1)
        }
        self.user_service.info_acct.return_value = (
            None,
            account(2),
        )

        message_only = json.loads(
            await callback.message(
                conn,
                json.dumps(
                    {"chal_id": 7, "message": "secret"}
                ),
            )
        )
        self.assertEqual(message_only["message"], "")

        malformed_testdata = json.loads(
            await callback.message(
                conn,
                json.dumps(
                    {
                        "chal_id": 7,
                        "total_result": {
                            "ce_message": "secret",
                            "ie_message": "secret",
                        },
                        "testdata_results": [],
                    }
                ),
            )
        )
        self.assertEqual(
            malformed_testdata["total_result"]["ce_message"],
            "",
        )

    async def test_style_payloads_without_optional_sections(self):
        cases = (
            (
                ChallengeResultStyle.TOTAL_ONLY,
                {"chal_id": 7},
            ),
            (
                ChallengeResultStyle.SUBTASK_ONLY,
                {"chal_id": 7},
            ),
            (
                ChallengeResultStyle.SUBTASK_ONLY,
                {"chal_id": 7, "total_result": {}},
            ),
            (
                ChallengeResultStyle.STATE_COUNT,
                {"chal_id": 7},
            ),
            (
                ChallengeResultStyle.STATE_COUNT,
                {"chal_id": 7, "total_result": {}},
            ),
            (
                999,
                {"chal_id": 7},
            ),
        )
        for style, payload in cases:
            with self.subTest(style=style, payload=payload):
                callback, conn, _, _ = self.prepare(
                    style=style,
                    system_test=False,
                )
                result = await callback.message(
                    conn, json.dumps(payload)
                )
                self.assertEqual(json.loads(result)["chal_id"], 7)

        callback, conn, _, _ = self.prepare(
            style=ChallengeResultStyle.FULL,
            system_test=True,
        )
        result = await callback.message(
            conn,
            json.dumps(
                {"chal_id": 7, "total_result": {}}
            ),
        )
        self.assertEqual(json.loads(result)["chal_id"], 7)

    async def test_state_count_nested_noncontest_guard(self):
        callback = ChalStateCallback()
        conn = self.connection(2)
        item = challenge(owner=2, contest_id=4)
        callback.conn_state[conn] = {"chal": item}
        self.user_service.info_acct.return_value = (
            None,
            account(2),
        )
        self.contest_service.get_contest.return_value = (
            None,
            contest(
                running=True,
                style=ChallengeResultStyle.STATE_COUNT,
                system_test=False,
            ),
        )

        async def detach_contest_while_loading_results(_):
            item.contest_id = 0
            return (
                None,
                {
                    1: TestdataResult(
                        1,
                        ChalConst.STATE_AC,
                        1,
                        1,
                        "",
                        MessageType.NONE,
                    )
                },
            )

        self.chal_service.get_testdata_results.side_effect = (
            detach_contest_while_loading_results
        )

        payload = json.loads(
            await callback.message(
                conn,
                json.dumps(
                    {"chal_id": 7, "id": 1, "status": 1}
                ),
            )
        )

        self.assertEqual(
            payload["state_count"],
            {str(ChalConst.STATE_AC): 1},
        )

    async def test_restored_filters_handle_system_and_malformed_keys(self):
        payload = json.dumps(
            {
                "chal_id": 7,
                "total_result": {"state": ChalConst.STATE_AC},
                "testdata_results": {
                    "1": {"status": ChalConst.STATE_AC},
                    "2": {"status": ChalConst.STATE_AC},
                    "bad": {"status": ChalConst.STATE_WA},
                },
                "subtask_results": {
                    "1": {"state": ChalConst.STATE_AC},
                    "2": {"state": ChalConst.STATE_AC},
                    "bad": {"state": ChalConst.STATE_WA},
                },
            }
        )

        for style in (
            ChallengeResultStyle.SUBTASK_ONLY,
            ChallengeResultStyle.FULL,
        ):
            with self.subTest(style=style):
                callback, conn, _, problem = self.prepare(
                    style=style,
                    system_test=True,
                )
                self.pro_service.get_pro.reset_mock(
                    side_effect=True
                )
                self.pro_service.get_pro.side_effect = [
                    (None, object()),
                    (("Einternal", "outer reload failed"), None),
                    (None, problem),
                ]

                result = json.loads(
                    await callback.message(conn, payload)
                )

                self.assertEqual(
                    set(result["subtask_results"]),
                    {"1"},
                )
                if style == ChallengeResultStyle.FULL:
                    self.assertEqual(
                        set(result["testdata_results"]),
                        {"1"},
                    )

class TestChallengeListAndPageCompletion(
    unittest.IsolatedAsyncioTestCase
):
    def test_non_admin_apply_and_post_contest_paths(self):
        subject = Subject(contest=handler_contest())
        subject.contest.is_admin.return_value = False
        subject.contest.is_start.return_value = True
        subject.contest.is_running.return_value = False
        subject.contest.is_public_scoreboard = True

        builder = ChalSearchingParamBuilder()
        result = ChalListHandler._apply_contest_filters(
            subject,
            builder,
            [7, 8, 10],
            False,
        )
        self.assertEqual(result, [7, 8, 10])

        subject.contest.is_admin.side_effect = (
            lambda acct_id=None, **_: acct_id == 8
        )
        result = ChalListHandler._get_non_admin_contest_accounts(
            subject,
            [7, 8, 10],
        )
        self.assertEqual(result, [7, 10])

    async def test_before_contest_non_admin_owner_and_private_own_view(self):
        from unittest.mock import AsyncMock, patch

        from services.chal import ChalService
        from services.pro import ProService

        challenges = SimpleNamespace(get_chal=AsyncMock())
        problems = SimpleNamespace(get_pro=AsyncMock())
        problem = SimpleNamespace(
            pro_id=5,
            config=SimpleNamespace(subtask_configs={}),
        )
        problems.get_pro.return_value = (None, problem)

        with (
            patch.object(
                ChalService, "inst", challenges, create=True
            ),
            patch.object(
                ProService, "inst", problems, create=True
            ),
        ):
            value = handler_contest()
            value.is_start.return_value = False
            value.is_running.return_value = False
            value.is_public_scoreboard = True
            value.is_admin.return_value = False
            challenges.get_chal.return_value = (
                None,
                handler_challenge(owner=7, contest_id=9),
            )
            subject = Subject(contest=value)
            await original(ChalHandler.get)(subject, "12")
            subject.render.assert_awaited_once()

            value = handler_contest()
            value.is_start.return_value = True
            value.is_running.return_value = False
            value.is_public_scoreboard = False
            value.is_admin.return_value = False
            challenges.get_chal.return_value = (
                None,
                handler_challenge(owner=7, contest_id=9),
            )
            subject = Subject(contest=value)
            await original(ChalHandler.get)(subject, "12")
            subject.render.assert_awaited_once()
            problems.get_pro.assert_awaited_with(
                5,
                ProConst.PRO_STATUS_CONTEST_USER,
            )


if __name__ == "__main__":
    unittest.main()
