import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.chal import (
    ChalSearchingParam,
    ChalSearchingParamBuilder,
    ChalService,
    Compiler,
)
from services.pro import ProConst, ProService, ProType


def database(connection=None, enter_error=None):
    connection = connection or AsyncMock()
    acquire = MagicMock()
    if enter_error is None:
        acquire.__aenter__ = AsyncMock(return_value=connection)
    else:
        acquire.__aenter__ = AsyncMock(side_effect=enter_error)
    acquire.__aexit__ = AsyncMock(return_value=None)
    db = MagicMock()
    db.acquire.return_value = acquire
    return db, connection


class TestChallengeSearchBranches(unittest.TestCase):
    def test_empty_filters_none_state_default_status_and_optional_builder_values(self):
        query = (
            ChalSearchingParamBuilder()
            .pro([])
            .acct([])
            .state(None)
            .compiler(-1)
            .contest(None)
            .build()
            .get_sql_query_str()
        )
        self.assertIn('"challenge"."pro_id" IS NULL', query)
        self.assertIn('"challenge"."acct_id" IS NULL', query)
        self.assertIn('"challenge"."contest_id"=0', query)
        self.assertIn(str(ProConst.STATUS_ONLINE), query)

        direct_default = ChalSearchingParam(
            None,
            None,
            0,
            -1,
            None,
        ).get_sql_query_str()
        self.assertIn(str(ProConst.STATUS_ONLINE), direct_default)

        with self.assertRaises(AssertionError):
            ChalSearchingParamBuilder().pro_statuses([999])


class TestChalServiceFailureBranches(unittest.IsolatedAsyncioTestCase):
    def service(self, *, db=None):
        if db is None:
            db, _ = database()
        return ChalService(db, AsyncMock())

    async def test_add_challenge_propagates_problem_error_and_rejects_unsupported_type(self):
        pro_service = SimpleNamespace(get_pro=AsyncMock())
        with patch.object(ProService, "inst", pro_service, create=True):
            pro_service.get_pro.return_value = (("Enoext", "missing"), None)
            self.assertEqual(
                await self.service().add_chal(5, 7, 0, Compiler.GPP, "code", ProType.BATCH),
                (("Enoext", "missing"), None),
            )

            pro_service.get_pro.return_value = (None, SimpleNamespace(config=object()))
            self.assertEqual(
                await self.service().add_chal(
                    5, 7, 0, Compiler.GPP, "code", ProType.OUTPUTONLY
                ),
                (("Eunk", "Unsupported problem type"), None),
            )

    async def test_reset_and_result_fetches_return_stable_database_errors(self):
        methods = (
            ("reset_chal", (("Eunk", "Unknown error"))),
            ("get_subtask_results", (("Eunk", "Unknown error"), None)),
            ("get_testdata_results", (("Eunk", "Unknown error"), None)),
            ("get_chal", (("Eunk", "Unknown error"), None)),
            ("get_total_result", (("Eunk", "Unknown error"), None)),
        )
        for method_name, expected in methods:
            with self.subTest(method=method_name):
                db, _ = database(enter_error=RuntimeError("db"))
                result = await getattr(self.service(db=db), method_name)(9)
                self.assertEqual(result, expected)

    async def test_emit_challenge_missing_and_unsupported_problem_type(self):
        db, connection = database()
        service = self.service(db=db)
        connection.fetch.return_value = []
        self.assertEqual(
            await service.emit_chal(9, object(), Compiler.GPP, 0, ProType.BATCH),
            (("Enoext", "Challenge not found"), None),
        )

        connection.fetch.return_value = [{"acct_id": 7, "pro_id": 5, "contest_id": 0}]
        self.assertEqual(
            await service.emit_chal(9, object(), Compiler.GPP, 0, ProType.OUTPUTONLY),
            (("Eunk", "Unsupported problem type"), None),
        )

    async def test_list_total_state_and_count_error_and_empty_branches(self):
        search = ChalSearchingParamBuilder().build()

        db, _ = database(enter_error=RuntimeError("db"))
        self.assertEqual(
            await self.service(db=db).list_chal(0, 20, search),
            (("Eunk", "Unknown error"), None),
        )

        db, connection = database()
        connection.fetch.return_value = []
        self.assertEqual(
            await self.service(db=db).get_total_result(9),
            (("Enoext", "Challenge not found"), None),
        )

        db, _ = database(enter_error=RuntimeError("db"))
        self.assertEqual(
            await self.service(db=db).check_acct_pro_state(7, 5),
            (("Eunk", "Unknown error"), None),
        )

        db, connection = database()
        connection.fetchrow.return_value = None
        self.assertEqual(
            await self.service(db=db).check_acct_pro_state(7, 5),
            (None, None),
        )

        db, _ = database(enter_error=RuntimeError("db"))
        self.assertEqual(
            await self.service(db=db).get_chals_count(search),
            (("Eunk", "Unknown error"), None),
        )

        db, connection = database()
        connection.fetch.return_value = []
        self.assertEqual(
            await self.service(db=db).get_chals_count(search),
            (("Eunk", "Unknown error"), None),
        )


if __name__ == "__main__":
    unittest.main()
