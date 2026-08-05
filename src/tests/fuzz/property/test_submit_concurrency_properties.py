"""Concurrent submission properties for duplicate and cooldown guards."""

import asyncio
import datetime
import sys
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import patch

from hypothesis import assume, given, strategies as st

test_config = sys.modules.setdefault("config", SimpleNamespace())
test_config.BASE_URL = "/"
test_config.SITE_TITLE = "NTOJ Fuzz"

import handlers.prospec.batch.submit as submit_module
from handlers.prospec.batch.submit import BatchSubmitHandler
from services.chal import Compiler
from services.contests import UserStatus
from services.prospec.batch import BatchProblemSpec


class AtomicFakeRedis:
    def __init__(self):
        self.values = {}
        self.sets = defaultdict(set)

    async def set(self, name, value, *, nx=False, ex=None):
        await asyncio.sleep(0)
        if nx and name in self.values:
            return False
        self.values[name] = value
        return True

    async def get(self, name):
        await asyncio.sleep(0)
        value = self.values.get(name)
        if value is None:
            return None
        return str(value).encode()

    async def sismember(self, name, value):
        await asyncio.sleep(0)
        return value in self.sets[name]

    async def sadd(self, name, value):
        await asyncio.sleep(0)
        before = len(self.sets[name])
        self.sets[name].add(value)
        return len(self.sets[name]) - before

    async def expire(self, name, *, time):
        await asyncio.sleep(0)
        return True

    async def eval(self, script, numkeys, name, token):
        await asyncio.sleep(0)
        if self.values.get(name) == token:
            del self.values[name]
            return 1
        return 0


class SubmitConcurrencyPropertiesTest(unittest.TestCase):
    @given(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789 \n",
            min_size=1,
            max_size=80,
        )
    )
    def test_two_identical_contest_submits_cannot_both_pass(self, code: str) -> None:
        assume(bool(code.strip()))

        async def exercise():
            redis = AtomicFakeRedis()
            account = SimpleNamespace(
                acct_id=7,
                is_kernel=lambda: False,
            )
            contest = SimpleNamespace(
                contest_id=11,
                submission_cd_time=30,
                allow_compilers={Compiler.GPP},
                contest_start=datetime.datetime(2026, 1, 1),
                contest_end=datetime.datetime(2026, 1, 1, 2),
                member_is_status=lambda acct, status: status == UserStatus.APPROVED,
            )
            subject = SimpleNamespace(
                acct=account,
                contest=contest,
                rs=redis,
            )
            problem = SimpleNamespace(
                pro_id=5,
                config=SimpleNamespace(spec_config=BatchProblemSpec().get_default_config()),
            )

            with patch.object(
                submit_module,
                "SUBMIT_GUARD_LOCK_RETRY_DELAY_SECONDS",
                0,
            ):
                return await asyncio.gather(
                    BatchSubmitHandler._is_allow_submit(subject, code, Compiler.GPP, problem),
                    BatchSubmitHandler._is_allow_submit(subject, code, Compiler.GPP, problem),
                )

        results = asyncio.run(exercise())
        accepted = [result for result in results if result is None]
        rejected = [result for result in results if result is not None]

        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0][0], "Esame")
