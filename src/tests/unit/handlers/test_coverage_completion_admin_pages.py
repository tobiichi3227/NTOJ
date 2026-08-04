import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from msgpack import packb

from handlers.manage.acct import ManageAcctHandler, acct_dispatcher
from handlers.manage.question import (
    ManageQuestionHandler,
    question_dispatcher,
)
from services.ques import QuestionService
from services.user import UserConst, UserService
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Subject,
    original,
)


class TestAdminAccountAndQuestion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.users = SimpleNamespace(
            list_acct=AsyncMock(return_value=(None, [])),
            info_acct=AsyncMock(),
            update_acct=AsyncMock(return_value=(None, None)),
        )
        self.questions = SimpleNamespace(
            get_queslist=AsyncMock(),
            reply=AsyncMock(),
        )
        for service, value in (
            (UserService, self.users),
            (QuestionService, self.questions),
        ):
            active = patch.object(service, "inst", value, create=True)
            active.start()
            self.addCleanup(active.stop)

    async def test_account_get_list_update_and_dispatch(self):
        method = original(ManageAcctHandler.get)
        self.assertEqual(
            (await method(Subject(arguments={"pageoff": "bad"}), None))[0],
            "Eparam",
        )
        for pageoff in ("-1", "0"):
            self.users.list_acct.return_value = (
                None, [SimpleNamespace(acct_id=1)]
            )
            subject = Subject(arguments={"pageoff": pageoff})
            await method(subject, None)
            subject.render.assert_awaited_once()

        self.assertEqual(
            (
                await method(
                    Subject(arguments={"acctid": "bad"}), "update"
                )
            )[0],
            "Eparam",
        )
        self.users.info_acct.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"acctid": "2"}), "update"
                )
            )[0],
            "Enoext",
        )
        self.users.info_acct.return_value = (
            None, SimpleNamespace(acct_id=2, name="user")
        )
        subject = Subject(arguments={"acctid": "2"})
        await method(subject, "update")
        subject.render.assert_awaited_once()

        subject = Subject(arguments={"reqtype": "update"})
        with patch.object(
            acct_dispatcher, "dispatch", AsyncMock(return_value="ok")
        ) as dispatch:
            self.assertEqual(
                await original(ManageAcctHandler.post)(subject), "ok"
            )
        dispatch.assert_awaited_once_with(subject, "update")

    async def test_account_update_validation_service_and_ip_paths(self):
        method = ManageAcctHandler.update_acct
        base = {"acct_id": "2", "acct_type": "1", "specific_ip": ""}

        self.assertEqual(
            (
                await method(
                    Subject(arguments={**base, "acct_id": "bad"})
                )
            )[0],
            "Eparam",
        )
        self.assertEqual(
            (
                await method(
                    Subject(arguments={**base, "acct_type": "bad"})
                )
            )[0],
            "Eparam",
        )

        self.users.info_acct.return_value = (("Enoext", "missing"), None)
        self.assertEqual((await method(Subject(arguments=base)))[0], "Enoext")

        account = SimpleNamespace(
            acct_id=2, acct_type=0, specific_ip="", name="user"
        )
        self.users.info_acct.return_value = (None, account)
        self.assertEqual(
            (
                await method(
                    Subject(
                        arguments={**base, "specific_ip": "not-an-ip"}
                    )
                )
            )[0],
            "Einval",
        )

        self.users.update_acct.return_value = (("Edb", "failed"), None)
        self.assertEqual(
            (
                await method(
                    Subject(
                        arguments={**base, "specific_ip": "127.0.0.1"}
                    )
                )
            )[0],
            "Edb",
        )

        self.users.update_acct.return_value = (None, None)
        subject = Subject(arguments=base)
        self.assertIsNone(await method(subject))
        subject.error.assert_called_with(("S", ""))

    async def test_question_get_list_reply_pages_and_dispatch(self):
        method = original(ManageQuestionHandler.get)
        accounts = [
            SimpleNamespace(acct_id=2),
            SimpleNamespace(acct_id=3),
        ]
        self.users.list_acct.return_value = (None, accounts)
        subject = Subject()
        subject.rs.get.side_effect = [None, packb("waiting")]
        await method(subject, None)
        subject.render.assert_awaited_once()

        self.assertEqual(
            (
                await method(
                    Subject(arguments={"qacct": "bad"}), "reply"
                )
            )[0],
            "Eparam",
        )
        self.questions.get_queslist.return_value = (
            ("Edb", "failed"), None
        )
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"qacct": "2"}), "reply"
                )
            )[0],
            "Edb",
        )
        self.questions.get_queslist.return_value = (None, [])
        subject = Subject(arguments={"qacct": "2"})
        await method(subject, "reply")
        subject.render.assert_awaited_once()

        subject = Subject(arguments={"reqtype": "rpl"})
        with patch.object(
            question_dispatcher, "dispatch", AsyncMock(return_value="ok")
        ) as dispatch:
            self.assertEqual(
                await original(ManageQuestionHandler.post)(subject, "reply"),
                "ok",
            )
        dispatch.assert_awaited_once_with(subject, "rpl")
        self.assertIsNone(
            await original(ManageQuestionHandler.post)(Subject(), None)
        )

    def question_args(self, **overrides):
        values = {
            "rtext": "reply",
            "index": "1",
            "qacct_id": "2",
        }
        values.update(overrides)
        return values

    async def test_reply_and_rereply_validation_and_success(self):
        for method in (
            ManageQuestionHandler.reply_question,
            ManageQuestionHandler.re_reply_question,
        ):
            subject = Subject(arguments=self.question_args())
            subject.len_check.return_value = ("Eparam", "bad")
            self.assertEqual((await method(subject))[0], "Eparam")

            self.assertEqual(
                (
                    await method(
                        Subject(
                            arguments=self.question_args(index="bad")
                        )
                    )
                )[0],
                "Eparam",
            )
            self.assertEqual(
                (
                    await method(
                        Subject(
                            arguments=self.question_args(qacct_id="bad")
                        )
                    )
                )[0],
                "Eparam",
            )
            subject = Subject(arguments=self.question_args())
            self.assertIsNone(await method(subject))
            subject.error.assert_called_with(("S", ""))


if __name__ == "__main__":
    unittest.main()
