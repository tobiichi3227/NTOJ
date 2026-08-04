import datetime
import decimal
import json
import sys
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

test_config = sys.modules.setdefault("config", SimpleNamespace())
test_config.BASE_URL = "/"
test_config.SITE_TITLE = "NTOJ Test"

from handlers.chal import (
    ChalListCallback,
    ChalListStateCallback,
    ChalStateCallback,
    _Encoder,
)
from services.chal import (
    Challenge,
    ChalConst,
    Compiler,
    MessageType,
    TestdataResult,
    TotalResult,
)
from services.contests import ChallengeResultStyle, ContestService
from services.pro import ProConst, ProService
from services.user import Account, UserConst, UserService


def account(acct_id=1, acct_type=UserConst.ACCTTYPE_USER):
    return Account(
        acct_id=acct_id,
        acct_type=acct_type,
        mail=f"user{acct_id}@example.com",
        name=f"user{acct_id}",
        photo="",
        cover="",
        motto="",
        lastip="127.0.0.1",
        last_compiler=Compiler.GPP,
        proclass_collection=[],
        specific_ip="",
    )


def challenge(*, owner=1, contest_id=0):
    return Challenge(
        chal_id=7,
        pro_id=10,
        acct_id=owner,
        contest_id=contest_id,
        acct_name=f"user{owner}",
        compiler_type=Compiler.GPP,
        timestamp=datetime.datetime.now(datetime.UTC),
        total_result=None,
        subtask_results=None,
        testdata_results=None,
    )


def contest(
    *,
    running=False,
    ended=False,
    public=False,
    admin_ids=(),
    style=ChallengeResultStyle.FULL,
    system_test=False,
):
    value = MagicMock()
    value.enable_system_test = system_test
    value.is_public_scoreboard = public
    value.pro_list = {10: {"challenge_style": style}}
    value.is_running.return_value = running
    value.is_end.return_value = ended
    value.is_admin.side_effect = (
        lambda acct=None, acct_id=None: (
            acct_id if acct_id is not None else acct.acct_id
        )
        in admin_ids
    )
    return value


class TestEncoderAndListCallback(unittest.IsolatedAsyncioTestCase):
    async def test_list_callback_lifecycle_and_encoder(self):
        callback = ChalListCallback()
        conn = object()
        self.assertIsNone(await callback.register(conn))
        self.assertEqual(await callback.message(conn, "payload"), "payload")
        self.assertIsNone(await callback.unregister(conn))

        @dataclass
        class Value:
            count: int

        encoded = json.dumps(
            {"decimal": decimal.Decimal("1.25"), "dataclass": Value(2)},
            cls=_Encoder,
        )
        self.assertEqual(
            json.loads(encoded), {"decimal": "1.25", "dataclass": {"count": 2}}
        )
        with self.assertRaises(TypeError):
            json.dumps({"unsupported": object()}, cls=_Encoder)


class CallbackTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.user_service = SimpleNamespace(info_acct=AsyncMock())
        self.pro_service = SimpleNamespace(
            get_pro=AsyncMock(return_value=(None, object()))
        )
        self.chal_service = SimpleNamespace(
            get_chal=AsyncMock(),
            get_total_result=AsyncMock(
                return_value=(
                    None,
                    TotalResult(
                        ChalConst.STATE_AC,
                        1,
                        2,
                        decimal.Decimal("1.0"),
                        "ok",
                        MessageType.TEXT,
                    ),
                )
            ),
            get_testdata_results=AsyncMock(),
        )
        self.contest_service = SimpleNamespace(get_contest=AsyncMock())
        self.patchers = [
            patch.object(UserService, "inst", self.user_service, create=True),
            patch.object(ProService, "inst", self.pro_service, create=True),
            patch("handlers.chal.ChalService.inst", self.chal_service, create=True),
            patch.object(ContestService, "inst", self.contest_service, create=True),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def connection(self, acct_id=1):
        conn = MagicMock()
        conn.acct_id = acct_id
        return conn

    def problem_with_system_flags(self):
        ordinary = MagicMock()
        ordinary.is_system_test.return_value = False
        system = MagicMock()
        system.is_system_test.return_value = True
        return SimpleNamespace(
            config=SimpleNamespace(
                testdatas={1: ordinary, 2: system},
                subtask_configs={1: ordinary, 2: system},
            )
        )


class TestChalListStateCallback(CallbackTestCase):
    async def test_registration_initialization_and_custom_messages(self):
        callback = ChalListStateCallback()
        conn = self.connection()
        await callback.register(conn)
        self.assertEqual(callback.conn_state[conn], {"chals": {}})

        first = challenge()
        self.chal_service.get_chal.side_effect = [
            (None, first),
            (("Enoext", "missing"), None),
        ]
        await callback.init(conn, [7, 8])
        self.assertIs(callback.conn_state[conn]["chals"][7], first)
        self.assertIsNone(callback.conn_state[conn]["chals"][8])

        other_conn = self.connection(2)
        self.chal_service.get_chal.side_effect = None
        self.chal_service.get_chal.return_value = (None, first)
        self.assertTrue(
            await callback.handle_custom_message(
                other_conn, "challiststatesub_init", '{"chalids":[7]}'
            )
        )
        self.assertIn(7, callback.conn_state[other_conn]["chals"])
        self.assertTrue(
            await callback.handle_custom_message(
                conn, "challiststatesub_init", "not-json"
            )
        )
        self.assertFalse(await callback.handle_custom_message(conn, "unknown", "{}"))

        await callback.unregister(conn)
        self.assertNotIn(conn, callback.conn_state)
        await callback.unregister(conn)

    async def test_normal_and_rejected_dependency_paths(self):
        callback = ChalListStateCallback()
        conn = self.connection(2)
        item = challenge(owner=1)

        self.assertIsNone(await callback.message(conn, "7"))
        callback.conn_state[conn] = {"chals": {7: item}}

        self.user_service.info_acct.return_value = (("Enoext", "missing"), None)
        self.assertIsNone(await callback.message(conn, "7"))

        self.user_service.info_acct.return_value = (None, account(2))
        self.pro_service.get_pro.return_value = (("Eacces", "hidden"), None)
        self.assertIsNone(await callback.message(conn, "7"))

        self.pro_service.get_pro.return_value = (None, object())
        payload = json.loads(await callback.message(conn, "7"))
        self.assertEqual(payload["chal_id"], 7)
        self.assertEqual(payload["rate"], "1.0")
        self.pro_service.get_pro.assert_awaited_with(
            10, ProConst.PRO_STATUS_NORMAL_USER
        )

        self.user_service.info_acct.return_value = (
            None,
            account(2, UserConst.ACCTTYPE_KERNEL),
        )
        await callback.message(conn, "7")
        self.pro_service.get_pro.assert_awaited_with(10, ProConst.PRO_STATUS_FULL)

    async def test_contest_visibility_matrix(self):
        callback = ChalListStateCallback()
        conn = self.connection(2)
        callback.conn_state[conn] = {"chals": {7: challenge(owner=2, contest_id=4)}}
        self.user_service.info_acct.return_value = (None, account(2))
        self.pro_service.get_pro.return_value = (None, object())

        self.contest_service.get_contest.return_value = (("Enoext", "missing"), None)
        self.assertIsNone(await callback.message(conn, "7"))

        for value in (
            contest(admin_ids=(2,)),
            contest(running=True),
            contest(ended=True),
        ):
            with self.subTest(value=value):
                self.contest_service.get_contest.return_value = (None, value)
                self.assertIsNotNone(await callback.message(conn, "7"))

        callback.conn_state[conn] = {"chals": {7: challenge(owner=1, contest_id=4)}}
        cases = [
            (contest(running=True), False),
            (contest(ended=True, public=True), True),
            (contest(ended=True, public=True, admin_ids=(1,)), False),
            (contest(ended=True, public=False), False),
            (contest(), False),
        ]
        for value, visible in cases:
            with self.subTest(value=value, visible=visible):
                self.contest_service.get_contest.return_value = (None, value)
                self.assertEqual(await callback.message(conn, "7") is not None, visible)

        self.pro_service.get_pro.assert_awaited_with(
            10, ProConst.PRO_STATUS_CONTEST_USER
        )


class TestChalStateCallback(CallbackTestCase):
    async def test_registration_initialization_and_dependency_failures(self):
        callback = ChalStateCallback()
        conn = self.connection(2)
        await callback.register(conn)
        self.assertIsNone(await callback.message(conn, '{"chal_id":7}'))

        item = challenge(owner=1)
        self.chal_service.get_chal.return_value = (None, item)
        self.assertTrue(
            await callback.handle_custom_message(conn, "chalstatesub_init", "7")
        )
        self.assertIs(callback.conn_state[conn]["chal"], item)
        self.assertFalse(await callback.handle_custom_message(conn, "unknown", "7"))
        self.assertTrue(
            await callback.handle_custom_message(conn, "chalstatesub_init", "bad")
        )

        other = self.connection(3)
        self.chal_service.get_chal.return_value = (("Enoext", "missing"), None)
        self.assertTrue(
            await callback.handle_custom_message(other, "chalstatesub_init", "8")
        )
        self.assertIsNone(callback.conn_state[other]["chal"])

        callback.conn_state[conn]["chal"] = item
        self.assertIsNone(await callback.message(conn, '{"chal_id":8}'))
        self.user_service.info_acct.return_value = (("Enoext", "missing"), None)
        self.assertIsNone(await callback.message(conn, '{"chal_id":7}'))
        self.user_service.info_acct.return_value = (None, account(2))
        self.pro_service.get_pro.return_value = (("Eacces", "hidden"), None)
        self.assertIsNone(await callback.message(conn, '{"chal_id":7}'))

        await callback.unregister(conn)
        self.assertNotIn(conn, callback.conn_state)
        await callback.unregister(conn)

    async def test_normal_visibility_and_fail_safe_sanitizing(self):
        callback = ChalStateCallback()
        conn = self.connection(2)
        callback.conn_state[conn] = {"chal": challenge(owner=1)}
        self.pro_service.get_pro.return_value = (None, object())

        raw = json.dumps(
            {
                "chal_id": 7,
                "total_result": {
                    "ce_message": "secret",
                    "ie_message": "internal",
                    "message_type": 2,
                },
                "testdata_results": {
                    "1": {"message": "checker", "message_type": 2},
                    "2": "ignored",
                },
                "message": "summary",
                "message_type": 2,
            }
        )
        self.user_service.info_acct.return_value = (None, account(2))
        sanitized = json.loads(await callback.message(conn, raw))
        self.assertEqual(sanitized["total_result"]["ce_message"], "")
        self.assertEqual(sanitized["testdata_results"]["1"]["message"], "")
        self.assertEqual(sanitized["message"], "")

        malformed = json.dumps({"chal_id": 7, "total_result": [], "message": "secret"})
        sanitized = json.loads(await callback.message(conn, malformed))
        self.assertEqual(sanitized["message"], "")

        callback.conn_state[conn] = {"chal": challenge(owner=2)}
        self.assertEqual(await callback.message(conn, raw), raw)
        self.user_service.info_acct.return_value = (
            None,
            account(2, UserConst.ACCTTYPE_KERNEL),
        )
        callback.conn_state[conn] = {"chal": challenge(owner=1)}
        self.assertEqual(await callback.message(conn, raw), raw)

    async def test_contest_total_and_subtask_styles(self):
        callback = ChalStateCallback()
        conn = self.connection(2)
        callback.conn_state[conn] = {"chal": challenge(owner=2, contest_id=4)}
        self.user_service.info_acct.return_value = (None, account(2))
        self.pro_service.get_pro.return_value = (None, self.problem_with_system_flags())

        summary = json.dumps(
            {
                "chal_id": 7,
                "total_result": {"state": ChalConst.STATE_AC},
                "subtask_results": {"1": {"state": 1}, "2": {"state": 1}, "bad": {}},
                "testdata_results": {"1": {"status": 1}, "2": {"status": 3}},
            }
        )
        single = json.dumps({"chal_id": 7, "id": 1, "status": ChalConst.STATE_AC})

        value = contest(running=True, style=ChallengeResultStyle.TOTAL_ONLY)
        self.contest_service.get_contest.return_value = (None, value)
        payload = json.loads(await callback.message(conn, summary))
        self.assertEqual(set(payload), {"chal_id", "total_result"})
        self.assertIsNone(await callback.message(conn, single))

        value = contest(
            running=True, style=ChallengeResultStyle.SUBTASK_ONLY, system_test=True
        )
        self.contest_service.get_contest.return_value = (None, value)
        payload = json.loads(await callback.message(conn, summary))
        self.assertNotIn("testdata_results", payload)
        self.assertEqual(set(payload["subtask_results"]), {"1"})
        self.assertIsNone(await callback.message(conn, single))

        self.contest_service.get_contest.return_value = (("Enoext", "missing"), None)
        self.assertIsNone(await callback.message(conn, summary))

    async def test_state_count_style_for_single_and_summary_updates(self):
        callback = ChalStateCallback()
        conn = self.connection(2)
        callback.conn_state[conn] = {"chal": challenge(owner=2, contest_id=4)}
        self.user_service.info_acct.return_value = (None, account(2))
        self.pro_service.get_pro.return_value = (None, self.problem_with_system_flags())
        self.chal_service.get_testdata_results.return_value = (
            None,
            {
                1: TestdataResult(1, ChalConst.STATE_AC, 1, 1, "", MessageType.NONE),
                2: TestdataResult(2, ChalConst.STATE_WA, 1, 1, "", MessageType.NONE),
            },
        )
        value = contest(
            running=True, style=ChallengeResultStyle.STATE_COUNT, system_test=True
        )
        self.contest_service.get_contest.return_value = (None, value)

        payload = json.loads(
            await callback.message(
                conn, json.dumps({"chal_id": 7, "id": 1, "status": 1})
            )
        )
        self.assertEqual(payload["state_count"], {str(ChalConst.STATE_AC): 1})

        summary = json.dumps(
            {
                "chal_id": 7,
                "total_result": {"state": 1},
                "testdata_results": {
                    "1": {"status": 1},
                    "2": {"status": 1},
                    "bad": {},
                    "text": "skip",
                },
            }
        )
        payload = json.loads(await callback.message(conn, summary))
        self.assertEqual(payload["testdata_results"]["state_count"], {"1": 1})

        value = contest(running=True, style=ChallengeResultStyle.STATE_COUNT)
        self.contest_service.get_contest.return_value = (None, value)
        payload = json.loads(await callback.message(conn, summary))
        self.assertEqual(payload["testdata_results"]["state_count"], {"1": 2})

    async def test_restored_style_filters_fail_closed_when_problem_reload_fails(self):
        summary = json.dumps(
            {
                "chal_id": 7,
                "total_result": {"state": 1},
                "testdata_results": {"1": {"status": 1}, "2": {"status": 1}},
                "subtask_results": {"1": {"state": 1}, "2": {"state": 1}},
            }
        )

        for style in (ChallengeResultStyle.SUBTASK_ONLY, ChallengeResultStyle.FULL):
            with self.subTest(style=style):
                callback = ChalStateCallback()
                conn = self.connection(2)
                callback.conn_state[conn] = {"chal": challenge(owner=2, contest_id=4)}
                self.user_service.info_acct.return_value = (None, account(2))
                value = contest(running=True, style=style, system_test=True)
                self.contest_service.get_contest.reset_mock(side_effect=True)
                self.contest_service.get_contest.return_value = (None, value)
                self.pro_service.get_pro.reset_mock(side_effect=True)
                self.pro_service.get_pro.side_effect = [
                    (None, object()),
                    (None, self.problem_with_system_flags()),
                    (("Einternal", "problem reload failed"), None),
                ]

                self.assertIsNone(await callback.message(conn, summary))
                self.assertEqual(self.pro_service.get_pro.await_count, 3)

    async def test_restored_style_filters_fail_closed_when_contest_reload_fails(self):
        summary = json.dumps(
            {
                "chal_id": 7,
                "total_result": {"state": 1},
                "testdata_results": {"1": {"status": 1}, "2": {"status": 1}},
                "subtask_results": {"1": {"state": 1}, "2": {"state": 1}},
            }
        )

        for style in (ChallengeResultStyle.SUBTASK_ONLY, ChallengeResultStyle.FULL):
            with self.subTest(style=style):
                callback = ChalStateCallback()
                conn = self.connection(2)
                callback.conn_state[conn] = {"chal": challenge(owner=2, contest_id=4)}
                self.user_service.info_acct.return_value = (None, account(2))
                value = contest(running=True, style=style, system_test=True)
                self.contest_service.get_contest.reset_mock(side_effect=True)
                self.contest_service.get_contest.side_effect = [
                    (None, value),
                    (("Einternal", "contest reload failed"), None),
                ]
                self.pro_service.get_pro.reset_mock(side_effect=True)
                self.pro_service.get_pro.side_effect = [
                    (None, object()),
                    (None, self.problem_with_system_flags()),
                ]

                self.assertIsNone(await callback.message(conn, summary))
                self.assertEqual(self.contest_service.get_contest.await_count, 2)

    async def test_restored_style_filters_preserve_results_when_system_test_is_disabled(
        self,
    ):
        summary = json.dumps(
            {
                "chal_id": 7,
                "total_result": {"state": 1},
                "testdata_results": {"1": {"status": 1}, "2": {"status": 1}},
                "subtask_results": {"1": {"state": 1}, "2": {"state": 1}},
            }
        )

        for style in (ChallengeResultStyle.SUBTASK_ONLY, ChallengeResultStyle.FULL):
            with self.subTest(style=style):
                callback = ChalStateCallback()
                conn = self.connection(2)
                callback.conn_state[conn] = {"chal": challenge(owner=2, contest_id=4)}
                self.user_service.info_acct.return_value = (None, account(2))
                value = contest(running=True, style=style, system_test=False)
                self.contest_service.get_contest.reset_mock(side_effect=True)
                self.contest_service.get_contest.return_value = (None, value)
                self.pro_service.get_pro.reset_mock(side_effect=True)
                self.pro_service.get_pro.return_value = (None, object())

                payload = json.loads(await callback.message(conn, summary))
                self.assertEqual(set(payload["subtask_results"]), {"1", "2"})
                if style == ChallengeResultStyle.SUBTASK_ONLY:
                    self.assertNotIn("testdata_results", payload)
                else:
                    self.assertEqual(set(payload["testdata_results"]), {"1", "2"})
                self.assertEqual(self.pro_service.get_pro.await_count, 1)

    async def test_full_style_system_filtering_and_visibility_matrix(self):
        callback = ChalStateCallback()
        conn = self.connection(2)
        self.user_service.info_acct.return_value = (None, account(2))
        self.pro_service.get_pro.return_value = (None, self.problem_with_system_flags())

        summary = json.dumps(
            {
                "chal_id": 7,
                "total_result": {
                    "state": 1,
                    "ce_message": "secret",
                    "ie_message": "",
                    "message_type": 2,
                },
                "testdata_results": {"1": {"status": 1}, "2": {"status": 1}, "bad": {}},
                "subtask_results": {"1": {"state": 1}, "2": {"state": 1}, "bad": {}},
            }
        )
        callback.conn_state[conn] = {"chal": challenge(owner=2, contest_id=4)}

        value = contest(running=True, style=ChallengeResultStyle.FULL, system_test=True)
        self.contest_service.get_contest.return_value = (None, value)
        payload = json.loads(await callback.message(conn, summary))
        self.assertEqual(set(payload["testdata_results"]), {"1"})
        self.assertEqual(set(payload["subtask_results"]), {"1"})
        self.assertIsNone(
            await callback.message(
                conn, json.dumps({"chal_id": 7, "id": 2, "status": 1})
            )
        )

        callback.conn_state[conn] = {"chal": challenge(owner=1, contest_id=4)}
        value = contest(running=True)
        self.contest_service.get_contest.return_value = (None, value)
        self.assertIsNone(await callback.message(conn, summary))

        value = contest(ended=True, public=True)
        self.contest_service.get_contest.return_value = (None, value)
        payload = json.loads(await callback.message(conn, summary))
        self.assertEqual(payload["total_result"]["ce_message"], "")

        value = contest(ended=True, public=False)
        self.contest_service.get_contest.return_value = (None, value)
        self.assertIsNone(await callback.message(conn, summary))

        value = contest()
        self.contest_service.get_contest.return_value = (None, value)
        self.assertIsNone(await callback.message(conn, summary))

        value = contest(admin_ids=(2,))
        self.contest_service.get_contest.return_value = (None, value)
        self.assertEqual(await callback.message(conn, summary), summary)
