import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.contests.manage.log import ContestManageLogHandler
from handlers.contests.manage.qa import (
    ContestManageAnnounceHandler,
    ContestManageQACallback,
    ContestManageQuestionHandler,
    contest_manage_announce_dispatcher,
    contest_manage_question_dispatcher,
)
from services.contests import ContestService
from services.log import LogService
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Base,
    Subject,
    contest,
    original,
)


class TestContestQA(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for name in (
            "get_all_question",
            "get_question",
            "reply_question",
            "get_all_announce",
            "add_announce",
            "edit_announce",
            "get_announce",
        ):
            setattr(self.contests, name, AsyncMock())
        self.logs = SimpleNamespace(
            get_log_type=AsyncMock(return_value=(None, ["contest"])),
            list_log=AsyncMock(
                return_value=(None, {"lognum": 0, "loglist": []})
            ),
            view_log=AsyncMock(),
        )
        active = patch.object(LogService, "inst", self.logs, create=True)
        active.start()
        self.addCleanup(active.stop)

    async def test_post_dispatchers(self):
        for handler, dispatcher in (
            (ContestManageQuestionHandler, contest_manage_question_dispatcher),
            (ContestManageAnnounceHandler, contest_manage_announce_dispatcher),
        ):
            subject = Subject(arguments={"reqtype": "go"})
            with patch.object(
                dispatcher, "dispatch", AsyncMock(return_value="ok")
            ) as dispatch:
                self.assertEqual(await original(handler.post)(subject), "ok")
            dispatch.assert_awaited_once_with(subject, "go")

    async def test_callback_lifecycle_and_filters(self):
        callback = ContestManageQACallback()
        conn = object()
        await callback.register(conn)
        self.assertIsNone(await callback.message(conn, "9"))
        self.assertFalse(await callback.handle_custom_message(conn, "other", "9"))
        self.assertTrue(
            await callback.handle_custom_message(
                conn, "contestnewquessub_init", "9"
            )
        )
        self.assertEqual(await callback.message(conn, "9"), "9")
        self.assertIsNone(await callback.message(conn, "8"))
        self.assertIsNone(await callback.message(conn, "bad"))
        self.assertTrue(
            await callback.handle_custom_message(
                object(), "contestnewquessub_init", "bad"
            )
        )
        await callback.unregister(conn)
        self.assertNotIn(conn, callback.conn_state)

    async def test_question_get_error_and_account_cache(self):
        method = original(ContestManageQuestionHandler.get)
        self.contests.get_all_question.return_value = (("Edb", "failed"), None)
        self.assertEqual((await method(Subject()))[0], "Edb")

        base = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
        self.contests.get_all_question.return_value = (
            None,
            [
                {
                    "ask_acct_id": 1,
                    "reply_acct_id": 2,
                    "ask_timestamp": base,
                    "reply_timestamp": base + datetime.timedelta(minutes=1),
                },
                {
                    "ask_acct_id": 1,
                    "reply_acct_id": 2,
                    "ask_timestamp": base + datetime.timedelta(minutes=2),
                    "reply_timestamp": base + datetime.timedelta(minutes=3),
                },
                {
                    "ask_acct_id": 3,
                    "reply_acct_id": None,
                    "ask_timestamp": base + datetime.timedelta(minutes=4),
                    "reply_timestamp": None,
                },
            ],
        )
        self.users.info_acct.side_effect = lambda acct_id: (
            None,
            SimpleNamespace(acct_id=acct_id),
        )
        subject = Subject()
        await method(subject)
        self.assertEqual(self.users.info_acct.await_count, 3)
        subject.render.assert_awaited_once()

    async def test_reply_paths(self):
        method = ContestManageQuestionHandler.reply_action
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"question_id": "bad", "content": "reply"})
                )
            )[0],
            "Eparam",
        )
        subject = Subject(arguments={"question_id": "1", "content": "reply"})
        subject.len_check.return_value = ("Eparam", "bad")
        self.assertEqual((await method(subject))[0], "Eparam")

        self.contests.get_question.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"question_id": "1", "content": "reply"})
                )
            )[0],
            "Enoext",
        )
        self.contests.get_question.return_value = (
            None, {"ask_acct_id": 22}
        )
        subject = Subject(
            arguments={"question_id": "1", "content": " reply "}
        )
        self.assertEqual(await method(subject), ("S", ""))
        self.contests.reply_question.assert_awaited_once_with(9, 1, 7, "reply")
        subject.rs.publish.assert_awaited_once()

    async def test_announce_get_add_and_edit(self):
        get_method = original(ContestManageAnnounceHandler.get)
        self.contests.get_all_announce.return_value = (("Edb", "failed"), None)
        self.assertEqual((await get_method(Subject()))[0], "Edb")
        self.contests.get_all_announce.return_value = (None, [])
        subject = Subject()
        await get_method(subject)
        subject.render.assert_awaited_once()

        add = ContestManageAnnounceHandler.add_announce_action
        subject = Subject(arguments={"subject": "title", "content": "body"})
        subject.len_check.side_effect = [("Eparam", "subject"), None]
        self.assertEqual((await add(subject))[0], "Eparam")
        subject = Subject(arguments={"subject": "title", "content": "body"})
        subject.len_check.side_effect = [None, ("Eparam", "content")]
        self.assertEqual((await add(subject))[0], "Eparam")

        value = contest()
        value.is_start.return_value = False
        subject = Subject(
            value, {"subject": " title ", "content": " body "}
        )
        self.assertEqual(await add(subject), ("S", ""))
        subject.rs.publish.assert_not_awaited()
        subject = Subject(arguments={"subject": "title", "content": "body"})
        await add(subject)
        subject.rs.publish.assert_awaited_once()

        edit = ContestManageAnnounceHandler.edit_announce_action
        self.assertEqual(
            (
                await edit(
                    Subject(
                        arguments={
                            "announce_id": "bad",
                            "subject": "title",
                            "content": "body",
                        }
                    )
                )
            )[0],
            "Eparam",
        )
        subject = Subject(
            arguments={"announce_id": "1", "subject": "title", "content": "body"}
        )
        subject.len_check.side_effect = [("Eparam", "subject"), None]
        self.assertEqual((await edit(subject))[0], "Eparam")
        subject = Subject(
            arguments={"announce_id": "1", "subject": "title", "content": "body"}
        )
        subject.len_check.side_effect = [None, ("Eparam", "content")]
        self.assertEqual((await edit(subject))[0], "Eparam")
        subject = Subject(
            arguments={
                "announce_id": "1",
                "subject": " title ",
                "content": " body ",
            }
        )
        self.assertEqual(await edit(subject), ("S", ""))
        self.contests.edit_announce.assert_awaited_once_with(
            9, 1, "title", "body"
        )
        subject.rs.publish.assert_awaited_once()

    async def test_popup_paths(self):
        method = ContestManageAnnounceHandler.popup_announce_action
        self.assertEqual(
            (
                await method(Subject(arguments={"announce_id": "bad"}))
            )[0],
            "Eparam",
        )
        self.contests.get_announce.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (
                await method(Subject(arguments={"announce_id": "1"}))
            )[0],
            "Enoext",
        )
        self.contests.get_announce.return_value = (
            None,
            {
                "subject": "Notice",
                "content": "Body",
                "timestamp": datetime.datetime(
                    2025, 1, 1, tzinfo=datetime.UTC
                ),
            },
        )
        subject = Subject(arguments={"announce_id": "1"})
        with patch("handlers.contests.manage.qa.config.TIMEZONE", datetime.UTC):
            self.assertEqual(await method(subject), ("S", ""))
        subject.rs.publish.assert_awaited_once()


class TestContestLog(TestContestQA):
    async def test_list_paths(self):
        method = original(ContestManageLogHandler.get)
        self.assertEqual(
            (await method(Subject(arguments={"pageoff": "bad"})))[0],
            "Eparam",
        )
        self.logs.get_log_type.return_value = (("Edb", "failed"), None)
        self.assertEqual((await method(Subject()))[0], "Edb")

        self.logs.get_log_type.return_value = (None, ["contest"])
        self.logs.list_log.return_value = (("Edb", "failed"), None)
        self.assertEqual((await method(Subject()))[0], "Edb")
        self.logs.list_log.return_value = (None, None)
        self.assertEqual((await method(Subject()))[0], "Eunk")

        self.logs.list_log.return_value = (
            None, {"lognum": 1, "loglist": [{"log_id": 1}]}
        )
        subject = Subject(
            arguments={"pageoff": "-5", "logtype": "contest.manage"}
        )
        await method(subject)
        self.logs.list_log.assert_awaited_with(
            0, 50, log_type="contest.manage", contest_id=9
        )
        subject = Subject(arguments={"pageoff": "0", "logtype": ""})
        await method(subject)
        self.logs.list_log.assert_awaited_with(
            0, 50, log_type=None, contest_id=9
        )

    async def test_detail_paths(self):
        method = original(ContestManageLogHandler.get)
        for log_id in ("bad", "0"):
            self.assertEqual((await method(Subject(), log_id))[0], "Eparam")
        self.logs.view_log.return_value = (("Enoext", "missing"), None)
        self.assertEqual((await method(Subject(), "1"))[0], "Enoext")
        self.logs.view_log.return_value = (None, None)
        self.assertEqual((await method(Subject(), "1"))[0], "Eunk")
        self.logs.view_log.return_value = (None, {"contest_id": 10})
        self.assertEqual((await method(Subject(), "1"))[0], "Eacces")
        self.logs.view_log.return_value = (
            None, {"contest_id": 9, "log_id": 1}
        )
        subject = Subject()
        await method(subject, "1")
        subject.render.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
