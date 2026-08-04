import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from services.pack import PackService


class TestPackService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.redis = AsyncMock()
        self.service = PackService(MagicMock(), self.redis)
        self.token = str(uuid.uuid4())

    async def test_generate_token_and_direct_copy_branches(self):
        with patch("services.pack.uuid.uuid4", return_value=uuid.UUID(self.token)):
            self.assertEqual(await self.service.gen_token(), (None, self.token))
        self.redis.set.assert_awaited_with(f"PACK_TOKEN@{self.token}", 0)

        self.redis.exists.return_value = 0
        self.assertEqual(
            await self.service.direct_copy(self.token, "/dst"),
            (("Enoext", "Pack token not found"), None),
        )

        self.redis.exists.return_value = 1
        source = MagicMock()
        source.read.side_effect = [b"first", b"second", b""]
        destination = MagicMock()
        source_context = MagicMock()
        source_context.__enter__.return_value = source
        destination_context = MagicMock()
        destination_context.__enter__.return_value = destination
        with (
            patch("builtins.open", side_effect=[source_context, destination_context]),
            patch("services.pack.os.remove") as remove,
        ):
            self.assertEqual(
                await self.service.direct_copy(self.token, "/dst"), (None, None)
            )
        self.assertEqual(
            [call.args[0] for call in destination.write.call_args_list],
            [b"first", b"second"],
        )
        remove.assert_called_once_with(f"tmp/{self.token}")
        self.redis.delete.assert_awaited_with(f"PACK_TOKEN@{self.token}")

        with patch("builtins.open", side_effect=OSError("io")):
            self.assertEqual(
                (await self.service.direct_copy(self.token, "/dst"))[0][0], "Eunk"
            )

    async def test_clear_missing_success_and_io_error(self):
        self.redis.exists.return_value = 0
        self.assertEqual((await self.service.clear(self.token))[0][0], "Enoext")

        self.redis.exists.return_value = 1
        with patch("services.pack.os.remove") as remove:
            self.assertEqual(await self.service.clear(self.token), (None, None))
        remove.assert_called_once_with(f"tmp/{self.token}")

        with patch("services.pack.os.remove", side_effect=OSError("io")):
            self.assertEqual((await self.service.clear(self.token))[0][0], "Eunk")

    async def test_process_helper_returns_exit_status(self):
        process = SimpleProcess(7)
        with patch(
            "services.pack.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ) as create:
            self.assertEqual(await self.service._run_and_wait_process("tool", "arg"), 7)
        create.assert_awaited_once_with("tool", "arg")

    async def test_unpack_token_clean_and_archive_failures(self):
        self.redis.delete.return_value = 0
        self.assertEqual(
            await self.service.unpack(self.token, "/dst"),
            (("Enoext", "Pack token not found"), None),
        )

        self.redis.delete.return_value = 1
        self.service._run_and_wait_process = AsyncMock(side_effect=[0, 0])
        temporary = temporary_directory("/tmp/work")
        with (
            patch("services.pack.tempfile.TemporaryDirectory", return_value=temporary),
            patch("services.pack.os.path.exists", return_value=False),
            patch("services.pack.os.makedirs") as makedirs,
            patch("services.pack.os.remove"),
            patch("services.pack.os.listdir", return_value=[]),
            patch("services.pack.shutil.copytree") as copytree,
        ):
            self.assertEqual(
                await self.service.unpack(self.token, "/dst", clean=True), (None, None)
            )
        makedirs.assert_called_once_with("/dst", 0o700)
        copytree.assert_called_once_with("/tmp/work", "/dst", dirs_exist_ok=True)

        self.service._run_and_wait_process = AsyncMock(side_effect=[0, 0, 0])
        with (
            patch("services.pack.tempfile.TemporaryDirectory", return_value=temporary),
            patch("services.pack.os.path.exists", return_value=True),
            patch("services.pack.os.makedirs") as makedirs,
            patch("services.pack.os.remove"),
            patch("services.pack.os.listdir", return_value=[]),
            patch("services.pack.shutil.copytree"),
        ):
            self.assertEqual(
                await self.service.unpack(self.token, "/dst", clean=True), (None, None)
            )
        self.service._run_and_wait_process.assert_any_await(
            "/bin/rm", "-Rf", "/dst"
        )
        makedirs.assert_called_once_with("/dst", 0o700)

        self.service._run_and_wait_process = AsyncMock(return_value=0)
        with (
            patch("services.pack.tempfile.TemporaryDirectory", return_value=temporary),
            patch("services.pack.os.remove", side_effect=OSError("remove")),
        ):
            self.assertEqual(
                (await self.service.unpack(self.token, "/dst"))[0][0], "Eunk"
            )

        self.service._run_and_wait_process = AsyncMock(return_value=2)
        with (
            patch("services.pack.tempfile.TemporaryDirectory", return_value=temporary),
            patch("services.pack.os.remove"),
        ):
            result = await self.service.unpack(self.token, "/dst")
        self.assertEqual(result[0][1], "Unknown error (tar)")

    async def test_unpack_rejects_links_nonfiles_and_newline_failure(self):
        self.redis.delete.return_value = 1
        temporary = temporary_directory("/tmp/work")

        async def run_with(*, is_link=False, is_file=True, process_codes=(0, 0)):
            self.service._run_and_wait_process = AsyncMock(side_effect=process_codes)
            with (
                patch(
                    "services.pack.tempfile.TemporaryDirectory", return_value=temporary
                ),
                patch("services.pack.os.remove"),
                patch("services.pack.os.listdir", return_value=["entry"]),
                patch("services.pack.os.path.isdir", return_value=False),
                patch("services.pack.os.path.islink", return_value=is_link),
                patch("services.pack.os.path.isfile", return_value=is_file),
                patch("services.pack.shutil.copytree"),
            ):
                return await self.service.unpack(self.token, "/dst")

        self.assertEqual((await run_with(is_link=True))[0][0], "Eparam")
        self.assertEqual((await run_with(is_file=False))[0][0], "Eparam")
        result = await run_with(process_codes=(0, 3))
        self.assertEqual(result[0][1], "Unknown error (newline)")

    async def test_unpack_recurses_into_directories(self):
        self.redis.delete.return_value = 1
        self.service._run_and_wait_process = AsyncMock(side_effect=[0, 0])
        temporary = temporary_directory("/tmp/work")

        def listdir(path):
            return ["nested"] if path == "/tmp/work" else ["file.txt"]

        def isdir(path):
            return path == "/tmp/work/nested"

        with (
            patch("services.pack.tempfile.TemporaryDirectory", return_value=temporary),
            patch("services.pack.os.remove"),
            patch("services.pack.os.listdir", side_effect=listdir),
            patch("services.pack.os.path.isdir", side_effect=isdir),
            patch("services.pack.os.path.islink", return_value=False),
            patch("services.pack.os.path.isfile", return_value=True),
            patch("services.pack.shutil.copytree") as copytree,
        ):
            self.assertEqual(await self.service.unpack(self.token, "/dst"), (None, None))
        copytree.assert_called_once()


class SimpleProcess:
    def __init__(self, returncode):
        self.returncode = returncode

    async def wait(self):
        return self.returncode


def temporary_directory(path):
    context = MagicMock()
    context.__enter__.return_value = path
    return context


if __name__ == "__main__":
    unittest.main()
