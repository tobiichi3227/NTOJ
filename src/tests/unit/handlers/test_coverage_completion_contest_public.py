import datetime
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.contests.qa import (
    ASK_CD_TIME,
    ContestQACallback,
    ContestQAHandler,
    contest_qa_dispatcher,
)
from handlers.contests.reg import ContestRegHandler, contest_reg_dispatcher
from services.contests import ContestService, RegMode, UserStatus
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Base,
    Subject,
    contest,
    original,
)


def registration_contest(**overrides):
    values = {
        "contest_start": datetime.datetime(2030, 1, 2, tzinfo=datetime.UTC),
        "contest_end": datetime.datetime(2030, 1, 3, tzinfo=datetime.UTC),
        "reg_end": datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC),
        "reg_mode": RegMode.FREE_REG,
        "user_list": {1: {"status": UserStatus.ADMIN}},
    }
    values.update(overrides)
    value = contest(**values)
    value.is_admin = MagicMock(return_value=False)
    value.member_is_status = MagicMock(
        side_effect=lambda acct_id, status: (
            acct_id in value.user_list
            and value.user_list[acct_id]["status"] == status
        )
    )
    return value


class TestContestPublicQA(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for name in (
            "get_all_announce",
            "get_all_question",
            "mark_notifications_as_read",
            "ask_question",
        ):
            setattr(self.contests, name, AsyncMock())

    async def test_callback_routes_messages_and_bad_data(self):
        callback = ContestQACallback()
        conn = MagicMock(acct_id=7)
        await callback.register(conn)
        self.assertIsNone(await callback.message(conn, "{}"))
        self.assertFalse(await callback.handle_custom_message(conn, "other", "{}"))
        self.assertTrue(
            await callback.handle_custom_message(
                object(), "contestnewqasub_init", '{"contest_id": 9}'
            )
        )
        self.assertTrue(
            await callback.handle_custom_message(
                conn, "contestnewqasub_init", '{"contest_id": 9}'
            )
        )

        announce = json.dumps({"contest_id": 9, "type": "announce"})
        reply = json.dumps(
            {"contest_id": 9, "type": "reply", "ask_acct_id": 7}
        )
        self.assertEqual(await callback.message(conn, announce), announce)
        self.assertEqual(await callback.message(conn, reply), reply)
        self.assertIsNone(
            await callback.message(
                conn,
                json.dumps(
                    {"contest_id": 9, "type": "reply", "ask_acct_id": 8}
                ),
            )
        )
        self.assertIsNone(
            await callback.message(
                conn, json.dumps({"contest_id": 10, "type": "announce"})
            )
        )
        self.assertIsNone(await callback.message(conn, "bad-json"))
        self.assertTrue(
            await callback.handle_custom_message(
                conn, "contestnewqasub_init", "bad-json"
            )
        )
        await callback.unregister(conn)
        await callback.unregister(conn)

    async def test_get_permission_time_and_service_paths(self):
        method = original(ContestQAHandler.get)
        value = registration_contest()
        value.is_admin.return_value = True
        self.assertEqual((await method(Subject(value)))[0], "Eacces")

        value = registration_contest()
        value.is_start.return_value = True
        self.contests.get_all_announce.return_value = (("Edb", "failed"), None)
        self.assertEqual((await method(Subject(value)))[0], "Edb")

        value.is_start.return_value = False
        self.contests.get_all_question.return_value = (("Edb", "failed"), None)
        self.assertEqual((await method(Subject(value)))[0], "Edb")

        self.contests.get_all_question.return_value = (
            None,
            [
                {
                    "reply_acct_id": None,
                    "reply_timestamp": None,
                    "ask_timestamp": datetime.datetime(
                        2025, 1, 1, tzinfo=datetime.UTC
                    ),
                }
            ],
        )
        subject = Subject(value)
        await method(subject)
        self.contests.mark_notifications_as_read.assert_awaited_once_with(9, 7)
        subject.render.assert_awaited_once()

        value.is_start.return_value = True
        self.contests.get_all_announce.return_value = (None, [])
        self.contests.get_all_question.return_value = (None, [])
        subject = Subject(value)
        await method(subject)
        subject.render.assert_awaited_once()

    async def test_ask_cooldown_validation_and_both_set_modes(self):
        method = ContestQAHandler.ask_question_action
        args = {"subject": " subject ", "content": " content "}

        subject = Subject(arguments=args)
        subject.rs.get.return_value = b"100"
        with patch("handlers.contests.qa.time.time", return_value=101):
            self.assertEqual((await method(subject))[0], "Einternal")

        subject = Subject(arguments=args)
        subject.rs.get.return_value = None
        subject.len_check.side_effect = [("Eparam", "subject"), None]
        self.assertEqual((await method(subject))[0], "Eparam")
        subject = Subject(arguments=args)
        subject.rs.get.return_value = None
        subject.len_check.side_effect = [None, ("Eparam", "content")]
        self.assertEqual((await method(subject))[0], "Eparam")

        subject = Subject(arguments=args)
        subject.rs.get.return_value = None
        with patch("handlers.contests.qa.time.time", return_value=1000):
            self.assertEqual(await method(subject), ("S", ""))
        subject.rs.set.assert_awaited_once_with(
            "last_ask_time_7_9", 1000, ex=ASK_CD_TIME
        )

        subject = Subject(arguments=args)
        subject.rs.get.return_value = b"100"
        with patch(
            "handlers.contests.qa.time.time",
            side_effect=[1000, 1001],
        ):
            self.assertEqual(await method(subject), ("S", ""))
        subject.rs.set.assert_awaited_once_with("last_ask_time_7_9", 1001)

    async def test_post_dispatch(self):
        subject = Subject(arguments={"reqtype": "ask"})
        with patch.object(
            contest_qa_dispatcher, "dispatch", AsyncMock(return_value="ok")
        ) as dispatch:
            self.assertEqual(await original(ContestQAHandler.post)(subject), "ok")
        dispatch.assert_awaited_once_with(subject, "ask")


class TestContestRegistration(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        active = patch.object(
            Subject, "check", ContestRegHandler.check, create=True
        )
        active.start()
        self.addCleanup(active.stop)
    async def test_get_check_and_post(self):
        method = original(ContestRegHandler.get)
        subject = Subject()
        subject.contest = None
        self.assertEqual((await method(subject))[0], "Enoext")

        value = registration_contest()
        value.is_admin.return_value = True
        self.assertEqual((await method(Subject(value)))[0], "Eacces")

        value.is_admin.return_value = False
        subject = Subject(value)
        await method(subject)
        subject.render.assert_awaited_once()

        handler = ContestRegHandler.check
        value.is_admin.return_value = True
        self.assertEqual(handler(Subject(value), "register")[0], "Eacces")
        value.is_admin.return_value = False
        value.reg_mode = RegMode.INVITED
        self.assertEqual(handler(Subject(value), "register")[0], "Eacces")
        value.reg_mode = RegMode.FREE_REG
        self.assertIsNone(handler(Subject(value), "register"))

        subject = Subject(value, {"reqtype": "reg"})
        with patch.object(
            contest_reg_dispatcher, "dispatch", AsyncMock(return_value="ok")
        ) as dispatch:
            self.assertEqual(await original(ContestRegHandler.post)(subject), "ok")
        dispatch.assert_awaited_once_with(subject, "reg")

    async def test_register_all_status_and_mode_paths(self):
        method = ContestRegHandler.register_action
        value = registration_contest(reg_mode=RegMode.INVITED)
        self.assertEqual((await method(Subject(value)))[0], "Eacces")

        value = registration_contest(
            reg_end=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
        )
        self.assertEqual((await method(Subject(value)))[0], "Etime")

        for status, expected in (
            (UserStatus.REJECTED, "Eacces"),
            (UserStatus.REQUESTED, "Eacces"),
            (UserStatus.APPROVED, "Eexist"),
        ):
            value = registration_contest(
                reg_mode=RegMode.REG_APPROVAL,
                user_list={7: {"status": status}},
            )
            self.assertEqual((await method(Subject(value)))[0], expected)

        value = registration_contest()
        subject = Subject(value)
        self.assertEqual(await method(subject), ("S", "Register Successfully"))
        self.assertEqual(value.user_list[7]["status"], UserStatus.APPROVED)

        value = registration_contest(reg_mode=RegMode.REG_APPROVAL)
        subject = Subject(value)
        self.assertEqual(await method(subject), ("S", "Register Successfully"))
        self.assertEqual(value.user_list[7]["status"], UserStatus.REQUESTED)

    async def test_registration_uses_atomic_membership_operations(self):
        value = registration_contest()
        self.assertEqual(
            await ContestRegHandler.register_action(Subject(value)),
            ("S", "Register Successfully"),
        )
        self.contests.add_contest_user.assert_awaited_once_with(
            9, 7, UserStatus.APPROVED
        )
        self.contests.update_contest.assert_not_awaited()

        self.contests.add_contest_user.return_value = (("Edb", "failed"), None)
        self.assertEqual(
            (await ContestRegHandler.register_action(Subject(registration_contest())))[0],
            "Edb",
        )
        self.contests.add_contest_user.return_value = (None, None)

        requested = registration_contest(
            reg_mode=RegMode.REG_APPROVAL,
            user_list={7: {"status": UserStatus.REQUESTED}},
        )
        self.assertEqual(
            await ContestRegHandler.cancel_request_action(Subject(requested)),
            ("S", "Cancel Request Successfully"),
        )
        self.contests.remove_contest_user.assert_awaited_with(9, 7)

        self.contests.remove_contest_user.return_value = (("Edb", "failed"), None)
        requested = registration_contest(
            reg_mode=RegMode.REG_APPROVAL,
            user_list={7: {"status": UserStatus.REQUESTED}},
        )
        self.assertEqual(
            (await ContestRegHandler.cancel_request_action(Subject(requested)))[0],
            "Edb",
        )

        approved = registration_contest(
            user_list={7: {"status": UserStatus.APPROVED}}
        )
        self.assertEqual(
            (await ContestRegHandler.unregister_action(Subject(approved)))[0],
            "Edb",
        )

    async def test_cancel_request_paths(self):
        method = ContestRegHandler.cancel_request_action
        value = registration_contest(reg_mode=RegMode.INVITED)
        self.assertEqual((await method(Subject(value)))[0], "Eacces")
        value = registration_contest(
            reg_end=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
        )
        self.assertEqual((await method(Subject(value)))[0], "Etime")
        value = registration_contest()
        self.assertEqual((await method(Subject(value)))[0], "Enoext")
        value = registration_contest(
            user_list={7: {"status": UserStatus.APPROVED}}
        )
        self.assertEqual((await method(Subject(value)))[0], "Eacces")
        value = registration_contest(
            reg_mode=RegMode.REG_APPROVAL,
            user_list={7: {"status": UserStatus.REQUESTED}},
        )
        self.assertEqual(
            await method(Subject(value)), ("S", "Cancel Request Successfully")
        )
        self.assertNotIn(7, value.user_list)

    async def test_unregister_paths(self):
        method = ContestRegHandler.unregister_action
        value = registration_contest(reg_mode=RegMode.INVITED)
        self.assertEqual((await method(Subject(value)))[0], "Eacces")
        value = registration_contest(
            contest_start=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
        )
        self.assertEqual((await method(Subject(value)))[0], "Etime")
        value = registration_contest()
        self.assertEqual((await method(Subject(value)))[0], "Enoext")

        for status in (UserStatus.REJECTED, UserStatus.REQUESTED):
            value = registration_contest(
                reg_mode=RegMode.REG_APPROVAL,
                user_list={7: {"status": status}},
            )
            self.assertEqual((await method(Subject(value)))[0], "Eacces")

        value = registration_contest(
            user_list={7: {"status": UserStatus.APPROVED}}
        )
        self.assertEqual(
            await method(Subject(value)), ("S", "Unregister Successfully")
        )
        self.assertNotIn(7, value.user_list)


if __name__ == "__main__":
    unittest.main()
