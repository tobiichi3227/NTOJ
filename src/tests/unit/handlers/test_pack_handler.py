import hashlib
import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.pack import PackHandler
from services.user import UserService


class Subject:
    def __init__(self):
        self.cookie = None
        self.get_secure_cookie = MagicMock(side_effect=lambda _: self.cookie)
        self.close = MagicMock(return_value="closed")
        self.write_message = MagicMock()
        self.rs = AsyncMock()


class TestPackHandler(unittest.IsolatedAsyncioTestCase):
    async def test_open_authentication_branches_and_initialization(self):
        subject = Subject()
        self.assertEqual(await PackHandler.open(subject), "closed")

        subject.cookie = b"bad"
        self.assertEqual(await PackHandler.open(subject), "closed")

        user_service = SimpleNamespace(info_acct=AsyncMock())
        subject.cookie = b"7"
        user_service.info_acct.return_value = (("Enoext", "missing"), None)
        with patch.object(UserService, "inst", user_service, create=True):
            self.assertEqual(await PackHandler.open(subject), "closed")

            account = MagicMock()
            account.is_kernel.return_value = False
            user_service.info_acct.return_value = (None, account)
            self.assertEqual(await PackHandler.open(subject), "closed")

            account.is_kernel.return_value = True
            self.assertIsNone(await PackHandler.open(subject))
        self.assertEqual(subject.state, PackHandler.STATE_HDR)
        self.assertEqual(subject.remain, 0)
        self.assertIsNone(subject.output)

    async def test_header_validation_token_and_io_branches(self):
        token = str(uuid.uuid4())
        subject = Subject()
        subject.state = PackHandler.STATE_HDR
        for payload in ("not-json", json.dumps({}), json.dumps({"pack_token": "bad"})):
            await PackHandler.on_message(subject, payload)
            subject.write_message.assert_called_with("Eparam")
            subject.close.assert_called()
            subject.reset = None

        subject = Subject()
        subject.state = PackHandler.STATE_HDR
        subject.rs.exists.return_value = 0
        await PackHandler.on_message(
            subject,
            json.dumps({"pack_token": token, "pack_size": 3, "md5": "abc"}),
        )
        subject.write_message.assert_called_with("Etoken")

        subject = Subject()
        subject.state = PackHandler.STATE_HDR
        subject.rs.exists.return_value = 1
        with patch("builtins.open", side_effect=OSError("io")):
            await PackHandler.on_message(
                subject,
                json.dumps({"pack_token": token, "pack_size": 3, "md5": "abc"}),
            )
        subject.write_message.assert_called_with("Eio")

        output = MagicMock()
        subject = Subject()
        subject.state = PackHandler.STATE_HDR
        subject.rs.exists.return_value = 1
        with patch("builtins.open", return_value=output):
            await PackHandler.on_message(
                subject,
                json.dumps({"pack_token": token, "pack_size": 3, "md5": "abc"}),
            )
        self.assertEqual(subject.state, PackHandler.STATE_DTAT)
        self.assertEqual(subject.remain, 3)
        self.assertIs(subject.output, output)
        subject.write_message.assert_called_with("S")

    async def test_data_chunk_size_hash_and_success_branches(self):
        token = str(uuid.uuid4())
        subject = Subject()
        subject.state = PackHandler.STATE_DTAT
        subject.output = MagicMock()
        subject.remain = 1
        subject.pack_token = token
        subject.md5 = hashlib.md5()
        subject.received_md5 = ""
        with patch("handlers.pack.os.remove") as remove:
            await PackHandler.on_message(subject, b"too large")
        remove.assert_called_once()
        subject.write_message.assert_called_with("Echunk")
        self.assertIsNone(subject.output)

        subject = Subject()
        subject.state = PackHandler.STATE_DTAT
        subject.output = MagicMock()
        subject.remain = 1
        subject.pack_token = token
        subject.md5 = hashlib.md5()
        subject.received_md5 = "wrong"
        with patch("handlers.pack.os.remove", side_effect=OSError("remove")):
            await PackHandler.on_message(subject, b"x")
        subject.write_message.assert_called_with("Ehash")

        data = b"hello"
        subject = Subject()
        subject.state = PackHandler.STATE_DTAT
        output = MagicMock()
        subject.output = output
        subject.remain = len(data) + 1
        subject.pack_token = token
        subject.md5 = hashlib.md5()
        subject.received_md5 = hashlib.md5(data + b"!").hexdigest()
        await PackHandler.on_message(subject, data)
        self.assertEqual(subject.remain, 1)
        output.write.assert_called_with(data)
        subject.write_message.assert_called_with("S")

        await PackHandler.on_message(subject, b"!")
        self.assertEqual(subject.remain, 0)
        output.close.assert_called_once()
        self.assertIsNone(subject.output)
        subject.write_message.assert_called_with("S")

    def test_close_cleans_open_output_and_partial_file(self):
        token = str(uuid.uuid4())
        subject = Subject()
        subject.output = MagicMock()
        subject.remain = 2
        subject.pack_token = token
        with patch("handlers.pack.os.remove") as remove:
            PackHandler.on_close(subject)
        subject.output.close.assert_called_once()
        remove.assert_called_once_with(f"tmp/{token}")

        subject = Subject()
        subject.output = None
        subject.remain = 1
        subject.pack_token = token
        with patch("handlers.pack.os.remove", side_effect=OSError("remove")):
            PackHandler.on_close(subject)


if __name__ == "__main__":
    unittest.main()
