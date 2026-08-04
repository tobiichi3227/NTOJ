import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from msgpack import packb

from handlers.manage.pro.prolist import (
    ManageProListHandler,
    prolist_dispatcher,
)
from handlers.manage.proclass import (
    ManageProClassHandler,
    proclass_dispatcher,
)
from services.chal import ChalService, Compiler
from services.judge import JudgeServerClusterService
from services.pro import (
    ProClassConst,
    ProClassService,
    ProConst,
    ProService,
)
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Subject,
    original,
)


def db_subject(arguments, rows):
    subject = Subject(arguments=arguments)
    connection = AsyncMock()
    connection.fetch.return_value = rows
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=connection)
    manager.__aexit__ = AsyncMock(return_value=None)
    subject.db = MagicMock()
    subject.db.acquire.return_value = manager
    return subject


class TestAdminProblemLists(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.problem = SimpleNamespace(
            config=SimpleNamespace(name="config"),
            problem_type="batch",
        )
        self.problems = SimpleNamespace(
            list_pro=AsyncMock(return_value=(None, [])),
            get_pro=AsyncMock(return_value=(None, self.problem)),
        )
        self.challenges = SimpleNamespace(
            reset_chal=AsyncMock(return_value=(None, None)),
            emit_chal=AsyncMock(return_value=(None, None)),
        )
        self.judges = SimpleNamespace(
            is_server_online=MagicMock(return_value=True)
        )
        self.classes = SimpleNamespace(
            get_proclass_list=AsyncMock(return_value=(None, [])),
            get_proclass=AsyncMock(),
            add_proclass=AsyncMock(return_value=(None, 8)),
            update_proclass=AsyncMock(return_value=None),
            remove_proclass=AsyncMock(),
        )
        for service, value in (
            (ProService, self.problems),
            (ChalService, self.challenges),
            (JudgeServerClusterService, self.judges),
            (ProClassService, self.classes),
        ):
            active = patch.object(service, "inst", value, create=True)
            active.start()
            self.addCleanup(active.stop)

    async def test_problem_list_get_and_dispatch(self):
        method = original(ManageProListHandler.get)
        self.problems.list_pro.return_value = (("Edb", "failed"), None)
        self.assertEqual((await method(Subject()))[0], "Edb")

        self.problems.list_pro.return_value = (
            None, [SimpleNamespace(pro_id=1)]
        )
        for pageoff in ("-1", "0"):
            subject = Subject(arguments={"pageoff": pageoff})
            await method(subject)
            subject.render.assert_awaited_once()

        subject = Subject(arguments={"reqtype": "rechal"})
        with patch.object(
            prolist_dispatcher, "dispatch", AsyncMock(return_value="ok")
        ) as dispatch:
            self.assertEqual(
                await original(ManageProListHandler.post)(subject), "ok"
            )
        dispatch.assert_awaited_once_with(subject, "rechal")

    async def test_rejudge_no_judge_and_successful_inner_loop(self):
        method = ManageProListHandler.rechal_pro
        self.judges.is_server_online.return_value = False
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"pro_id": "1"})
                )
            )[0],
            "Ejudge",
        )

        self.judges.is_server_online.return_value = True
        subject = db_subject(
            {"pro_id": "1"},
            [(10, Compiler.GPP), (11, Compiler.CLANGPP)],
        )
        self.assertIsNone(await method(subject))
        self.assertEqual(self.challenges.reset_chal.await_count, 2)
        self.assertEqual(self.challenges.emit_chal.await_count, 2)

    async def test_rejudge_all_validation_errors_and_success(self):
        method = ManageProListHandler.rechal_all_pro
        import handlers.manage.pro.prolist as module

        encoded = base64.b64encode(packb("pw"))
        with patch.object(module.config, "unlock_pwd", encoded):
            self.assertEqual(
                (
                    await method(
                        Subject(
                            arguments={"pwd": "pw", "pro_id": "bad"}
                        )
                    )
                )[0],
                "Eparam",
            )

            self.judges.is_server_online.return_value = False
            self.assertEqual(
                (
                    await method(
                        Subject(arguments={"pwd": "pw", "pro_id": "1"})
                    )
                )[0],
                "Ejudge",
            )

            self.judges.is_server_online.return_value = True
            self.problems.get_pro.return_value = (
                ("Enoext", "missing"), None
            )
            self.assertEqual(
                (
                    await method(
                        Subject(arguments={"pwd": "pw", "pro_id": "1"})
                    )
                )[0],
                "Enoext",
            )

            self.problems.get_pro.return_value = (None, self.problem)
            self.challenges.reset_chal.reset_mock()
            self.challenges.emit_chal.reset_mock()
            subject = db_subject(
                {"pwd": "pw", "pro_id": "1"},
                [(10, Compiler.GPP)],
            )
            self.assertIsNone(await method(subject))
            self.challenges.reset_chal.assert_awaited_once()
            self.challenges.emit_chal.assert_awaited_once()

    async def test_proclass_get_pages_and_dispatch(self):
        method = original(ManageProClassHandler.get)
        self.classes.get_proclass_list.return_value = (
            None,
            [
                {
                    "type": ProClassConst.OFFICIAL_PUBLIC,
                    "name": "official",
                },
                {"type": 999, "name": "private"},
            ],
        )
        for pageoff in ("-1", "0"):
            subject = Subject(arguments={"pageoff": pageoff})
            await method(subject, None)
            subject.render.assert_awaited_once()

        subject = Subject()
        await method(subject, "add")
        subject.render.assert_awaited_once()

        self.assertEqual(
            (
                await method(
                    Subject(arguments={"proclassid": "bad"}), "update"
                )
            )[0],
            "Eparam",
        )
        self.classes.get_proclass.return_value = (
            None, {"type": 999, "name": "private"}
        )
        self.assertEqual(
            (
                await method(
                    Subject(arguments={"proclassid": "1"}), "update"
                )
            )[0],
            "Eacces",
        )
        self.classes.get_proclass.return_value = (
            None,
            {
                "type": ProClassConst.OFFICIAL_PUBLIC,
                "name": "official",
            },
        )
        subject = Subject(arguments={"proclassid": "1"})
        await method(subject, "update")
        subject.render.assert_awaited_once()

        subject = Subject(arguments={"reqtype": "add"})
        with patch.object(
            proclass_dispatcher, "dispatch", AsyncMock(return_value="ok")
        ) as dispatch:
            self.assertEqual(
                await original(ManageProClassHandler.post)(subject), "ok"
            )
        dispatch.assert_awaited_once_with(subject, "add")

    def class_args(self, **overrides):
        values = {
            "name": "class",
            "desc": "description",
            "type": str(ProClassConst.OFFICIAL_PUBLIC),
            "list": "1-2",
            "proclass_id": "1",
        }
        values.update(overrides)
        return values

    async def test_add_proclass_empty_list_and_service_error(self):
        method = ManageProClassHandler.add_proclass
        self.assertEqual(
            (
                await method(
                    Subject(arguments=self.class_args(list="bad"))
                )
            )[0],
            "Eparam",
        )

        self.classes.add_proclass.return_value = (
            ("Edb", "failed"), None
        )
        self.assertEqual(
            (
                await method(
                    Subject(arguments=self.class_args())
                )
            )[0],
            "Edb",
        )

    async def test_update_proclass_validation_and_service_errors(self):
        method = ManageProClassHandler.update_proclass
        subject = Subject(arguments=self.class_args())
        subject.len_check.return_value = ("Eparam", "name")
        self.assertEqual((await method(subject))[0], "Eparam")

        subject = Subject(arguments=self.class_args())
        subject.len_check.side_effect = [None, ("Eparam", "desc")]
        self.assertEqual((await method(subject))[0], "Eparam")

        for overrides in (
            {"type": "999"},
            {"list": "bad"},
            {"proclass_id": "bad"},
        ):
            self.assertEqual(
                (
                    await method(
                        Subject(
                            arguments=self.class_args(**overrides)
                        )
                    )
                )[0],
                "Eparam",
            )

        self.classes.get_proclass.return_value = (
            ("Enoext", "missing"), None
        )
        self.assertEqual(
            (
                await method(
                    Subject(arguments=self.class_args())
                )
            )[0],
            "Enoext",
        )

        self.classes.get_proclass.return_value = (
            None,
            {
                "type": ProClassConst.OFFICIAL_PUBLIC,
                "name": "official",
            },
        )
        self.classes.update_proclass.return_value = ("Edb", "failed")
        self.assertEqual(
            (
                await method(
                    Subject(arguments=self.class_args())
                )
            )[0],
            "Edb",
        )

    async def test_remove_invalid_identifier(self):
        self.assertEqual(
            (
                await ManageProClassHandler.remove_proclass(
                    Subject(arguments={"proclass_id": "bad"})
                )
            )[0],
            "Eparam",
        )


if __name__ == "__main__":
    unittest.main()
