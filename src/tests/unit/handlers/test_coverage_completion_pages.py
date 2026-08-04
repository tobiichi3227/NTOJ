import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.bulletin import BulletinHandler
from handlers.log import LogHandler
from handlers.manage.bulletin import (
    ManageBulletinHandler,
    bulletin_dispatcher,
)
from handlers.manage.dash import ManageDashHandler
from handlers.manage.judge import ManageJudgeHandler, judge_dispatcher
from handlers.ques import QuestionHandler
from handlers.rank import ProRankHandler, UserRankHandler
from services.bulletin import BulletinService
from services.judge import JudgeServerClusterService
from services.log import LogService
from services.pro import ProService
from services.ques import QuestionService
from services.rank import RankService
from services.user import UserConst


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
    def __init__(self, arguments=None):
        self.arguments = arguments or {}
        self.error = MagicMock(side_effect=lambda value: value)
        self.render = AsyncMock(return_value="rendered")
        self.add_log = AsyncMock(return_value=(None, 1))
        self.len_check = MagicMock(return_value=None)
        self.rs = AsyncMock()
        self.acct = MagicMock(
            acct_id=7,
            acct_type=UserConst.ACCTTYPE_KERNEL,
            name="admin",
        )
        self.acct.is_kernel.return_value = False

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)


class TestPublicPageCoverageCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bulletins = SimpleNamespace(
            list_bulletin=AsyncMock(return_value=(None, [])),
            get_bulletin=AsyncMock(),
        )
        self.logs = SimpleNamespace(
            get_log_type=AsyncMock(return_value=(None, ["judge"])),
            list_log=AsyncMock(return_value=(None, {"lognum": 0, "loglist": []})),
            view_log=AsyncMock(),
        )
        self.problems = SimpleNamespace(get_pro=AsyncMock())
        self.ranks = SimpleNamespace(get_pro_rank=AsyncMock(), get_user_rank=AsyncMock())
        self.questions = SimpleNamespace(
            get_queslist=AsyncMock(),
            set_ques=AsyncMock(),
            rm_ques=AsyncMock(),
        )
        self.judges = SimpleNamespace(is_server_online=MagicMock(return_value=True))
        for service, value in (
            (BulletinService, self.bulletins),
            (JudgeServerClusterService, self.judges),
            (LogService, self.logs),
            (ProService, self.problems),
            (RankService, self.ranks),
            (QuestionService, self.questions),
        ):
            active_patch = patch.object(service, "inst", value, create=True)
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def test_bulletin_list_invalid_missing_and_detail(self):
        method = original(BulletinHandler.get)
        await method(Subject(), None)
        self.assertEqual((await method(Subject(), "bad"))[0], "Eparam")

        self.bulletins.get_bulletin.return_value = (("Enoext", "missing"), None)
        self.assertEqual((await method(Subject(), "2"))[0], "Enoext")

        self.bulletins.get_bulletin.return_value = (None, {"title": "Notice"})
        subject = Subject()
        await method(subject, "2")
        subject.render.assert_awaited_once()

    async def test_log_list_and_detail_validation_errors_and_success(self):
        method = original(LogHandler.get)
        self.assertEqual((await method(Subject({"pageoff": "bad"})))[0], "Eparam")

        self.logs.list_log.return_value = (("Edb", "failed"), None)
        self.assertEqual((await method(Subject(), None))[0], "Edb")

        self.assertEqual((await method(Subject(), "0"))[0], "Eparam")
        self.logs.view_log.return_value = (("Enoext", "missing"), None)
        self.assertEqual((await method(Subject(), "3"))[0], "Enoext")

        self.logs.view_log.return_value = (None, {"log_id": 3})
        subject = Subject()
        await method(subject, "3")
        subject.render.assert_awaited_once()

    async def test_problem_rank_validation_and_service_errors(self):
        method = original(ProRankHandler.get)
        self.assertEqual((await method(Subject({"pageoff": "bad"}), "1"))[0], "Eparam")
        self.assertEqual((await method(Subject({"pagenum": "bad"}), "1"))[0], "Eparam")
        self.assertEqual((await method(Subject(), None))[0], "Eparam")

        self.problems.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual((await method(Subject(), "1"))[0], "Enoext")

        self.problems.get_pro.return_value = (None, SimpleNamespace(name="Problem"))
        self.ranks.get_pro_rank.return_value = (("Edb", "failed"), ([], 0))
        self.assertEqual((await method(Subject(), "1"))[0], "Edb")

        self.ranks.get_pro_rank.return_value = (None, ([], 0))
        subject = Subject({"pageoff": "-2", "pagenum": "0"})
        subject.acct.is_kernel.return_value = True
        await method(subject, "1")
        subject.render.assert_awaited_once()

    async def test_user_rank_validation_error_and_success(self):
        method = original(UserRankHandler.get)
        self.assertEqual((await method(Subject({"pageoff": "bad"})))[0], "Eparam")
        self.assertEqual((await method(Subject({"pagenum": "bad"})))[0], "Eparam")

        self.ranks.get_user_rank.return_value = (("Edb", "failed"), ([], 0))
        self.assertEqual((await method(Subject()))[0], "Edb")

        self.ranks.get_user_rank.return_value = (None, ([], 0))
        subject = Subject({"pageoff": "-2", "pagenum": "0"})
        await method(subject)
        subject.render.assert_awaited_once()

    async def test_question_get_and_post_error_paths(self):
        get_method = original(QuestionHandler.get)
        self.questions.get_queslist.return_value = (("Edb", "failed"), None)
        self.assertEqual((await get_method(Subject()))[0], "Edb")

        self.questions.get_queslist.return_value = (None, [])
        subject = Subject()
        await get_method(subject)
        subject.rs.set.assert_awaited_once()

        post_method = original(QuestionHandler.post)
        subject = Subject({"reqtype": "ask", "qtext": "question"})
        subject.len_check.return_value = ("Eparam", "bad")
        self.assertEqual((await post_method(subject))[0], "Eparam")

        subject = Subject({"reqtype": "ask", "qtext": "question"})
        self.questions.set_ques.return_value = ("Edb", "failed")
        self.assertEqual((await post_method(subject))[0], "Edb")

        subject = Subject({"reqtype": "rm_ques", "index": "bad"})
        self.assertEqual((await post_method(subject))[0], "E")

        subject = Subject({"reqtype": "rm_ques", "index": "2"})
        self.questions.rm_ques.return_value = ("Edb", "failed")
        self.assertEqual((await post_method(subject))[0], "Edb")

        self.questions.rm_ques.return_value = None
        await post_method(subject)
        subject.error.assert_called_with(("S", ""))


class TestManagementPageCoverageCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bulletins = SimpleNamespace(
            list_bulletin=AsyncMock(return_value=(None, [])),
            get_bulletin=AsyncMock(),
            add_bulletin=AsyncMock(),
            edit_bulletin=AsyncMock(),
            del_bulletin=AsyncMock(),
        )
        self.judges = SimpleNamespace(
            get_servers_status=MagicMock(return_value=[]),
            get_server_status=MagicMock(),
            disconnect_server=AsyncMock(),
        )
        for service, value in (
            (BulletinService, self.bulletins),
            (JudgeServerClusterService, self.judges),
        ):
            active_patch = patch.object(service, "inst", value, create=True)
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def test_dashboard_and_judge_get_post_and_disconnect_error(self):
        subject = Subject()
        await original(ManageDashHandler.get)(subject)
        subject.render.assert_awaited_once()

        subject = Subject()
        await original(ManageJudgeHandler.get)(subject)
        subject.render.assert_awaited_once()

        subject = Subject({"reqtype": "connect"})
        with patch.object(judge_dispatcher, "dispatch", AsyncMock(return_value="ok")) as dispatch:
            self.assertEqual(await original(ManageJudgeHandler.post)(subject), "ok")
        dispatch.assert_awaited_once_with(subject, "connect")

        self.judges.get_server_status.return_value = (None, {"name": "judge"})
        self.judges.disconnect_server.return_value = ("Ejudge", "failed")
        import handlers.manage.judge as judge_module

        with patch.object(judge_module.config, "unlock_pwd", judge_module.base64.b64encode(judge_module.packb("pw"))):
            self.assertEqual(
                (await ManageJudgeHandler.disconnect_judge(Subject({"index": "1", "pwd": "pw"})))[0],
                "Ejudge",
            )

    async def test_manage_bulletin_get_pages_and_dispatch(self):
        method = original(ManageBulletinHandler.get)
        for page in (None, "add"):
            subject = Subject()
            await method(subject, page)
            subject.render.assert_awaited_once()

        self.assertEqual((await method(Subject({"bulletin_id": "bad"}), "update"))[0], "Eparam")
        self.bulletins.get_bulletin.return_value = (("Enoext", "missing"), None)
        self.assertEqual((await method(Subject({"bulletin_id": "1"}), "update"))[0], "Enoext")
        self.bulletins.get_bulletin.return_value = (None, {"title": "Title"})
        subject = Subject({"bulletin_id": "1"})
        await method(subject, "update")
        subject.render.assert_awaited_once()

        subject = Subject({"reqtype": "add"})
        with patch.object(bulletin_dispatcher, "dispatch", AsyncMock(return_value="ok")) as dispatch:
            self.assertEqual(await original(ManageBulletinHandler.post)(subject), "ok")
        dispatch.assert_awaited_once_with(subject, "add")

    def bulletin_arguments(self, **overrides):
        values = {
            "bulletin_id": "1",
            "title": "Title",
            "content": "Body",
            "pinned": "false",
            "color": "White",
        }
        values.update(overrides)
        return values

    async def test_add_bulletin_validation_service_error_and_pinned_values(self):
        subject = Subject(self.bulletin_arguments())
        subject.len_check.side_effect = [("Eparam", "title"), None]
        self.assertEqual((await ManageBulletinHandler.add_bulletin(subject))[0], "Eparam")

        subject = Subject(self.bulletin_arguments())
        subject.len_check.side_effect = [None, ("Eparam", "content")]
        self.assertEqual((await ManageBulletinHandler.add_bulletin(subject))[0], "Eparam")

        self.bulletins.add_bulletin.return_value = (("Edb", "failed"), None)
        self.assertEqual(
            (await ManageBulletinHandler.add_bulletin(Subject(self.bulletin_arguments())))[0],
            "Edb",
        )

        self.bulletins.add_bulletin.return_value = (None, 8)
        for pinned in ("false", "true", "unexpected"):
            subject = Subject(self.bulletin_arguments(pinned=pinned))
            await ManageBulletinHandler.add_bulletin(subject)
            subject.rs.publish.assert_awaited_once()

    async def test_update_and_remove_bulletin_boundaries(self):
        self.assertEqual(
            (await ManageBulletinHandler.update_bulletin(Subject(self.bulletin_arguments(bulletin_id="bad"))))[0],
            "Eparam",
        )

        subject = Subject(self.bulletin_arguments())
        subject.len_check.side_effect = [("Eparam", "title"), None]
        self.assertEqual((await ManageBulletinHandler.update_bulletin(subject))[0], "Eparam")

        subject = Subject(self.bulletin_arguments())
        subject.len_check.side_effect = [None, ("Eparam", "content")]
        self.assertEqual((await ManageBulletinHandler.update_bulletin(subject))[0], "Eparam")

        self.bulletins.edit_bulletin.return_value = (("Edb", "failed"), None)
        self.assertEqual(
            (await ManageBulletinHandler.update_bulletin(Subject(self.bulletin_arguments(pinned="true"))))[0],
            "Edb",
        )
        self.bulletins.edit_bulletin.return_value = (None, None)
        subject = Subject(self.bulletin_arguments(pinned="unexpected"))
        await ManageBulletinHandler.update_bulletin(subject)
        subject.error.assert_called_with(("S", ""))

        self.assertEqual(
            (await ManageBulletinHandler.remove_bulletin(Subject({"bulletin_id": "bad"})))[0],
            "Eparam",
        )
        self.bulletins.del_bulletin.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (await ManageBulletinHandler.remove_bulletin(Subject({"bulletin_id": "1"})))[0],
            "Enoext",
        )
        self.bulletins.del_bulletin.return_value = (None, None)
        subject = Subject({"bulletin_id": "1"})
        await ManageBulletinHandler.remove_bulletin(subject)
        subject.error.assert_called_with(("S", ""))


if __name__ == "__main__":
    unittest.main()
