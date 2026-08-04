import pickle
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg

from services.chal import Compiler
from services.user import Account, UserConst, UserService


def database(connection=None, enter_error=None):
    if connection is None:
        connection = MagicMock()
        connection.fetch = AsyncMock()
        connection.execute = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=None)
    transaction.__aexit__ = AsyncMock(return_value=None)
    connection.transaction = MagicMock(return_value=transaction)
    acquire = MagicMock()
    if enter_error is None:
        acquire.__aenter__ = AsyncMock(return_value=connection)
    else:
        acquire.__aenter__ = AsyncMock(side_effect=enter_error)
    acquire.__aexit__ = AsyncMock(return_value=None)
    db = MagicMock()
    db.acquire.return_value = acquire
    return db, connection


def account(**overrides):
    values = dict(
        acct_id=1,
        acct_type=UserConst.ACCTTYPE_USER,
        mail="user@example.com",
        name="user",
        photo="",
        cover="",
        motto="hello",
        lastip="",
        last_compiler=Compiler.GPP,
        proclass_collection=[],
        specific_ip="",
    )
    values.update(overrides)
    return Account(**values)


def account_row():
    return {
        "acct_type": UserConst.ACCTTYPE_USER,
        "mail": "user@example.com",
        "name": "user",
        "photo": "",
        "cover": "",
        "motto": "hello",
        "last_compiler": Compiler.GPP,
        "lastip": "",
        "proclass_collection": [],
        "specific_ip": None,
    }


class Request:
    def __init__(self, request):
        self.request = request

    def get_secure_cookie(self, _):
        return "1"

    def get_cookie(self, _):
        return "session"


class BrokenRemoteIp:
    @property
    def remote_ip(self):
        raise RuntimeError("disconnected")


class TestUserServiceFailureBranches(unittest.IsolatedAsyncioTestCase):
    def service(self, *, db=None, rs=None):
        if db is None:
            db, _ = database()
        return UserService(db, rs or AsyncMock())

    async def test_sign_in_database_error(self):
        db, _ = database(enter_error=RuntimeError("db"))
        self.assertEqual(
            await self.service(db=db).sign_in("user@example.com", "pw"),
            (("Eunk", "Unknown error"), None),
        )

    async def test_sign_up_generic_empty_and_integrity_rollback_errors(self):
        with (
            patch("services.user.bcrypt.gensalt", return_value=b"salt"),
            patch("services.user.bcrypt.hashpw", return_value=b"hash"),
        ):
            db, _ = database(enter_error=RuntimeError("db"))
            self.assertEqual(
                await self.service(db=db).sign_up("u@e.co", "pw", "user"),
                (("Eunk", "Unknown error"), None),
            )

            db, connection = database()
            connection.fetch.return_value = []
            self.assertEqual(
                await self.service(db=db).sign_up("u@e.co", "pw", "user"),
                (("Eexist", "Account already exists"), None),
            )

            first = MagicMock()
            first.__aenter__ = AsyncMock(
                side_effect=asyncpg.UniqueViolationError("duplicate")
            )
            first.__aexit__ = AsyncMock(return_value=None)
            second = MagicMock()
            second.__aenter__ = AsyncMock(side_effect=RuntimeError("rollback"))
            second.__aexit__ = AsyncMock(return_value=None)
            db = MagicMock()
            db.acquire.side_effect = [first, second]
            self.assertEqual(
                await self.service(db=db).sign_up("u@e.co", "pw", "user"),
                (("Eunk", "Unknown error"), None),
            )

    async def test_info_sign_handles_missing_remote_ip_and_corrupt_cached_account(self):
        rs = AsyncMock()
        rs.hget.return_value = b"session"
        rs.get.return_value = pickle.dumps(account(lastip=""))
        service = self.service(rs=rs)
        with patch("services.user.unpackb", return_value={"time": time.time()}):
            self.assertEqual(
                await service.info_sign(Request(BrokenRemoteIp())),
                (None, 1, ""),
            )

        rs.get.return_value = b"corrupt"
        with (
            patch("services.user.unpackb", return_value={"time": time.time()}),
            patch("services.user.pickle.loads", side_effect=ValueError("cache")),
        ):
            self.assertEqual(
                await service.info_sign(Request(SimpleNamespace(remote_ip="127.0.0.1"))),
                (None, 1, "127.0.0.1"),
            )

    async def test_info_account_recovers_bad_cache_and_handles_database_and_pickle_errors(self):
        db, connection = database()
        rs = AsyncMock()
        rs.get.side_effect = [b"bad", None]
        connection.fetch.return_value = [account_row()]
        service = self.service(db=db, rs=rs)
        with patch("services.user.pickle.loads", side_effect=ValueError("cache")):
            err, value = await service.info_acct(1)
        self.assertIsNone(err)
        self.assertEqual(value.name, "user")
        rs.delete.assert_awaited_with("account@1")

        db, _ = database(enter_error=RuntimeError("db"))
        rs = AsyncMock()
        rs.get.return_value = None
        self.assertEqual(
            await self.service(db=db, rs=rs).info_acct(1),
            (("Eunk", "Unknown error"), None),
        )

        db, connection = database()
        connection.fetch.return_value = [account_row()]
        rs = AsyncMock()
        rs.get.return_value = None
        with patch(
            "services.user.pickle.dumps", side_effect=pickle.PicklingError("pickle")
        ):
            err, value = await self.service(db=db, rs=rs).info_acct(1)
        self.assertIsNone(err)
        self.assertEqual(value.mail, "")
        rs.setnx.assert_not_awaited()

    async def test_update_account_remaining_validation_not_found_and_database_error(self):
        service = self.service()
        self.assertEqual(
            (await service.update_acct(account(name="x" * (UserConst.NAME_MAX + 1))))[0][0],
            "Enamemax",
        )

        db, connection = database()
        connection.fetch.return_value = []
        self.assertEqual(
            await self.service(db=db).update_acct(account()),
            (("Enoext", "Account not found"), None),
        )

        db, _ = database(enter_error=RuntimeError("db"))
        self.assertEqual(
            await self.service(db=db).update_acct(account()),
            (("Eunk", "Unknown error"), None),
        )

    async def test_update_password_bounds_missing_same_and_database_error(self):
        service = self.service()
        self.assertEqual((await service.update_pw(1, "old", "", False))[0][0], "Epwmin")
        self.assertEqual(
            (
                await service.update_pw(
                    1, "old", "x" * (UserConst.PW_MAX + 1), False
                )
            )[0][0],
            "Epwmax",
        )

        db, connection = database()
        connection.fetch.return_value = []
        self.assertEqual(
            await self.service(db=db).update_pw(1, "old", "new", False),
            (("Enoext", "Account not found"), None),
        )

        db, connection = database()
        connection.fetch.return_value = [{"password": "encoded"}]
        with (
            patch("services.user.base64.b64decode", return_value=b"current"),
            patch("services.user.bcrypt.hashpw", return_value=b"current"),
        ):
            self.assertEqual(
                await self.service(db=db).update_pw(1, "old", "new", True),
                (("Epwsame", "New password cannot be the same as current password"), None),
            )

        db, _ = database(enter_error=RuntimeError("db"))
        self.assertEqual(
            await self.service(db=db).update_pw(1, "old", "new", True),
            (("Eunk", "Unknown error"), None),
        )

    async def test_list_account_recovers_cache_and_handles_db_and_pickle_failures(self):
        db, connection = database()
        connection.fetch.return_value = []
        rs = AsyncMock()
        rs.hget.side_effect = [b"bad", None]
        with patch("services.user.pickle.loads", side_effect=ValueError("cache")):
            err, values = await self.service(db=db, rs=rs).list_acct()
        self.assertIsNone(err)
        self.assertEqual(values, [])
        rs.hdel.assert_awaited_once()

        db, _ = database(enter_error=RuntimeError("db"))
        rs = AsyncMock()
        rs.hget.return_value = None
        self.assertEqual(
            await self.service(db=db, rs=rs).list_acct(),
            (("Eunk", "Unknown error"), None),
        )

        db, connection = database()
        connection.fetch.return_value = []
        rs = AsyncMock()
        rs.hget.return_value = None
        with patch(
            "services.user.pickle.dumps", side_effect=pickle.PicklingError("pickle")
        ):
            self.assertEqual(await self.service(db=db, rs=rs).list_acct(), (None, []))


if __name__ == "__main__":
    unittest.main()
