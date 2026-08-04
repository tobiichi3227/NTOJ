import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.base import RequestHandler, UnifiedWebSocketHandler, WebSocketHandler


class AsyncMessages:
    def __init__(self, messages):
        self.messages = list(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise asyncio.CancelledError()
        return self.messages.pop(0)


class BadSession:
    @property
    def session_id(self):
        raise RuntimeError("session property")

    def __hash__(self):
        return id(self)


class TestRequestHandlerRenderCompletion(
    unittest.IsolatedAsyncioTestCase
):
    async def test_render_without_title(self):
        handler = object.__new__(RequestHandler)
        handler.acct = SimpleNamespace(acct_id=1)
        handler.base_url = "/"
        handler.write = MagicMock()
        handler.finish = MagicMock()
        template = MagicMock()
        template.generate.return_value = b"page"
        handler.tpldr = MagicMock()
        handler.tpldr.load.return_value = template

        await handler.render("page", None, now="value")
        handler.write.assert_not_called()
        handler.finish.assert_called_once_with(b"page")

        handler.write.reset_mock()
        handler.finish.reset_mock()
        await handler.render("page", "Title")
        handler.write.assert_called_once()
        handler.finish.assert_called_once_with(b"page")

    def test_websocket_constructors(self):
        with (
            patch("tornado.websocket.WebSocketHandler.__init__", return_value=None),
            patch("handlers.base.aioredis.Redis", return_value=MagicMock()),
        ):
            plain = WebSocketHandler(db="db", rs="redis")
            self.assertEqual((plain.db, plain.rs), ("db", "redis"))
            UnifiedWebSocketHandler._redis_pool = None
            first = UnifiedWebSocketHandler(db="db", pool="pool")
            second = UnifiedWebSocketHandler(db="db2", pool="other")
        self.assertEqual(first.db, "db")
        self.assertEqual(second.db, "db2")
        self.assertEqual(UnifiedWebSocketHandler._redis_pool, "pool")


class TestRegisterChannelCallbackSyncCompletion(unittest.TestCase):
    def setUp(self):
        UnifiedWebSocketHandler._channel_callbacks = {}
        UnifiedWebSocketHandler._shared_pubsub = None

    def test_registration_without_event_loop(self):
        with patch(
            "handlers.base.asyncio.get_event_loop",
            side_effect=RuntimeError("no loop"),
        ):
            UnifiedWebSocketHandler.register_channel_callback(
                "offline", object()
            )
        self.assertIn(
            "offline",
            UnifiedWebSocketHandler._channel_callbacks,
        )

    def test_registration_with_stopped_event_loop(self):
        loop = asyncio.new_event_loop()
        try:
            with patch(
                "handlers.base.asyncio.get_event_loop",
                return_value=loop,
            ):
                UnifiedWebSocketHandler.register_channel_callback(
                    "stopped", object()
                )
        finally:
            loop.close()
        self.assertIn(
            "stopped",
            UnifiedWebSocketHandler._channel_callbacks,
        )


class TestUnifiedWebSocketCompletion(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self):
        cls = UnifiedWebSocketHandler
        cls._shared_pubsub = None
        cls._pubsub_task = None
        cls._redis_pool = None
        cls.subscriptions = {}
        cls.active_connections = set()
        cls._channel_callbacks = {}

    def handler(self):
        handler = object.__new__(UnifiedWebSocketHandler)
        handler.last_pong = 0.0
        handler.last_ping = 0.0
        handler.ping_callback = None
        handler.acct_id = 0
        handler.session_id = None
        return handler

    async def test_shared_pubsub_without_custom_channels(self):
        cls = UnifiedWebSocketHandler
        pubsub = AsyncMock()
        redis = MagicMock()
        redis.pubsub.return_value = pubsub

        def capture(coroutine):
            coroutine.close()
            return MagicMock()

        with (
            patch(
                "handlers.base.aioredis.Redis",
                return_value=redis,
            ),
            patch(
                "handlers.base.asyncio.create_task",
                side_effect=capture,
            ),
        ):
            self.assertIs(
                await cls.get_shared_pubsub(),
                pubsub,
            )
        pubsub.subscribe.assert_awaited_once_with(
            cls._LOGOUT_EVENT_CHANNEL
        )

    async def test_runtime_registration_subscribes_existing_pubsub(self):
        cls = UnifiedWebSocketHandler
        cls._shared_pubsub = AsyncMock()
        callback = object()
        cls.register_channel_callback("runtime", callback)
        await asyncio.sleep(0)
        self.assertIs(
            cls._channel_callbacks["runtime"],
            callback,
        )
        cls._shared_pubsub.subscribe.assert_awaited_once_with(
            "runtime"
        )

    async def test_listener_swallows_candidate_and_cleanup_errors(self):
        cls = UnifiedWebSocketHandler

        close_failure = MagicMock(session_id="logout")
        close_failure.close.side_effect = RuntimeError("close")
        close_failure.cleanup = AsyncMock(
            side_effect=RuntimeError("cleanup")
        )
        bad_session = BadSession()
        write_failure = MagicMock()
        write_failure.write_message = AsyncMock(
            side_effect=RuntimeError("write")
        )
        write_failure.cleanup = AsyncMock(
            side_effect=RuntimeError("cleanup")
        )

        cls.active_connections = {
            close_failure,
            bad_session,
        }
        cls.subscriptions = {
            write_failure: {"raw"},
        }
        cls._shared_pubsub = SimpleNamespace(
            listen=lambda: AsyncMessages(
                [
                    {
                        "type": "message",
                        "channel": cls._LOGOUT_EVENT_CHANNEL,
                        "data": "logout",
                    },
                    {
                        "type": "message",
                        "channel": "raw",
                        "data": "value",
                    },
                ]
            )
        )

        with self.assertRaises(asyncio.CancelledError):
            await cls._listen_redis_messages()
        close_failure.cleanup.assert_awaited_once()
        write_failure.cleanup.assert_awaited_once()

    async def test_listener_updates_retry_delay_before_second_failure(self):
        cls = UnifiedWebSocketHandler

        class BrokenPubsub:
            def listen(self):
                raise RuntimeError("redis")

        cls._shared_pubsub = BrokenPubsub()
        sleep = AsyncMock(
            side_effect=[None, asyncio.CancelledError()]
        )
        with (
            patch("handlers.base.asyncio.sleep", sleep),
            patch.object(
                cls,
                "get_shared_pubsub",
                AsyncMock(side_effect=RuntimeError("redis")),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await cls._listen_redis_messages()
        self.assertEqual(
            [call.args[0] for call in sleep.await_args_list],
            [1, 2],
        )

    async def test_message_none_callbacks_and_outer_exception(self):
        cls = UnifiedWebSocketHandler
        handler = self.handler()

        await handler.on_message(
            json.dumps({"type": "register", "data": "missing"})
        )
        self.assertIn("missing", cls.subscriptions[handler])

        cls.subscriptions = {}
        await handler.on_message(
            json.dumps({"type": "unregister", "data": "missing"})
        )

        callback = SimpleNamespace(
            register=AsyncMock(side_effect=RuntimeError("callback"))
        )
        cls._channel_callbacks = {"broken": callback}
        await handler.on_message(
            json.dumps({"type": "register", "data": "broken"})
        )
        callback.register.assert_awaited_once()

        cls._channel_callbacks = {"plain": object()}
        await handler.on_message(
            json.dumps({"type": "custom", "data": "ignored"})
        )

    async def test_listener_initializes_missing_pubsub(self):
        cls = UnifiedWebSocketHandler
        pubsub = SimpleNamespace(listen=lambda: AsyncMessages([]))

        async def initialize():
            cls._shared_pubsub = pubsub
            return pubsub

        with (
            patch.object(cls, "get_shared_pubsub", side_effect=initialize),
            patch.object(cls, "_resubscribe_all_channels", new=AsyncMock()),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await cls._listen_redis_messages()

    async def test_ping_close_errors_and_cleanup_error(self):
        handler = self.handler()
        loop = MagicMock()
        loop.time.return_value = 100.0
        handler.last_pong = 1.0
        handler.close = MagicMock(side_effect=RuntimeError("close"))
        with patch(
            "handlers.base.tornado.ioloop.IOLoop.current",
            return_value=loop,
        ):
            handler.periodic_ping()

        handler.last_pong = 100.0
        handler.write_message = MagicMock(
            side_effect=RuntimeError("write")
        )
        with patch(
            "handlers.base.tornado.ioloop.IOLoop.current",
            return_value=loop,
        ):
            handler.periodic_ping()

        handler.ping_callback = MagicMock()
        handler.ping_callback.stop.side_effect = RuntimeError("stop")
        await handler.cleanup()

        handler = self.handler()
        cls = UnifiedWebSocketHandler
        cls.subscriptions = {}
        cls.active_connections = set()
        await handler.cleanup()
        self.assertNotIn(handler, cls.subscriptions)


if __name__ == "__main__":
    unittest.main()
