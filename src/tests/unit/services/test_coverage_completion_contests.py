import datetime
import pickle
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg

from services.chal import Compiler
from services.contests import (
    ChallengeResultStyle,
    Contest,
    ContestMode,
    ContestService,
    ProblemScoreType,
    RegMode,
    UserStatus,
)
from services.user import Account


def value_contest(**overrides):
    values = {
        "contest_id": 9,
        "contest_creator": 1,
        "name": "Contest",
        "contest_mode": ContestMode.IOI,
        "contest_start": datetime.datetime.now(datetime.UTC)
        - datetime.timedelta(hours=1),
        "contest_end": datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(hours=1),
        "reg_mode": RegMode.FREE_REG,
        "reg_end": datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(minutes=30),
        "user_list": {
            1: {"status": UserStatus.ADMIN},
            2: {"status": UserStatus.APPROVED},
        },
        "pro_list": {},
        "allow_compilers": {Compiler.GPP},
    }
    values.update(overrides)
    return Contest(**values)


class EmptyInsertResult:
    def __len__(self):
        return 0

    def __getitem__(self, index):
        if index == 0:
            return {"contest_id": 9}
        raise IndexError(index)


class TestContestServiceCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = AsyncMock()
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=self.connection)
        manager.__aexit__ = AsyncMock(return_value=None)
        self.db = MagicMock()
        self.db.acquire.return_value = manager
        self.db.fetch = AsyncMock()
        self.db.execute = AsyncMock()
        self.rs = AsyncMock()
        self.service = ContestService(self.db, self.rs)

    def test_contest_membership_id_account_and_assertions(self):
        value = value_contest()
        account = MagicMock(spec=Account)
        account.acct_id = 99

        self.assertTrue(value.is_admin(acct_id=1))
        self.assertFalse(value.is_admin(acct_id=99))
        with self.assertRaises(AssertionError):
            value.is_admin()

        self.assertTrue(value.is_member(acct_id=2))
        self.assertFalse(value.is_member(acct_id=99))
        with self.assertRaises(AssertionError):
            value.is_member()

        self.assertFalse(value.member_is_status(account, UserStatus.APPROVED))
        self.assertFalse(value.member_is_status(99, UserStatus.APPROVED))
        self.assertTrue(value.member_is_status(2, UserStatus.APPROVED))

    async def test_get_contest_cache_expiry_missing_and_running_database_value(self):
        ended = value_contest(
            contest_end=datetime.datetime.now(datetime.UTC)
            - datetime.timedelta(minutes=1)
        )
        self.rs.hget.return_value = pickle.dumps(ended)
        err, loaded = await self.service.get_contest(9)
        self.assertIsNone(err)
        self.assertEqual(loaded.contest_id, 9)
        self.rs.hdel.assert_awaited_once_with("contest", "9")

        self.rs.reset_mock()
        self.rs.hget.return_value = None
        self.connection.fetch.return_value = []
        self.assertEqual(
            await self.service.get_contest(404),
            (("Enoext", "Contest not found"), None),
        )

        row = {
            "contest_id": 9,
            "contest_creator": 1,
            "name": "Contest",
            "desc_before_contest": "",
            "desc_during_contest": "",
            "desc_after_contest": "",
            "contest_mode": ContestMode.IOI.value,
            "contest_start": datetime.datetime.now(datetime.UTC)
            - datetime.timedelta(minutes=1),
            "contest_end": datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=1),
            "reg_mode": RegMode.FREE_REG.value,
            "reg_end": datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=1),
            "allow_compilers": {Compiler.GPP},
            "is_public_scoreboard": False,
            "allow_view_other_page": False,
            "hide_admin": False,
            "submission_cd_time": 30,
            "freeze_scoreboard_period": 0,
            "penalty_value": 20,
            "enable_system_test": False,
        }
        self.connection.fetch.side_effect = [
            [row],
            [(5, ProblemScoreType.IOI2017, ChallengeResultStyle.FULL)],
            [(2, UserStatus.APPROVED)],
        ]
        err, loaded = await self.service.get_contest(9)
        self.assertIsNone(err)
        self.assertIn(5, loaded.pro_list)
        self.assertIn(2, loaded.user_list)
        self.rs.hset.assert_awaited_once()

    async def test_add_default_integrity_and_empty_result(self):
        account = MagicMock(acct_id=1)
        self.connection.fetch.side_effect = (
            asyncpg.IntegrityConstraintViolationError()
        )
        self.assertEqual(
            await self.service.add_default_contest(account, "Contest"),
            (("Eexist", "Contest already exists"), None),
        )

        self.connection.fetch.side_effect = None
        self.connection.fetch.return_value = EmptyInsertResult()
        self.assertEqual(
            await self.service.add_default_contest(account, "Contest"),
            (("Eexist", "Contest already exists"), None),
        )

    async def test_missing_announcement_and_question_results(self):
        for method, args in (
            (self.service.add_announce, (9, 7, "subject", "content")),
            (self.service.get_announce, (9, 1)),
            (self.service.ask_question, (9, 7, "subject", "content")),
            (self.service.get_question, (9, 1)),
        ):
            self.db.fetch.return_value = []
            result = await method(*args)
            self.assertEqual(result[0][0], "Eunk")
            self.assertIsNone(result[1])

    async def test_empty_and_populated_score_maps(self):
        before = datetime.datetime.now(datetime.UTC)
        with patch.object(
            self.service,
            "get_contest",
            AsyncMock(return_value=(None, value_contest())),
        ):
            self.db.fetch.return_value = []
            self.assertEqual(
                await self.service.get_icpc_scores(9, 1, before), {}
            )

        self.db.fetch.return_value = []
        self.assertEqual(
            await self.service.get_ioi2013_scores(9, 1, before), {}
        )
        timestamp = datetime.datetime.now(datetime.UTC)
        self.db.fetch.return_value = [(7, 10, 80, timestamp, 2)]
        self.assertEqual(
            await self.service.get_ioi2013_scores(9, 1, before),
            {
                7: {
                    "acct_id": 7,
                    "chal_id": 10,
                    "score": 80,
                    "timestamp": timestamp,
                    "fail_cnt": 2,
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
