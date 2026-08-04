import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.acct import (
    AcctConfigHandler,
    AcctHandler,
    AcctProClassHandler,
    SignHandler,
)
from services.chal import ChalConst
from services.pro import (
    ProClassConst,
    ProClassService,
    ProService,
)
from services.rate import RateService
from services.user import UserService
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Subject,
    original,
)


class TestAccountHandlerCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.users = SimpleNamespace(info_acct=AsyncMock())
        self.rates = SimpleNamespace(
            get_acct_rate_and_chal_cnt=AsyncMock(),
            map_rate_acct=AsyncMock(),
            get_pro_topcoder=AsyncMock(return_value=(None, 99)),
        )
        self.problems = SimpleNamespace(list_pro=AsyncMock())
        self.classes = SimpleNamespace(
            get_proclass_list=AsyncMock(return_value=(None, [])),
            get_proclass=AsyncMock(),
            add_proclass=AsyncMock(),
            update_proclass=AsyncMock(),
            remove_proclass=AsyncMock(),
        )
        for service, value in (
            (UserService, self.users),
            (RateService, self.rates),
            (ProService, self.problems),
            (ProClassService, self.classes),
        ):
            active = patch.object(
                service, "inst", value, create=True
            )
            active.start()
            self.addCleanup(active.stop)

    def profile_account(self):
        return SimpleNamespace(
            acct_id=1,
            acct_type=0,
            name="user",
            photo="http://example/photo",
            cover="http://example/cover",
        )

    async def test_profile_validation_and_service_errors(self):
        method = original(AcctHandler.get)
        self.assertEqual((await method(Subject(), None))[0], "Eparam")

        self.users.info_acct.return_value = (
            ("Enoext", "missing"),
            None,
        )
        self.assertEqual(
            (await method(Subject(), "1"))[0],
            "Enoext",
        )

        account = self.profile_account()
        self.users.info_acct.return_value = (None, account)
        self.rates.get_acct_rate_and_chal_cnt.return_value = (
            ("Edb", "rate"),
            None,
        )
        self.assertEqual(
            (await method(Subject(), "1"))[0],
            "Edb",
        )

        self.rates.get_acct_rate_and_chal_cnt.return_value = (
            None,
            {"rate": 1},
        )
        self.problems.list_pro.return_value = (
            ("Edb", "problem"),
            None,
        )
        self.assertEqual(
            (await method(Subject(), "1"))[0],
            "Edb",
        )

    async def test_profile_ratemap_problem_state(self):
        account = self.profile_account()
        self.users.info_acct.return_value = (None, account)
        self.rates.get_acct_rate_and_chal_cnt.return_value = (
            None,
            {"rate": 100.9},
        )
        self.problems.list_pro.return_value = (
            None,
            [SimpleNamespace(pro_id=5), SimpleNamespace(pro_id=6)],
        )
        self.rates.map_rate_acct.return_value = (
            None,
            {
                5: {
                    "rate": 77.5,
                    "state": ChalConst.STATE_AC,
                }
            },
        )
        subject = Subject()
        subject.rs.hgetall.return_value = {}
        await original(AcctHandler.get)(subject, "1")
        rate = subject.render.call_args.kwargs["rate"]
        pages = list(subject.render.call_args.kwargs["prolist"])
        self.assertEqual(rate["rate"], 100)
        self.assertEqual(rate["ac_pro_cnt"], 1)
        self.assertEqual(len(pages[0]), 2)
        self.assertIsNone(pages[0][1]["state"])
        self.assertEqual(account.photo, "https://example/photo")

    async def test_account_config_invalid_and_lookup_error(self):
        method = original(AcctConfigHandler.get)
        self.assertEqual(
            (await method(Subject(), "bad"))[0],
            "Eparam",
        )

        self.users.info_acct.return_value = (
            ("Enoext", "missing"),
            None,
        )
        self.assertEqual(
            (await method(Subject(), "1"))[0],
            "Enoext",
        )

        self.users.info_acct.return_value = (
            None,
            self.profile_account(),
        )
        subject = Subject()
        await method(subject, "8")
        subject.render.assert_awaited_once()
        self.assertEqual(subject.render.call_args.kwargs["session_keys"], {})
        self.assertIsNone(
            subject.render.call_args.kwargs["current_session_key"]
        )

    async def test_remote_logout_all_sessions(self):
        subject = Subject()
        subject.target_acct_id = subject.acct.acct_id
        subject.rs.hgetall.return_value = {
            b"session-one": b"value",
            b"session-two": b"value",
        }
        subject.clear_cookie = MagicMock()
        result = await AcctConfigHandler.remote_logout_all(subject)
        self.assertEqual(result, ("S", ""))
        self.assertEqual(subject.rs.publish.await_count, 2)
        subject.rs.delete.assert_awaited_once()
        subject.clear_cookie.assert_called_once_with("id")

    async def test_proclass_get_and_post_validation_and_ownership(self):
        get_method = original(AcctProClassHandler.get)
        self.assertEqual(
            (await get_method(Subject(), "bad"))[0],
            "Eparam",
        )

        self.classes.get_proclass.return_value = (
            None,
            {
                "acct_id": 99,
                "name": "other",
            },
        )
        self.assertEqual(
            (
                await get_method(
                    Subject(
                        arguments={
                            "page": "update",
                            "proclassid": "1",
                        }
                    ),
                    "7",
                )
            )[0],
            "Eacces",
        )

        subject = Subject(arguments={"reqtype": "add"})
        self.assertEqual(
            (
                await original(AcctProClassHandler.post)(
                    subject, "bad"
                )
            )[0],
            "Eparam",
        )

        subject = Subject(arguments={"page": "unknown"})
        self.assertIsNone(await get_method(subject, "7"))

    def proclass_arguments(self, **overrides):
        values = {
            "proclass_id": "1",
            "type": str(ProClassConst.USER_PUBLIC),
            "list": "1-2",
            "name": "Class",
            "desc": "Description",
        }
        values.update(overrides)
        return values

    async def test_add_proclass_service_error(self):
        self.classes.add_proclass.return_value = (
            ("Edb", "failed"),
            None,
        )
        result = await AcctProClassHandler.add_proclass(
            Subject(arguments=self.proclass_arguments())
        )
        self.assertEqual(result[0], "Edb")

    async def test_update_proclass_type_desc_and_service_errors(self):
        result = await AcctProClassHandler.update_proclass(
            Subject(
                arguments=self.proclass_arguments(type="999")
            )
        )
        self.assertEqual(result[0], "Eparam")

        subject = Subject(
            arguments=self.proclass_arguments()
        )
        subject.len_check.side_effect = [
            None,
            ("Eparam", "desc"),
        ]
        self.assertEqual(
            (await AcctProClassHandler.update_proclass(subject))[0],
            "Eparam",
        )

        self.classes.get_proclass.return_value = (
            None,
            {
                "acct_id": 7,
                "name": "owned",
            },
        )
        self.classes.update_proclass.return_value = (
            "Edb",
            "failed",
        )
        result = await AcctProClassHandler.update_proclass(
            Subject(arguments=self.proclass_arguments())
        )
        self.assertEqual(result[0], "Edb")


class TestSignHandlerCompletion(unittest.IsolatedAsyncioTestCase):
    async def test_signed_in_get_and_signout_without_session_cookie(self):
        subject = Subject()
        subject.acct.is_guest.return_value = False
        subject.write = MagicMock(return_value="redirect")
        self.assertEqual(
            await original(SignHandler.get)(subject),
            "redirect",
        )
        subject.write.assert_called_once()

        subject = Subject()
        subject.acct.is_guest.return_value = False
        subject.get_cookie = MagicMock(return_value=None)
        subject.clear_cookie = MagicMock()
        await SignHandler.sign_out(subject)
        subject.rs.hdel.assert_not_awaited()
        subject.clear_cookie.assert_called_once()


if __name__ == "__main__":
    unittest.main()
