import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.base import UnifiedWebSocketHandler
from handlers.contests.contests import ContestListHandler
from handlers.manage.acct import ManageAcctHandler
from handlers.manage.board import ManageBoardHandler
from handlers.manage.bulletin import ManageBulletinHandler
from handlers.manage.pro.subtask import ManageProSubtaskHandler
from handlers.manage.proclass import ManageProClassHandler
from handlers.manage.question import ManageQuestionHandler
from handlers.pro import ProsetHandler
from handlers.ques import QuestionHandler
from services.contests import ContestService
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Subject,
    original,
)


class TestStructuralHandlerBranches(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_pages_and_actions_fall_through(self):
        for handler in (
            ManageAcctHandler,
            ManageBoardHandler,
            ManageBulletinHandler,
            ManageProClassHandler,
            ManageQuestionHandler,
        ):
            with self.subTest(handler=handler.__name__):
                self.assertIsNone(
                    await original(handler.get)(Subject(), "unknown")
                )

        self.assertIsNone(
            await original(QuestionHandler.post)(
                Subject(arguments={"reqtype": "unknown"})
            )
        )
        self.assertIsNone(
            await original(ProsetHandler.post)(
                Subject(arguments={"reqtype": "unknown"})
            )
        )

    async def test_resubscribe_without_an_active_pubsub_is_a_noop(self):
        handler = UnifiedWebSocketHandler
        previous = handler._shared_pubsub
        handler._shared_pubsub = None
        try:
            self.assertIsNone(await handler._resubscribe_all_channels())
        finally:
            handler._shared_pubsub = previous

    async def test_contest_ending_exactly_now_finishes_category_loop(self):
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        contests = SimpleNamespace(
            get_contest_list=AsyncMock(
                return_value=(
                    None,
                    [
                        {
                            "contest_start": now - datetime.timedelta(hours=1),
                            "contest_end": now,
                        }
                    ],
                )
            )
        )
        subject = Subject()
        with (
            patch.object(ContestService, "inst", contests, create=True),
            patch(
                "handlers.contests.contests.datetime.datetime"
            ) as clock,
        ):
            clock.now.return_value = now
            await original(ContestListHandler.get)(subject)

        categories = subject.render.await_args.kwargs["contest_category"]
        self.assertTrue(all(not values for values in categories.values()))

    def test_acyclic_dependency_walk_reuses_visited_subtask(self):
        configs = {
            0: SimpleNamespace(dependency_subtasks={1}),
            1: SimpleNamespace(dependency_subtasks=set()),
        }
        self.assertFalse(
            ManageProSubtaskHandler.have_cycle(None, configs)
        )


if __name__ == "__main__":
    unittest.main()
