import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.pro import (
    Limit,
    Problem,
    ProblemConfig,
    ProClassService,
    ProConst,
    ProService,
    ProType,
)
from services.prospec.batch import BatchProblemSpec, BatchTestdata
from services.rate import RateService


def fake_database():
    connection = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=None)
    transaction.__aexit__ = AsyncMock(return_value=None)
    connection.transaction = MagicMock(return_value=transaction)
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=connection)
    acquire.__aexit__ = AsyncMock(return_value=None)
    database = MagicMock()
    database.acquire = MagicMock(return_value=acquire)
    return database, connection


def problem(name="Problem", status=ProConst.STATUS_ONLINE, tags="math"):
    return Problem(5, name, status, tags, True, ProType.BATCH, None)


class TestProblemServiceBranches(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.database, self.connection = fake_database()
        self.redis = AsyncMock()
        self.service = ProService(self.database, self.redis)
    def test_problem_config_accepts_empty_limits_and_valid_precision(self):
        config = ProblemConfig(
            limits={},
            subtask_configs={},
            testdatas={},
            rate_precision=1,
            spec_config=BatchProblemSpec().get_default_config(),
        )
        self.assertEqual(config.rate_precision, 1)

    async def test_get_non_batch_problem_skips_batch_parsers(self):
        row = {
            "name": "Output",
            "status": ProConst.STATUS_ONLINE,
            "tags": "",
            "allow_submit": True,
            "problem_type": ProType.OUTPUTONLY,
            "config": "{}",
            "limits": "{}",
            "rate_precision": 0,
        }
        self.connection.fetch.side_effect = [[row], [], []]

        err, value = await self.service.get_pro(
            5, ProConst.PRO_STATUS_NORMAL_USER
        )

        self.assertIsNone(err)
        self.assertEqual(value.problem_type, ProType.OUTPUTONLY)
        self.assertIsNone(value.config)

    async def test_update_non_batch_config_skips_batch_serialization(self):
        config = ProblemConfig(
            limits={},
            subtask_configs={},
            testdatas={},
            rate_precision=0,
            spec_config=BatchProblemSpec().get_default_config(),
        )
        self.connection.fetch.side_effect = [[], []]
        rate = SimpleNamespace(
            refresh_pro_ac_rate=MagicMock(),
            refresh_acct_rate=AsyncMock(),
            refresh_pro_topcoder=AsyncMock(),
        )

        with patch.object(RateService, "inst", rate, create=True):
            result = await self.service.update_pro_config(
                5, ProType.OUTPUTONLY, config
            )

    async def test_get_problem_handles_testdata_and_config_parse_errors(self):
        row = {
            "name": "Problem",
            "status": ProConst.STATUS_ONLINE,
            "tags": None,
            "allow_submit": True,
            "problem_type": ProType.BATCH,
            "config": json.dumps(
                BatchProblemSpec().to_json(BatchProblemSpec().get_default_config())
            ),
            "limits": json.dumps(
                {"default": {"time": 1, "memory": 1, "output": 1}}
            ),
            "rate_precision": 0,
        }
        self.connection.fetch.side_effect = [
            [row],
            [(1, "not-json", "{}")],
        ]
        self.assertEqual(
            (await self.service.get_pro(5, ProConst.PRO_STATUS_NORMAL_USER))[0][0],
            "Eunk",
        )

        self.connection.fetch.side_effect = [[row], [], []]
        with patch(
            "services.prospec.batch.batch_spec.from_json",
            side_effect=ValueError("bad config"),
        ):
            self.assertEqual(
                (await self.service.get_pro(5, ProConst.PRO_STATUS_NORMAL_USER))[0][0],
                "Eunk",
            )
        self.assertIsNone(await self.service.get_pro_config(5))

    async def test_list_problem_database_error(self):
        self.redis.hget.return_value = None
        self.database.acquire.return_value.__aenter__.side_effect = RuntimeError("db")
        self.assertEqual(
            (await self.service.list_pro(ProConst.PRO_STATUS_NORMAL_USER))[0][0],
            "Eunk",
        )

    async def test_add_problem_validation_database_and_directory_failures(self):
        self.assertEqual((await self.service.add_pro("", 0))[0][0], "Enamemin")
        self.assertEqual(
            (await self.service.add_pro("x" * 65, 0))[0][0], "Enamemax"
        )
        self.assertEqual((await self.service.add_pro("x", 9))[0][0], "Eparam")

        self.connection.fetch.return_value = []
        self.assertEqual((await self.service.add_pro("x", 0))[0][0], "Eunk")

        self.connection.fetch.return_value = [{"pro_id": 12}]
        with (
            patch("services.pro.os.mkdir", side_effect=OSError("mkdir")),
            patch("services.pro.os.rmdir", side_effect=[None, OSError("missing"), None, None]) as remove,
        ):
            self.assertEqual((await self.service.add_pro("x", 0))[0][0], "Eunk")
        self.assertGreaterEqual(remove.call_count, 1)

        self.database.acquire.return_value.__aenter__.side_effect = RuntimeError("db")
        self.assertEqual((await self.service.add_pro("x", 0))[0][0], "Eunk")

    async def test_update_problem_validation_missing_hidden_cache_and_exception(self):
        self.assertEqual((await self.service.update_pro(problem(name="")))[0][0], "Enamemin")
        self.assertEqual(
            (await self.service.update_pro(problem(name="x" * 65)))[0][0], "Enamemax"
        )
        invalid_status = problem()
        invalid_status.status = 9
        self.assertEqual((await self.service.update_pro(invalid_status))[0][0], "Eparam")
        self.assertEqual(
            (await self.service.update_pro(problem(tags="bad!")))[0][0], "Etags"
        )

        self.connection.fetch.return_value = []
        self.assertEqual((await self.service.update_pro(problem()))[0][0], "Enoext")

        hidden = problem(status=ProConst.STATUS_HIDDEN)
        self.connection.fetch.side_effect = [[{"pro_id": 5}], [{"contest_id": 2}, {"contest_id": 3}]]
        pipeline = AsyncMock()
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__ = AsyncMock(return_value=None)
        self.redis.pipeline = MagicMock(return_value=pipeline)
        self.assertEqual(await self.service.update_pro(hidden), (None, None))
        self.assertEqual(pipeline.hdel.await_count, 4)
        pipeline.execute.assert_awaited_once()

        self.connection.fetch.side_effect = RuntimeError("db")
        self.assertEqual((await self.service.update_pro(problem()))[0][0], "Eunk")

    async def test_update_config_refreshes_contests_and_handles_database_error(self):
        config = ProblemConfig(
            limits={"default": Limit(1, 2, 3)},
            subtask_configs={},
            testdatas={1: BatchTestdata(1, {}, "1.in", "1.out")},
            rate_precision=0,
            spec_config=BatchProblemSpec().get_default_config(),
        )
        self.connection.fetch.side_effect = [
            [{"chal_id": 10}],
            [{"contest_id": 2}, {"contest_id": 3}],
        ]
        rate = SimpleNamespace(
            refresh_pro_ac_rate=MagicMock(side_effect=lambda *_: completed()),
            refresh_acct_rate=AsyncMock(),
            refresh_pro_topcoder=AsyncMock(),
        )
        with patch.object(RateService, "inst", rate, create=True):
            self.assertEqual(
                await self.service.update_pro_config(5, ProType.BATCH, config),
                (None, None),
            )
        self.assertEqual(rate.refresh_pro_ac_rate.call_count, 2)
        rate.refresh_acct_rate.assert_awaited_once_with(all_account=True)
        rate.refresh_pro_topcoder.assert_awaited_once_with(5)

        self.database.acquire.return_value.__aenter__.side_effect = RuntimeError("db")
        with patch.object(RateService, "inst", rate, create=True):
            self.assertEqual(
                (await self.service.update_pro_config(5, ProType.BATCH, config))[0][0],
                "Eunk",
            )

    async def test_unpack_rejects_unsupported_problem_type(self):
        self.assertEqual(
            (await self.service.unpack_pro(5, "token", ProType.OUTPUTONLY))[0][0],
            "Enotsupport",
        )


class TestProblemClassServiceErrors(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.database, self.connection = fake_database()
        self.service = ProClassService(self.database, AsyncMock())

    async def test_not_found_and_database_error_branches(self):
        self.connection.fetch.return_value = []
        self.assertEqual((await self.service.get_proclass(8))[0][0], "Enoext")
        self.database.acquire.return_value.__aenter__.side_effect = RuntimeError("db")
        self.assertEqual((await self.service.get_proclass(8))[0][0], "Eunk")
        self.assertEqual((await self.service.get_proclass_list())[0][0], "Eunk")
        self.assertEqual(
            (await self.service.add_proclass("x", [], "", 1, 0))[0][0], "Eunk"
        )
        self.assertEqual((await self.service.remove_proclass(8))[0][0], "Eunk")
        self.assertEqual(
            (await self.service.update_proclass(8, "x", [], "", 0))[0][0], "Eunk"
        )

    async def test_remove_missing_problem_class(self):
        self.connection.execute.return_value = "DELETE 0"
        self.assertEqual((await self.service.remove_proclass(8))[0][0], "Enoext")


async def completed():
    return None


if __name__ == "__main__":
    unittest.main()
