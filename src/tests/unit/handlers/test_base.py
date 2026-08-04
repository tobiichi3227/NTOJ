import asyncio
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

test_config = sys.modules.setdefault("config", SimpleNamespace())
test_config.BASE_URL = "/"
test_config.SITE_TITLE = "NTOJ Test"
test_config.lock_user_list = []
test_config.can_see_code_user = []

from handlers.base import (
    ActionDispatcher,
    RequestHandler,
    UnifiedWebSocketHandler,
    reqenv,
    require_permission,
)
from services.contests import ContestService
from services.user import UserConst, UserService


class TestActionDispatcherAndRequestHandler(unittest.IsolatedAsyncioTestCase):
    async def test_dispatcher_known_and_unknown_actions(self):
        dispatcher = ActionDispatcher()
        handler = SimpleNamespace(error=MagicMock(return_value="unknown"))

        @dispatcher.action("known")
        async def known(target):
            return (target, "done")

        self.assertEqual(await dispatcher.dispatch(handler, "known"), (handler, "done"))
        self.assertEqual(await dispatcher.dispatch(handler, "missing"), "unknown")
        handler.error.assert_called_once_with(("Eunk", "Unknown action: missing"))

    async def test_request_handler_helpers_cover_boundaries_and_logging(self):
        handler = object.__new__(RequestHandler)
        handler.finish = MagicMock()
        handler.error(("S", {"ok": True}))
        self.assertEqual(json.loads(handler.finish.call_args.args[0]), {"status": "S", "data": {"ok": True}})

        self.assertEqual(handler.len_check("", 1, 3, "Name"), ("Eparam", "Name too short"))
        self.assertEqual(handler.len_check("long", 1, 3, "Name"), ("Eparam", "Name too long"))
        self.assertIsNone(handler.len_check("ok", 1, 3, "Name"))

        log_service = SimpleNamespace(add_log=AsyncMock(return_value=(None, 9)))
        with patch("services.log.LogService.inst", log_service, create=True):
            self.assertEqual(await handler.add_log("message", "type", {"x": 1}), (None, 9))
        log_service.add_log.assert_awaited_once_with(
            "message", "type", {"x": 1}, handler=handler
        )


class TestPermissionDecorators(unittest.IsolatedAsyncioTestCase):
    def subject(self, *, path="/be/info", acct_type=UserConst.ACCTTYPE_USER, guest=False):
        acct = MagicMock()
        acct.acct_type = acct_type
        acct.is_guest.return_value = guest
        return SimpleNamespace(
            request=SimpleNamespace(path=path),
            acct=acct,
            contest=None,
            finish=AsyncMock(),
        )

    async def test_reqenv_loads_account_and_contest_or_returns_not_found(self):
        account = MagicMock()
        user_service = SimpleNamespace(
            info_sign=AsyncMock(return_value=(None, 4, "127.0.0.1")),
            info_acct=AsyncMock(return_value=(None, account)),
        )
        contest = MagicMock()
        contest_service = SimpleNamespace(get_contest=AsyncMock(return_value=(None, contest)))

        async def endpoint(subject, value):
            return f"called-{value}"

        wrapped = reqenv(endpoint)
        with (
            patch.object(UserService, "inst", user_service, create=True),
            patch.object(ContestService, "inst", contest_service, create=True),
        ):
            plain = self.subject()
            self.assertEqual(await wrapped(plain, "plain"), "called-plain")
            self.assertIs(plain.acct, account)

            contest_subject = self.subject(path="/be/contests/12/manage/pro")
            self.assertEqual(await wrapped(contest_subject, "contest"), "called-contest")
            self.assertIs(contest_subject.contest, contest)
            contest_service.get_contest.assert_awaited_with(12)

            contest_service.get_contest.return_value = (("Enoext", "missing"), None)
            missing = self.subject(path="/be/contests/99/pro")
            self.assertIsNone(await wrapped(missing, "missing"))
            payload = json.loads(missing.finish.await_args.args[0])
            self.assertEqual(payload["status"], "Enoext")

    async def test_require_permission_for_list_and_single_types(self):
        async def endpoint(subject):
            return "allowed"

        allowed = self.subject(acct_type=UserConst.ACCTTYPE_USER)
        self.assertEqual(
            await require_permission([UserConst.ACCTTYPE_USER, UserConst.ACCTTYPE_KERNEL])(endpoint)(allowed),
            "allowed",
        )
        self.assertEqual(
            await require_permission(UserConst.ACCTTYPE_USER)(endpoint)(allowed),
            "allowed",
        )

        for decorator_arg in (
            [UserConst.ACCTTYPE_KERNEL],
            UserConst.ACCTTYPE_KERNEL,
        ):
            denied = self.subject(acct_type=UserConst.ACCTTYPE_USER)
            self.assertIsNone(await require_permission(decorator_arg)(endpoint)(denied))
            self.assertEqual(json.loads(denied.finish.await_args.args[0])["status"], "Eacces")

            guest = self.subject(acct_type=UserConst.ACCTTYPE_GUEST, guest=True)
            guest.finish = MagicMock()
            self.assertIsNone(await require_permission(decorator_arg)(endpoint)(guest))
            self.assertIn("/sign/", guest.finish.call_args.args[0])


class AsyncMessages:
    def __init__(self, messages):
        self.messages = messages

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise asyncio.CancelledError()
        return self.messages.pop(0)


class TestUnifiedWebSocketHandler(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cls = UnifiedWebSocketHandler
        cls._shared_pubsub = None
        cls._pubsub_task = None
        cls._redis_pool = None
        cls.subscriptions = {}
        cls.active_connections = set()
        cls._channel_callbacks = {}

    def handler(self):
        value = object.__new__(UnifiedWebSocketHandler)
        value.last_pong = 0.0
        value.last_ping = 0.0
        value.ping_callback = None
        value.acct_id = 0
        value.session_id = None
        return value

    async def test_shared_pubsub_creation_resubscription_and_runtime_registration(self):
        cls = UnifiedWebSocketHandler
        callback = AsyncMock()
        cls._channel_callbacks = {"alpha": callback}
        cls._redis_pool = object()
        pubsub = AsyncMock()
        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        listener_task = MagicMock()

        def capture_task(coroutine):
            coroutine.close()
            return listener_task

        with (
            patch("handlers.base.aioredis.Redis", return_value=redis),
            patch("handlers.base.asyncio.create_task", side_effect=capture_task),
        ):
            self.assertIs(await cls.get_shared_pubsub(), pubsub)
            self.assertIs(await cls.get_shared_pubsub(), pubsub)
        pubsub.subscribe.assert_any_await("alpha")
        pubsub.subscribe.assert_any_await(cls._LOGOUT_EVENT_CHANNEL)

        pubsub.reset_mock()
        await cls._resubscribe_all_channels()
        pubsub.subscribe.assert_any_await("alpha")
        pubsub.subscribe.assert_any_await(cls._LOGOUT_EVENT_CHANNEL)

        pubsub.reset_mock()
        cls._channel_callbacks = {}
        await cls._resubscribe_all_channels()
        pubsub.subscribe.assert_awaited_once_with(cls._LOGOUT_EVENT_CHANNEL)

        await cls.register_channel_callback_async("beta", callback)
        self.assertIs(cls._channel_callbacks["beta"], callback)
        pubsub.subscribe.assert_awaited_with("beta")

        cls._shared_pubsub = None
        await cls.register_channel_callback_async("gamma", callback)
        self.assertIs(cls._channel_callbacks["gamma"], callback)

    async def test_listener_routes_logout_raw_formatted_skipped_and_failed_messages(self):
        cls = UnifiedWebSocketHandler
        logout_ok = MagicMock(session_id="logout-session")
        logout_ok.close = MagicMock()
        logout_failed = MagicMock(session_id="logout-session")
        logout_failed.close.side_effect = RuntimeError("close failed")
        logout_failed.cleanup = AsyncMock()
        unrelated = MagicMock(session_id="other")

        raw = MagicMock()
        raw.write_message = AsyncMock()
        formatted = MagicMock()
        formatted.write_message = AsyncMock()
        skipped = MagicMock()
        skipped.write_message = AsyncMock()
        failed = MagicMock()
        failed.write_message = AsyncMock(side_effect=RuntimeError("write failed"))
        failed.cleanup = AsyncMock()
        empty = MagicMock()

        cls.active_connections = {logout_ok, logout_failed, unrelated}
        cls.subscriptions = {
            logout_failed: set(),
            raw: {"raw"},
            formatted: {"formatted"},
            skipped: {"formatted"},
            failed: {"raw"},
            empty: set(),
        }
        callback = SimpleNamespace(
            message=AsyncMock(side_effect=lambda conn, data: None if conn is skipped else f"formatted-{data}")
        )
        cls._channel_callbacks = {"formatted": callback}
        cls._shared_pubsub = SimpleNamespace(
            listen=lambda: AsyncMessages(
                [
                    {"type": "subscribe", "channel": b"ignored", "data": b"ignored"},
                    {"type": "message", "channel": cls._LOGOUT_EVENT_CHANNEL.encode(), "data": b"logout-session"},
                    {"type": "message", "channel": b"raw", "data": b"payload"},
                    {"type": "message", "channel": "formatted", "data": "payload"},
                ]
            )
        )

        with self.assertRaises(asyncio.CancelledError):
            await cls._listen_redis_messages()

        logout_ok.close.assert_called_once_with(code=4000, reason="Logout")
        logout_failed.cleanup.assert_awaited_once()
        raw.write_message.assert_awaited_once()
        formatted.write_message.assert_awaited_once()
        skipped.write_message.assert_not_awaited()
        failed.cleanup.assert_awaited_once()

    async def test_listener_recovers_from_pubsub_exception_with_backoff(self):
        cls = UnifiedWebSocketHandler

        class BrokenPubsub:
            def listen(self):
                raise RuntimeError("redis unavailable")

        cls._shared_pubsub = BrokenPubsub()
        sleep = AsyncMock(side_effect=asyncio.CancelledError())
        with patch("handlers.base.asyncio.sleep", sleep):
            with self.assertRaises(asyncio.CancelledError):
                await cls._listen_redis_messages()
        self.assertIsNone(cls._shared_pubsub)
        sleep.assert_awaited_once_with(1)

    async def test_open_ping_message_routing_cleanup_and_close(self):
        cls = UnifiedWebSocketHandler
        handler = self.handler()
        handler.get_secure_cookie = MagicMock(return_value=b"12")
        handler.get_cookie = MagicMock(return_value="session")
        handler.start_ping = MagicMock()
        with patch.object(cls, "get_shared_pubsub", AsyncMock(return_value=object())):
            await handler.open()
        self.assertEqual(handler.acct_id, 12)
        self.assertEqual(handler.session_id, "session")
        handler.start_ping.assert_called_once()

        callback = SimpleNamespace(
            register=AsyncMock(),
            unregister=AsyncMock(),
            handle_custom_message=AsyncMock(return_value=True),
        )
        cls._channel_callbacks = {"alpha": callback}
        await handler.on_message(json.dumps({"type": "register", "data": "alpha"}))
        self.assertIn("alpha", cls.subscriptions[handler])
        self.assertIn(handler, cls.active_connections)
        callback.register.assert_awaited_once_with(handler)

        await handler.on_message(json.dumps({"type": "pong", "data": ""}))
        self.assertGreater(handler.last_pong, 0)
        await handler.on_message(json.dumps({"type": "custom", "data": "value"}))
        callback.handle_custom_message.assert_awaited_with(handler, "custom", "value")

        callback.handle_custom_message.return_value = False
        await handler.on_message(json.dumps({"type": "unhandled", "data": "value"}))
        await handler.on_message(json.dumps({"type": "unregister", "data": "alpha"}))
        self.assertNotIn("alpha", cls.subscriptions[handler])
        callback.unregister.assert_awaited_once_with(handler)
        await handler.on_message("not-json")

        handler.ping_callback = MagicMock()
        await handler.cleanup()
        handler.ping_callback.stop.assert_called_once()
        self.assertNotIn(handler, cls.subscriptions)
        self.assertNotIn(handler, cls.active_connections)

        cleanup = AsyncMock()
        handler.cleanup = cleanup
        task = MagicMock()
        with patch("handlers.base.asyncio.create_task", return_value=task) as create_task:
            handler.on_close()
        create_task.assert_called_once()
        create_task.call_args.args[0].close()

    async def test_ping_success_timeout_and_write_failure(self):
        handler = self.handler()
        handler.write_message = MagicMock()
        handler.close = MagicMock()
        loop = MagicMock()
        loop.time.return_value = 100.0
        periodic = MagicMock()

        with (
            patch("handlers.base.tornado.ioloop.IOLoop.current", return_value=loop),
            patch("handlers.base.tornado.ioloop.PeriodicCallback", return_value=periodic),
        ):
            handler.start_ping()
            periodic.start.assert_called_once()
            handler.periodic_ping()
        handler.write_message.assert_called_with(json.dumps(UnifiedWebSocketHandler._PING_DATA))
        self.assertEqual(handler.last_ping, 100.0)

        handler.last_pong = 1.0
        with patch("handlers.base.tornado.ioloop.IOLoop.current", return_value=loop):
            handler.periodic_ping()
        handler.close.assert_called_with(code=1000, reason="Ping timeout")

        handler.last_pong = 100.0
        handler.write_message.side_effect = RuntimeError("closed")
        with patch("handlers.base.tornado.ioloop.IOLoop.current", return_value=loop):
            handler.periodic_ping()
        handler.close.assert_called()
        self.assertTrue(handler.check_origin("https://example.test"))

