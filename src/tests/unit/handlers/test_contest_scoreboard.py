import datetime
import inspect
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import tornado.web
from msgpack import packb

import config

config.TIMEZONE = datetime.UTC

from handlers.contests.scoreboard import (
    ContestScoreboardCallback,
    ContestScoreboardHandler,
    _JsonDatetimeEncoder,
)
from services.contests import ContestMode, ContestService, ProblemScoreType, UserStatus
from services.user import UserService


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
    def __init__(self, contest, arguments=None):
        self.contest = contest
        self.arguments = arguments or {}
        self.acct = MagicMock(acct_id=7)
        self.rs = AsyncMock()
        self.error = MagicMock(side_effect=lambda value, **_: value)
        self.render = AsyncMock(return_value="rendered")
        self._encoder = ContestScoreboardHandler._encoder.__get__(self)

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise tornado.web.MissingArgumentError(name)


def contest(*, public=True, hide_admin=False):
    start = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)
    end = start + datetime.timedelta(hours=4)
    value = MagicMock(
        contest_id=9,
        name="Contest",
        contest_start=start,
        contest_end=end,
        freeze_scoreboard_period=60,
        is_public_scoreboard=public,
        hide_admin=hide_admin,
        contest_mode=ContestMode.ACM,
        user_list={
            7: {"status": UserStatus.APPROVED},
            8: {"status": UserStatus.ADMIN},
            10: {"status": UserStatus.REQUESTED},
        },
        pro_list={
            1: {"score_type": ProblemScoreType.ICPC},
            2: {"score_type": ProblemScoreType.IOI2017},
            3: {"score_type": ProblemScoreType.IOI2013},
        },
    )
    value.is_start.return_value = True
    value.is_running.return_value = True
    value.is_end.return_value = True
    value.is_admin.return_value = False
    value.is_member.return_value = True
    return value


def score(chal_id, score_value):
    return {
        7: {
            "chal_id": chal_id,
            "timestamp": datetime.datetime.now(datetime.UTC),
            "score": Decimal(score_value),
            "fail_cnt": 1,
        }
    }


class TestContestScoreboardCallback(unittest.IsolatedAsyncioTestCase):
    async def test_lifecycle_filter_and_custom_initialization(self):
        callback = ContestScoreboardCallback()
        conn = object()
        self.assertIsNone(await callback.register(conn))
        self.assertIsNone(await callback.message(conn, "9"))
        self.assertFalse(await callback.handle_custom_message(conn, "unknown", "9"))
        self.assertTrue(
            await callback.handle_custom_message(conn, "contestnewchalsub_init", "9")
        )
        self.assertEqual(await callback.message(conn, "9"), "9")
        self.assertIsNone(await callback.message(conn, "8"))
        self.assertIsNone(await callback.message(conn, "invalid"))
        self.assertTrue(
            await callback.handle_custom_message(
                object(), "contestnewchalsub_init", "invalid"
            )
        )
        self.assertIsNone(await callback.unregister(conn))
        self.assertNotIn(conn, callback.conn_state)

    def test_json_encoders_cover_datetime_duration_decimal_and_fallback(self):
        now = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
        encoded = json.dumps(
            {
                "datetime": now,
                "duration": datetime.timedelta(minutes=2, seconds=3),
                "decimal": Decimal("1.25"),
            },
            cls=_JsonDatetimeEncoder,
        )
        self.assertIn("2:03", encoded)
        self.assertIn("1.25", encoded)
        with self.assertRaises(TypeError):
            json.dumps({"object": object()}, cls=_JsonDatetimeEncoder)

        handler = object.__new__(ContestScoreboardHandler)
        self.assertEqual(handler._encoder(now), now.timestamp())
        self.assertEqual(handler._encoder(Decimal("2.5")), "2.5")
        marker = object()
        self.assertIs(handler._encoder(marker), marker)


class TestContestScoreboardHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        timezone_patch = patch(
            'handlers.contests.scoreboard.config.TIMEZONE', datetime.UTC, create=True
        )
        timezone_patch.start()
        self.addCleanup(timezone_patch.stop)
        self.contest_service = SimpleNamespace(
            get_icpc_scores=AsyncMock(return_value=score(11, "100")),
            get_ioi2017_scores=AsyncMock(return_value=score(12, "70")),
            get_ioi2013_scores=AsyncMock(return_value=score(13, "30")),
        )
        self.user_service = SimpleNamespace(
            info_acct=AsyncMock(
                side_effect=lambda acct_id: (
                    None,
                    SimpleNamespace(acct_id=acct_id, name=f"user-{acct_id}"),
                )
            )
        )
        for service, value in (
            (ContestService, self.contest_service),
            (UserService, self.user_service),
        ):
            active_patch = patch.object(service, "inst", value, create=True)
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def test_get_renders_contest(self):
        subject = Subject(contest())
        await original(ContestScoreboardHandler.get)(subject)
        subject.render.assert_awaited_once()

    async def test_post_permission_branches(self):
        value = contest()
        value.is_start.return_value = False
        value.is_admin.return_value = False
        subject = Subject(value)
        self.assertEqual(
            (await original(ContestScoreboardHandler.post)(subject))[0],
            "Eacces",
        )

        value = contest(public=False)
        value.is_member.return_value = False
        subject = Subject(value)
        self.assertEqual(
            (await original(ContestScoreboardHandler.post)(subject))[0],
            "Eacces",
        )

    async def test_public_scoreboard_computes_all_score_types_freezes_and_caches(self):
        value = contest(public=True, hide_admin=False)
        subject = Subject(value)
        subject.rs.hget.return_value = None

        post = original(ContestScoreboardHandler.post)
        await post(subject)

        self.contest_service.get_icpc_scores.assert_awaited_once()
        self.contest_service.get_ioi2017_scores.assert_awaited_once()
        self.contest_service.get_ioi2013_scores.assert_awaited_once()
        self.assertEqual(subject.rs.hset.await_count, 3)
        self.assertEqual(subject.rs.expire.await_count, 3)
        result = subject.error.call_args.args[0]
        self.assertEqual(result[0], "S")
        self.assertEqual([row["acct_id"] for row in result[1]], [7, 8])
        self.assertEqual(result[1][0]["total_score"], Decimal("200"))

    async def test_private_scoreboard_member_admin_and_cached_scores(self):
        post = original(ContestScoreboardHandler.post)
        value = contest(public=False, hide_admin=False)
        value.freeze_scoreboard_period = 0
        subject = Subject(value, {"display_time": value.contest_end.isoformat()})
        await post(subject)
        rows = subject.error.call_args.args[0][1]
        self.assertEqual([row["acct_id"] for row in rows], [7])

        value.is_admin.return_value = True
        subject = Subject(value, {"display_time": value.contest_end.isoformat()})
        await post(subject)
        rows = subject.error.call_args.args[0][1]
        self.assertEqual([row["acct_id"] for row in rows], [7, 8])

        cached = {
            7: {
                "chal_id": 99,
                "timestamp": datetime.datetime.now(datetime.UTC).timestamp(),
                "score": "2.5",
                "fail_cnt": 0,
            },
            8: {"chal_id": 98, "timestamp": None, "score": "0", "fail_cnt": 0},
        }
        value = contest(public=True, hide_admin=True)
        value.freeze_scoreboard_period = 0
        value.pro_list = {2: {"score_type": ProblemScoreType.IOI2017}}
        value.is_end.return_value = False
        subject = Subject(value)
        subject.rs.hget.return_value = packb(cached)
        await post(subject)
        rows = subject.error.call_args.args[0][1]
        self.assertEqual(rows[0]["scores"][2]["score"], Decimal("2.5"))
        self.contest_service.get_ioi2017_scores.reset_mock()


    async def test_explicit_pre_freeze_time_and_hidden_admins(self):
        post = original(ContestScoreboardHandler.post)

        running = contest(public=True)
        display_time = (
            running.contest_start + datetime.timedelta(minutes=1)
        ).isoformat()
        subject = Subject(
            running,
            {"display_time": display_time},
        )
        await post(subject)
        self.assertTrue(subject.error.called)

        private = contest(public=False, hide_admin=True)
        private.freeze_scoreboard_period = 0
        private.is_admin.return_value = True
        subject = Subject(
            private,
            {"display_time": private.contest_end.isoformat()},
        )
        await post(subject)
        rows = subject.error.call_args.args[0][1]
        self.assertEqual(
            [row["acct_id"] for row in rows],
            [7],
        )

if __name__ == "__main__":
    unittest.main()
