import os
import json
import uuid

import tornado.process

from req import WebSocketHandler
import config

from dbg import dbg_print

class PackService:
    def __init__(self, db, rs) -> None:
        self.db = db
        self.rs = rs
        PackService.inst = self

    async def gen_token(self):
        pack_token = str(uuid.uuid1())
        await self.rs.set(f'PACK_TOKEN@{pack_token}', 0)

        return (None, pack_token)

    async def direct_copy(self, pack_token, dst):
        pack_token = str(uuid.UUID(pack_token))

        ret = await self.rs.get(f'PACK_TOKEN@{pack_token}')
        if ret == None:
            return ('Enoext', None)

        await self.rs.delete(f'PACK_TOKEN@{pack_token}')

        inf = open(f'tmp/{pack_token}', 'rb')
        outf = open(dst, 'wb')
        while True:
            data = inf.read(65536)
            if len(data) == 0:
                break

            outf.write(data)

        inf.close()
        outf.close()

        os.remove(f'tmp/{pack_token}')

    async def unpack(self, pack_token, dst, clean=False):
        def _unpack():
            def __rm_cb(code):
                os.makedirs(dst, 0o700)
                __tar()

            def __tar():
                sub = tornado.process.Subprocess(
                        ['/bin/tar', '-Jxf', f'tmp/{pack_token}', '-C', dst])
                sub.set_exit_callback(__tar_cb)

            def __tar_cb(code):
                if code != 0:
                    return ('Eunk', None)

                #os.remove('tmp/%s'%pack_token)

                sub = tornado.process.Subprocess(
                        ['/bin/bash', 'newline.sh', f'{dst}/res/testdata'])

            if clean == False:
                __tar()

            else:
                sub = tornado.process.Subprocess(
                        ['/bin/rm', '-Rf', dst])
                sub.set_exit_callback(__rm_cb)

        pack_token = str(uuid.UUID(pack_token))

        ret = await self.rs.get(f'PACK_TOKEN@{pack_token}')
        if ret == None:
            return ('Enoext', None)

        await self.rs.delete(f'PACK_TOKEN@{pack_token}')

        ret = _unpack()
        return ret

class PackHandler(WebSocketHandler):
    STATE_HDR = 0
    STATE_DTAT = 1
    CHUNK_MAX = 65536

    def check_origin(self, origin: str) -> bool:
        #TODO: secure
        return True

    async def open(self):
        self.state = PackHandler.STATE_HDR
        self.output = None
        self.remain = 0

    async def on_message(self, msg):
        if self.state == PackHandler.STATE_DTAT:
            size = len(msg)
            if size > PackHandler.CHUNK_MAX or size > self.remain:
                self.write_message('Echunk')
                self.output.close()
                self.output = None
                return

            self.output.write(msg)
            self.remain -= size

            if self.remain == 0:
                self.output.close()
                self.output = None

            self.write_message('S')
            return

        elif self.state == PackHandler.STATE_HDR:
            hdr = json.loads(msg)

            self.pack_token = str(uuid.UUID(hdr['pack_token']))
            self.remain = hdr['pack_size']
            self.output = open(f'tmp/{self.pack_token}', 'wb')
            self.state = PackHandler.STATE_DTAT

            self.write_message('S')
            return

    def on_close(self) -> None:
        if self.output != None:
            self.output.close()

        if self.remain > 0:
            os.remove(f'tmp/{self.pack_token}')
