import datetime
from msgpack import packb, unpackb

from req import WebSocketHandler

from dbg import dbg_print

class InformService:
    def __init__(self, db, rs) -> None:
        self.db = db
        self.rs = rs
        InformService.inst = self

    async def set_inform(self, text):
        inform_list = unpackb((await self.rs.get('inform')))
        inform_list.append({ 'text': str(text), 'time': str(datetime.datetime.now())[:-7], 'color': 'white' })
        inform_list.sort(key=lambda row: row['time'], reverse=True)
        await self.rs.set('inform', packb(inform_list))
        await self.rs.publish('informsub', 1)
        return

    async def edit_inform(self, index, text, color):
        inform_list = unpackb((await self.rs.get('inform')))
        inform_list[int(index)] = {'text': str(text), 'time': str(datetime.datetime.now())[:-7], 'color': color }
        inform_list.sort(key=lambda row: row['time'], reverse=True)
        await self.rs.set('inform', packb(inform_list))
        await self.rs.publish('informsub', 1)
        return

    async def del_inform(self, index):
        inform_list = unpackb((await self.rs.get('inform')))
        inform_list.pop(int(index))
        inform_list.sort(key=lambda row: row['time'], reverse=True)
        await self.rs.set('inform', packb(inform_list))
        return

from redis import asyncio as aioredis
import asyncio

class InformSub(WebSocketHandler):
    async def open(self):
        self.ars = aioredis.Redis(host='localhost', port=6379, db=1)
        await self.ars.incr('online_counter', 1)
        await self.ars.sadd('online_counter_set', self.request.remote_ip)
        self.p = self.ars.pubsub()
        await self.p.subscribe('informsub')

        async def test():
            async for msg in self.p.listen():
                if msg['type'] != 'message':
                    continue

                await self.on_message(str(int(msg['data'])))

        self.task = asyncio.tasks.Task(test())

    async def on_message(self, msg):
        self.write_message(msg)

    def on_close(self) -> None:
        dbg_print(__file__, 64, ip=self.request.remote_ip)
        asyncio.create_task(self.ars.decr('online_counter', 1))
        asyncio.create_task(self.ars.srem('online_counter_set', self.request.remote_ip))
        self.task.cancel()

    def check_origin(self, origin):
        #TODO: secure
        return True
