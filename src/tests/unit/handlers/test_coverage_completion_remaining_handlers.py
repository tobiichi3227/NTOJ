import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import tornado.web

from handlers.contests.manage.pro import ContestManageProHandler
from handlers.contests.manage.qa import (
    ContestManageAnnounceHandler,
    ContestManageQACallback,
)
from handlers.contests.scoreboard import (
    ContestScoreboardCallback,
    ContestScoreboardHandler,
)
from handlers.pro import ProHandler, ProStaticHandler, ProsetHandler
from services.chal import ChalConst, ChalService
from services.contests import (
    ChallengeResultStyle,
    ContestMode,
    ContestService,
    ProblemScoreType,
    UserStatus,
)
from services.pro import ProClassConst, ProClassService, ProConst, ProService
from services.rate import RateService
from services.user import UserService
from tests.unit.handlers.test_contest_scoreboard import (
    Subject as ScoreboardSubject,
    contest as scoreboard_contest,
    original as scoreboard_original,
)
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Subject,
)
from tests.unit.handlers.test_coverage_completion_contest_pro import (
    problem_contest,
)
from tests.unit.handlers.test_pro_handlers import (
    Subject as ProSubject,
    original,
    problem,
)


class TestContestProblemValidationCompletion(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self):
        self.contests = SimpleNamespace(
            update_contest=AsyncMock(return_value=([], None))
        )
        self.problems = SimpleNamespace(
            get_pro=AsyncMock(),
            update_pro=AsyncMock(),
        )
        for service, value in (
            (ContestService, self.contests),
            (ProService, self.problems),
        ):
            active = patch.object(
                service, "inst", value, create=True
            )
            active.start()
            self.addCleanup(active.stop)

    async def test_add_remove_multi_add_and_multi_remove_edges(self):
        value = problem_contest()
        self.assertEqual(
            (
                await ContestManageProHandler.add_action(
                    Subject(
                        value,
                        {
                            "pro_id": "1",
                            "score_type": str(
                                ProblemScoreType.IOI2017.value
                            ),
                        },
                    )
                )
            )[0],
            "Eexist",
        )
        self.assertEqual(
            (
                await ContestManageProHandler.remove_action(
                    Subject(value, {"pro_id": "2"})
                )
            )[0],
            "Enoext",
        )
        self.assertEqual(
            (
                await ContestManageProHandler.multi_add_action(
                    Subject(
                        value,
                        {
                            "pro_id": "2",
                            "score_type": "999",
                        },
                    )
                )
            )[0],
            "Eparam",
        )

        result = await ContestManageProHandler.multi_remove_action(
            Subject(value, {"pro_id": "1-2"})
        )
        self.assertEqual(result[0], "S")
        self.assertIn("[2]", result[1])

    async def test_rejudge_and_option_validation_edges(self):
        self.assertEqual(
            (
                await ContestManageProHandler.rechal_action(
                    Subject(arguments={"pro_id": "bad"})
                )
            )[0],
            "Eparam",
        )

        missing = problem_contest()
        self.assertEqual(
            (
                await ContestManageProHandler.update_score_type_action(
                    Subject(
                        missing,
                        {"pro_id": "2", "score_type": "1"},
                    )
                )
            )[0],
            "Enoext",
        )
        self.assertEqual(
            (
                await ContestManageProHandler.update_score_type_action(
                    Subject(
                        problem_contest(),
                        {"pro_id": "1", "score_type": "999"},
                    )
                )
            )[0],
            "Eparam",
        )

        self.assertEqual(
            (
                await ContestManageProHandler.update_challenge_style_action(
                    Subject(
                        missing,
                        {
                            "pro_id": "2",
                            "challenge_style": "1",
                        },
                    )
                )
            )[0],
            "Enoext",
        )
        self.assertEqual(
            (
                await ContestManageProHandler.update_challenge_style_action(
                    Subject(
                        problem_contest(),
                        {
                            "pro_id": "1",
                            "challenge_style": "999",
                        },
                    )
                )
            )[0],
            "Eparam",
        )

    async def test_public_and_system_test_membership_configuration(self):
        self.assertEqual(
            (
                await ContestManageProHandler.public_action(
                    Subject(
                        problem_contest(),
                        {"pro_id": "2"},
                    )
                )
            )[0],
            "Enoext",
        )
        self.assertEqual(
            (
                await ContestManageProHandler.system_test_action(
                    Subject(
                        problem_contest(),
                        {"pro_id": "2"},
                    )
                )
            )[0],
            "Enoext",
        )
        self.assertEqual(
            (
                await ContestManageProHandler.system_test_action(
                    Subject(
                        problem_contest(enable_system_test=False),
                        {"pro_id": "1"},
                    )
                )
            )[0],
            "Econf",
        )


class TestProsetCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.problems = SimpleNamespace(list_pro=AsyncMock())
        self.rates = SimpleNamespace(
            map_rate_acct=AsyncMock(return_value=(None, {})),
            get_pro_topcoder=AsyncMock(return_value=(None, None)),
            get_pro_ac_rate=AsyncMock(),
        )
        self.users = SimpleNamespace(
            info_acct=AsyncMock(),
            update_acct=AsyncMock(),
        )
        self.classes = SimpleNamespace(
            get_proclass=AsyncMock(),
        )
        for service, value in (
            (ProService, self.problems),
            (RateService, self.rates),
            (ProClassService, self.classes),
            (UserService, self.users),
        ):
            active = patch.object(
                service, "inst", value, create=True
            )
            active.start()
            self.addCleanup(active.stop)

    async def test_only_ac_name_and_tag_filters(self):
        method = original(ProsetHandler.get)
        cases = (
            (
                {"show": "onlyac"},
                {1: {"state": ChalConst.STATE_WA}},
            ),
            (
                {"name": "missing"},
                {1: {"state": ChalConst.STATE_AC}},
            ),
            (
                {"tags": "missing"},
                {1: {"state": ChalConst.STATE_AC}},
            ),
        )
        for arguments, states in cases:
            with self.subTest(arguments=arguments):
                candidate = problem(1)
                self.problems.list_pro.return_value = (
                    None,
                    [candidate],
                )
                self.rates.map_rate_acct.return_value = (
                    None,
                    states,
                )
                subject = ProSubject(arguments)
                await method(subject)
                self.assertEqual(
                    subject.render.await_args.kwargs["prolist"],
                    [],
                )

    def rate_data(self, *, nonzero):
        value = 2 if nonzero else 0
        return {
            "user_ac_chal_cnt": value,
            "user_all_chal_cnt": value,
            "ac_chal_cnt": value,
            "all_chal_cnt": value,
        }

    async def test_user_and_challenge_ratio_sorters(self):
        method = original(ProsetHandler.get)
        candidates = [problem(1), problem(2)]
        self.problems.list_pro.return_value = (
            None,
            candidates,
        )
        self.rates.map_rate_acct.return_value = (
            None,
            {
                1: {"state": ChalConst.STATE_AC},
                2: {"state": ChalConst.STATE_AC},
            },
        )

        async def get_rate(pro_id):
            return None, self.rate_data(nonzero=pro_id == 1)

        self.rates.get_pro_ac_rate.side_effect = get_rate
        for order in (
            "user",
            "chal",
            "chalcnt",
            "chalaccnt",
            "usercnt",
            "useraccnt",
        ):
            with self.subTest(order=order):
                subject = ProSubject({"order": order})
                await method(subject)
                self.assertEqual(
                    len(subject.render.await_args.kwargs["prolist"]),
                    2,
                )

    async def test_topcoder_account_cache_hit_and_miss(self):
        method = original(ProsetHandler.get)
        self.problems.list_pro.return_value = (
            None,
            [problem(1), problem(2)],
        )
        self.rates.map_rate_acct.return_value = (
            None,
            {
                1: {"state": ChalConst.STATE_AC},
                2: {"state": ChalConst.STATE_AC},
            },
        )
        self.rates.get_pro_topcoder.return_value = (None, 9)
        self.rates.get_pro_ac_rate.return_value = (
            None,
            self.rate_data(nonzero=True),
        )
        topcoder = SimpleNamespace(acct_id=9, name="topcoder")
        self.users.info_acct.return_value = (None, topcoder)

        subject = ProSubject()
        await method(subject)
        self.users.info_acct.assert_awaited_once_with(9)
        score_map = subject.render.await_args.kwargs["score_map"]
        self.assertIs(score_map[1]["topcoder"], topcoder)
        self.assertIs(score_map[2]["topcoder"], topcoder)


    async def test_proclass_without_creator_skips_account_lookup(self):
        method = original(ProsetHandler.get)
        self.problems.list_pro.return_value = (
            None,
            [problem(1)],
        )
        self.rates.map_rate_acct.return_value = (
            None,
            {1: {"state": ChalConst.STATE_AC}},
        )
        self.rates.get_pro_ac_rate.return_value = (
            None,
            self.rate_data(nonzero=True),
        )
        self.classes.get_proclass.return_value = (
            None,
            {
                "type": ProClassConst.OFFICIAL_PUBLIC,
                "acct_id": 0,
                "list": [1],
            },
        )

        subject = ProSubject({"proclass_id": "4"})
        await method(subject)

        self.users.info_acct.assert_not_awaited()
        self.assertEqual(
            len(subject.render.await_args.kwargs["prolist"]),
            1,
        )

    async def test_topcoder_filters_keep_matching_problem(self):
        method = original(ProsetHandler.get)
        self.rates.get_pro_ac_rate.return_value = (
            None,
            self.rate_data(nonzero=True),
        )
        topcoder = SimpleNamespace(acct_id=9, name="topcoder")
        self.users.info_acct.return_value = (None, topcoder)

        for topcoder_filter, topcoder_id in (
            ("myself", 7),
            ("other", 9),
            ("9", 9),
        ):
            with self.subTest(topcoder_filter=topcoder_filter):
                self.problems.list_pro.return_value = (
                    None,
                    [problem(1)],
                )
                self.rates.map_rate_acct.return_value = (
                    None,
                    {1: {"state": ChalConst.STATE_AC}},
                )
                self.rates.get_pro_topcoder.return_value = (
                    None,
                    topcoder_id,
                )
                subject = ProSubject(
                    {"topcoder_filter": topcoder_filter}
                )
                await method(subject)
                self.assertEqual(
                    len(
                        subject.render.await_args.kwargs[
                            "prolist"
                        ]
                    ),
                    1,
                )

    async def test_topcoder_lookup_error_leaves_account_empty(self):
        method = original(ProsetHandler.get)
        self.problems.list_pro.return_value = (
            None,
            [problem(1)],
        )
        self.rates.map_rate_acct.return_value = (
            None,
            {1: {"state": ChalConst.STATE_AC}},
        )
        self.rates.get_pro_topcoder.return_value = (None, 9)
        self.rates.get_pro_ac_rate.return_value = (
            None,
            self.rate_data(nonzero=True),
        )
        self.users.info_acct.return_value = (
            ("Enoext", "missing"),
            None,
        )

        subject = ProSubject()
        await method(subject)

        self.assertIsNone(
            subject.render.await_args.kwargs["score_map"][1][
                "topcoder"
            ]
        )

class TestRemainingProblemPageBranches(unittest.IsolatedAsyncioTestCase):
    async def test_contest_static_file_uses_contest_status(self):
        contest = MagicMock()
        contest.is_pro.return_value = True
        contest.is_member.return_value = True
        contest.is_admin.return_value = True
        contest.is_running.return_value = False

        handler = object.__new__(ProStaticHandler)
        handler.contest = contest
        handler.acct = MagicMock()
        handler.acct.is_kernel.return_value = False
        handler.error = MagicMock(side_effect=lambda value: value)
        handler.set_status = MagicMock()
        handler.set_header = MagicMock()
        handler.finish = MagicMock()
        handler.get_argument = MagicMock(return_value=None)
        handler._is_file_access_safe = MagicMock(return_value=True)

        problems = SimpleNamespace(
            get_pro=AsyncMock(return_value=(None, object()))
        )
        static_get = AsyncMock()
        with (
            patch.object(ProService, "inst", problems, create=True),
            patch.object(
                tornado.web.StaticFileHandler,
                "get",
                new=static_get,
            ),
        ):
            await original(ProStaticHandler.get)(
                handler, "1", "cont.pdf"
            )
        problems.get_pro.assert_awaited_once_with(
            1,
            ProConst.PRO_STATUS_CONTEST_USER,
        )

    async def test_kernel_problem_detail_skips_user_state_lookup(self):
        problems = SimpleNamespace(
            get_pro=AsyncMock(
                return_value=(None, problem(1))
            )
        )
        rates = SimpleNamespace(
            get_pro_topcoder=AsyncMock(
                return_value=(None, None)
            )
        )
        challenges = SimpleNamespace(
            check_acct_pro_state=AsyncMock()
        )
        judges = SimpleNamespace(
            is_server_online=MagicMock(return_value=True)
        )
        with (
            patch.object(ProService, "inst", problems, create=True),
            patch.object(RateService, "inst", rates, create=True),
            patch.object(ChalService, "inst", challenges, create=True),
            patch(
                "handlers.pro.JudgeServerClusterService.inst",
                judges,
                create=True,
            ),
        ):
            subject = ProSubject()
            subject.acct.is_kernel.return_value = True
            await original(ProHandler.get)(subject, "1")
        challenges.check_acct_pro_state.assert_not_awaited()


class TestContestScoreboardAndQACompletion(
    unittest.IsolatedAsyncioTestCase
):
    async def test_callback_unregistered_valid_init(self):
        callback = ContestScoreboardCallback()
        conn = object()
        self.assertTrue(
            await callback.handle_custom_message(
                conn, "contestnewchalsub_init", "9"
            )
        )
        self.assertNotIn(conn, callback.conn_state)

        qa_callback = ContestManageQACallback()
        self.assertTrue(
            await qa_callback.handle_custom_message(
                conn, "contestnewquessub_init", "9"
            )
        )
        self.assertNotIn(conn, qa_callback.conn_state)

    async def test_announce_edit_before_start_does_not_publish(self):
        value = SimpleNamespace(
            contest_id=9,
            is_start=MagicMock(return_value=False),
        )
        contests = SimpleNamespace(edit_announce=AsyncMock())
        subject = Subject(
            value,
            {
                "announce_id": "1",
                "subject": "subject",
                "content": "content",
            },
        )
        with patch.object(
            ContestService, "inst", contests, create=True
        ):
            result = await ContestManageAnnounceHandler.edit_announce_action(
                subject
            )
        self.assertEqual(result, ("S", ""))
        subject.rs.publish.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
