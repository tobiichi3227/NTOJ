import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import tornado.web

from handlers.pro import ProHandler, ProStaticHandler, ProTagsHandler, ProsetHandler
from services.chal import ChalConst, ChalService
from services.judge import JudgeServerClusterService
from services.pro import ProClassConst, ProClassService, ProConst, ProService
from services.rate import RateService
from services.user import UserConst, UserService


def original(function):
    seen = set()
    while function.__name__ == "wrap" and function not in seen:
        seen.add(function)
        nested = [
            cell.cell_contents
            for cell in (function.__closure__ or ())
            if inspect.iscoroutinefunction(cell.cell_contents)
        ]
        if len(nested) != 1:
            raise AssertionError(f"Cannot unwrap {function}: {nested}")
        function = nested[0]
    return function


class Subject:
    def __init__(self, arguments=None, contest=None):
        self.arguments = arguments or {}
        self.contest = contest
        self.error = MagicMock(side_effect=lambda value: value)
        self.render = AsyncMock(return_value="rendered")
        self.add_log = AsyncMock(return_value=(None, 1))
        self.set_status = MagicMock()
        self.set_header = MagicMock()
        self.finish = MagicMock()
        self.acct = MagicMock(
            acct_id=7,
            acct_type=UserConst.ACCTTYPE_USER,
            name="member",
            proclass_collection=[],
        )
        self.acct.is_guest.return_value = False
        self.acct.is_kernel.return_value = False

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


def problem(pro_id=1, *, status=ProConst.STATUS_ONLINE, tags="math"):
    return SimpleNamespace(
        pro_id=pro_id,
        name=f"Problem {pro_id}",
        status=status,
        tags=tags,
    )


class TestProblemSetHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pro_service = SimpleNamespace(list_pro=AsyncMock())
        self.proclass_service = SimpleNamespace(
            get_proclass=AsyncMock(), get_proclass_list=AsyncMock()
        )
        self.rate_service = SimpleNamespace(
            map_rate_acct=AsyncMock(return_value=(None, {})),
            get_pro_topcoder=AsyncMock(return_value=(None, None)),
            get_pro_ac_rate=AsyncMock(
                return_value=(
                    None,
                    {
                        "user_ac_chal_cnt": 0,
                        "user_all_chal_cnt": 0,
                        "ac_chal_cnt": 0,
                        "all_chal_cnt": 0,
                    },
                )
            ),
        )
        self.user_service = SimpleNamespace(
            info_acct=AsyncMock(return_value=(None, SimpleNamespace(name="creator"))),
            list_acct=AsyncMock(return_value=(None, [])),
            update_acct=AsyncMock(return_value=(None, None)),
        )
        for service, value in (
            (ProService, self.pro_service),
            (ProClassService, self.proclass_service),
            (RateService, self.rate_service),
            (UserService, self.user_service),
        ):
            active_patch = patch.object(service, "inst", value, create=True)
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def test_get_proclass_errors_visibility_and_creator(self):
        method = original(ProsetHandler.get)
        self.pro_service.list_pro.return_value = (None, [problem(1), problem(2)])

        subject = Subject({"proclass_id": "9"})
        subject.acct.is_kernel.return_value = True
        self.proclass_service.get_proclass.return_value = (("Enoext", "gone"), None)
        self.assertEqual(await method(subject), ("Enoext", "gone"))
        self.pro_service.list_pro.assert_awaited_with(ProConst.PRO_STATUS_KERNEL_USER)

        hidden = {
            "proclass_id": 9,
            "acct_id": 0,
            "type": ProClassConst.OFFICIAL_HIDDEN,
            "list": [1],
        }
        subject = Subject({"proclass_id": "9"})
        self.proclass_service.get_proclass.return_value = (None, hidden)
        self.assertEqual((await method(subject))[0], "Eacces")

        user_hidden = {
            "proclass_id": 10,
            "acct_id": 99,
            "type": ProClassConst.USER_HIDDEN,
            "list": [1],
        }
        subject = Subject({"proclass_id": "10"})
        self.proclass_service.get_proclass.return_value = (None, user_hidden)
        self.assertEqual((await method(subject))[0], "Eacces")

        visible = {
            "proclass_id": 11,
            "acct_id": 7,
            "type": ProClassConst.USER_HIDDEN,
            "list": [1],
        }
        subject = Subject({"proclass_id": "11"})
        self.proclass_service.get_proclass.return_value = (None, visible)
        self.pro_service.list_pro.return_value = (None, [problem(1), problem(2)])
        await method(subject)
        rendered = subject.render.await_args.kwargs
        self.assertEqual([item.pro_id for item in rendered["prolist"]], [1])
        self.assertEqual(rendered["cur_proclass"]["creator_name"], "creator")

    async def test_get_filter_branches_remove_nonmatching_problems(self):
        method = original(ProsetHandler.get)

        async def run(arguments, candidate, *, states=None, topcoder=None):
            subject = Subject(arguments)
            self.pro_service.list_pro.return_value = (None, [candidate])
            self.rate_service.map_rate_acct.return_value = (None, states or {})
            self.rate_service.get_pro_topcoder.return_value = (None, topcoder)
            await method(subject)
            self.assertEqual(subject.render.await_args.kwargs["prolist"], [])

        await run({"online": "1"}, problem(1, status=ProConst.STATUS_HIDDEN))
        await run(
            {"show": "notac"},
            problem(1),
            states={1: {"state": ChalConst.STATE_AC}},
        )
        await run({"topcoder": "myself"}, problem(1), topcoder=8)
        await run({"topcoder": "other"}, problem(1), topcoder=7)
        await run({"topcoder": "99"}, problem(1), topcoder=8)

    async def test_post_list_problem_class_propagates_problem_list_error(self):
        method = original(ProsetHandler.post)
        self.proclass_service.get_proclass_list.return_value = (
            None,
            [
                {
                    "proclass_id": 1,
                    "acct_id": 0,
                    "type": ProClassConst.OFFICIAL_PUBLIC,
                }
            ],
        )
        self.pro_service.list_pro.return_value = (("Edb", "failed"), None)
        subject = Subject({"reqtype": "listproclass", "proclass_type": "official"})
        self.assertEqual(await method(subject), ("Edb", "failed"))


class TestProblemStaticHandler(unittest.IsolatedAsyncioTestCase):
    def make_handler(self, contest=None):
        handler = object.__new__(ProStaticHandler)
        handler.contest = contest
        handler.acct = MagicMock(acct_id=7)
        handler.acct.is_kernel.return_value = False
        handler.error = MagicMock(side_effect=lambda value: value)
        handler.set_status = MagicMock()
        handler.set_header = MagicMock()
        handler.finish = MagicMock()
        handler.arguments = {}
        handler.get_argument = lambda name, default=None: handler.arguments.get(
            name, default
        )
        return handler

    async def test_get_validates_path_problem_contest_and_service_errors(self):
        method = original(ProStaticHandler.get)
        pro_service = SimpleNamespace(get_pro=AsyncMock())
        with patch.object(ProService, "inst", pro_service, create=True):
            handler = self.make_handler()
            self.assertEqual(
                await method(handler, "1", None), ("Eparam", "Path is required")
            )
            self.assertEqual(
                await method(handler, "bad", "cont.pdf"),
                ("Eparam", "Invalid problem ID"),
            )

            contest = MagicMock()
            contest.is_pro.return_value = False
            handler = self.make_handler(contest)
            await method(handler, "1", "cont.pdf")
            handler.set_status.assert_called_with(404)

            contest.is_pro.return_value = True
            contest.is_member.return_value = False
            handler = self.make_handler(contest)
            await method(handler, "1", "cont.pdf")
            handler.set_status.assert_called_with(403)

            contest.is_member.return_value = True
            contest.is_admin.return_value = False
            contest.is_running.return_value = False
            handler = self.make_handler(contest)
            await method(handler, "1", "cont.pdf")
            handler.set_status.assert_called_with(403)

            for error, status in (
                (("Enoext", "missing"), 404),
                (("Eacces", "denied"), 403),
                (("Edb", "failed"), 500),
            ):
                handler = self.make_handler()
                pro_service.get_pro.return_value = (error, None)
                await method(handler, "1", "cont.pdf")
                handler.set_status.assert_called_with(status)
                handler.finish.assert_called_with(error[1])

    async def test_get_pdf_headers_safe_download_inline_and_unsafe_path(self):
        method = original(ProStaticHandler.get)
        pro_service = SimpleNamespace(get_pro=AsyncMock(return_value=(None, object())))
        static_get = AsyncMock()
        with (
            patch.object(ProService, "inst", pro_service, create=True),
            patch.object(tornado.web.StaticFileHandler, "get", new=static_get),
        ):
            handler = self.make_handler()
            handler.arguments["download"] = "1"
            handler._is_file_access_safe = MagicMock(return_value=True)
            await method(handler, "3", "cont.pdf")
            handler.set_header.assert_any_call(
                "Content-Disposition", 'attachment; filename="pro3.pdf"'
            )
            static_get.assert_awaited_with("3/http/cont.pdf")

            handler = self.make_handler()
            handler._is_file_access_safe = MagicMock(return_value=True)
            await method(handler, "3", "cont.pdf")
            handler.set_header.assert_any_call("Content-Disposition", "inline")

            handler = self.make_handler()
            handler._is_file_access_safe = MagicMock(return_value=False)
            await method(handler, "3", "../secret")
            handler.set_status.assert_called_with(403)
            handler.finish.assert_called_with("Permission denied")

    def test_file_access_safety_rejects_escape_links_and_non_files(self):
        method = ProStaticHandler._is_file_access_safe
        self.assertFalse(method(object(), "problem/1/http", "../secret"))

        with (
            patch("handlers.pro.os.path.exists", return_value=True),
            patch("handlers.pro.os.path.isfile", return_value=True),
            patch("handlers.pro.os.path.islink", return_value=False),
        ):
            self.assertTrue(method(object(), "problem/1/http", "cont.pdf"))

        with (
            patch("handlers.pro.os.path.exists", return_value=True),
            patch("handlers.pro.os.path.isfile", return_value=True),
            patch("handlers.pro.os.path.islink", return_value=True),
        ):
            self.assertFalse(method(object(), "problem/1/http", "link.pdf"))

        with patch("handlers.pro.os.path.exists", return_value=False):
            self.assertTrue(method(object(), "problem/1/http", "new.pdf"))


class TestProblemDetailAndTags(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pro_service = SimpleNamespace(get_pro=AsyncMock(), update_pro=AsyncMock())
        self.chal_service = SimpleNamespace(check_acct_pro_state=AsyncMock())
        self.rate_service = SimpleNamespace(get_pro_topcoder=AsyncMock())
        self.user_service = SimpleNamespace(info_acct=AsyncMock())
        self.judge_service = SimpleNamespace(is_server_online=MagicMock(return_value=True))
        for service, value in (
            (ProService, self.pro_service),
            (ChalService, self.chal_service),
            (RateService, self.rate_service),
            (UserService, self.user_service),
            (JudgeServerClusterService, self.judge_service),
        ):
            active_patch = patch.object(service, "inst", value, create=True)
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def test_problem_get_validation_contest_and_service_error_branches(self):
        method = original(ProHandler.get)
        self.assertEqual(
            await method(Subject(), "bad"), ("Eparam", "Invalid problem ID")
        )

        contest = MagicMock()
        contest.is_pro.return_value = False
        self.assertEqual((await method(Subject(contest=contest), "1"))[0], "Enoext")
        contest.is_pro.return_value = True
        contest.is_member.return_value = False
        self.assertEqual((await method(Subject(contest=contest), "1"))[0], "Eacces")
        contest.is_member.return_value = True
        contest.is_admin.return_value = False
        contest.is_running.return_value = False
        self.assertEqual((await method(Subject(contest=contest), "1"))[0], "Eacces")

        subject = Subject()
        subject.acct.is_kernel.return_value = True
        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(await method(subject, "1"), ("Enoext", "missing"))
        self.pro_service.get_pro.assert_awaited_with(1, ProConst.PRO_STATUS_KERNEL_USER)

    async def test_problem_get_hides_tags_and_propagates_rate_owner_errors(self):
        method = original(ProHandler.get)
        pro = problem()
        subject = Subject()
        subject.acct.is_guest.return_value = True
        self.pro_service.get_pro.return_value = (None, pro)
        self.rate_service.get_pro_topcoder.return_value = (("Edb", "rate"), None)
        self.assertEqual(await method(subject, "1"), ("Edb", "rate"))
        self.assertEqual(pro.tags, "")

        pro = problem()
        subject = Subject()
        self.pro_service.get_pro.return_value = (None, pro)
        self.chal_service.check_acct_pro_state.return_value = (("Edb", "state"), None)
        self.assertEqual(await method(subject, "1"), ("Edb", "state"))

        self.chal_service.check_acct_pro_state.return_value = (None, None)
        self.rate_service.get_pro_topcoder.return_value = (None, 9)
        self.user_service.info_acct.return_value = (("Enoext", "owner"), None)
        self.assertEqual((await method(subject, "1"))[0], "Enoext")
        self.assertEqual(pro.tags, "")

        self.user_service.info_acct.return_value = (
            None,
            SimpleNamespace(acct_id=9, name="topcoder"),
        )
        await method(subject, "1")
        self.assertEqual(subject.render.await_args.kwargs["topcoder"].name, "topcoder")

        contest = MagicMock()
        contest.is_pro.return_value = True
        contest.is_member.return_value = True
        contest.is_admin.return_value = True
        pro = problem()
        subject = Subject(contest=contest)
        subject.acct.is_kernel.return_value = False
        self.pro_service.get_pro.return_value = (None, pro)
        self.chal_service.check_acct_pro_state.return_value = (None, ChalConst.STATE_AC)
        await method(subject, "1")
        self.assertEqual(pro.tags, "math")
        self.assertIsNone(subject.render.await_args.kwargs["topcoder"])

    async def test_problem_tags_uses_contest_status_and_propagates_updates(self):
        method = original(ProTagsHandler.post)
        contest = object()
        subject = Subject({"pro_id": "1", "tags": "dp"}, contest=contest)
        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(await method(subject), ("Enoext", "missing"))
        self.pro_service.get_pro.assert_awaited_with(1, ProConst.PRO_STATUS_CONTEST_USER)

        pro = problem()
        self.pro_service.get_pro.return_value = (None, pro)
        self.pro_service.update_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual(await method(subject), ("Edb", "failed"))
        self.assertEqual(pro.tags, "dp")

        self.pro_service.update_pro.return_value = (None, None)
        await method(subject)
        subject.error.assert_called_with(("S", ""))
        subject.add_log.assert_awaited()


if __name__ == "__main__":
    unittest.main()
