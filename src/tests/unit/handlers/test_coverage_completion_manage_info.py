import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.manage.info import ManageInfoHandler, info_dispatcher
from services.user import UserService
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Subject,
    original,
)


def failing_db_subject():
    subject = Subject()
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(side_effect=RuntimeError("database"))
    manager.__aexit__ = AsyncMock(return_value=None)
    subject.db = MagicMock()
    subject.db.acquire.return_value = manager
    subject.rs.info.side_effect = RuntimeError("redis")
    return subject


class TestManageInfoCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.users = SimpleNamespace(
            info_acct=AsyncMock(return_value=(("Enoext", "missing"), None))
        )
        active = patch.object(UserService, "inst", self.users, create=True)
        active.start()
        self.addCleanup(active.stop)

    async def collect_with_environment(self, exists_side_effect):
        subject = failing_db_subject()
        import handlers.manage.info as module

        with (
            patch("builtins.open", side_effect=OSError("file")),
            patch.object(
                module.config, "can_see_code_user", [7], create=True
            ),
            patch.object(
                module.os.path,
                "exists",
                side_effect=exists_side_effect,
            ),
            patch.object(
                module.psutil,
                "boot_time",
                side_effect=RuntimeError("uptime"),
            ),
            patch.object(
                module.psutil,
                "disk_usage",
                side_effect=RuntimeError("disk"),
            ),
            patch.object(
                module.psutil,
                "cpu_percent",
                side_effect=RuntimeError("resources"),
            ),
        ):
            return await ManageInfoHandler._get_system_info(subject)

    async def test_all_error_fallbacks_and_unknown_environment(self):
        info = await self.collect_with_environment([False, False, False])
        self.assertIn("error", info["git"])
        self.assertIn("error", info["db"])
        self.assertEqual(info["config"]["can_see_code_user"], [])
        self.assertIn("error", info["redis"])
        self.assertEqual(info["python"]["dependencies"], "N/A")
        self.assertEqual(info["os"]["uptime"], "N/A")
        self.assertEqual(info["env"], "unknown")
        self.assertEqual(info["disk"], "N/A")
        self.assertIn("error", info["resources"])

    async def test_release_and_installation_environment_branches(self):
        info = await self.collect_with_environment([False, True])
        self.assertEqual(info["env"], "docker-release")

        info = await self.collect_with_environment([False, False, True])
        self.assertEqual(info["env"], "installation-script")

    async def test_get_post_dispatch_and_vacuum_failure(self):
        subject = failing_db_subject()
        with patch.object(
            subject,
            "_get_system_info",
            AsyncMock(return_value={"ok": True}),
            create=True,
        ):
            await original(ManageInfoHandler.get)(subject)
        subject.render.assert_awaited_once()

        subject = Subject(arguments={"reqtype": "vacuum"})
        with patch.object(
            info_dispatcher, "dispatch", AsyncMock(return_value="ok")
        ) as dispatch:
            self.assertEqual(
                await original(ManageInfoHandler.post)(subject), "ok"
            )
        dispatch.assert_awaited_once_with(subject, "vacuum")

        subject = failing_db_subject()
        self.assertEqual(
            await ManageInfoHandler.vacuum_database(subject),
            ("E", "VACUUM Failed"),
        )


if __name__ == "__main__":
    unittest.main()
