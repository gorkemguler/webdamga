"""Testler için küçük bir HTTP CONNECT proxy'si.

Yalnızca tünel kurar ve hangi hedeflere bağlanıldığını kaydeder; böylece bir
yakalamanın gerçekten proxy'den geçip geçmediği doğrulanabilir.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import Self


class RecordingProxy:
    def __init__(self) -> None:
        self.targets: list[str] = []
        self.port = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.base_events.Server | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    async def _pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(Exception):
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        with contextlib.suppress(Exception):
            writer.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        method, target, *_ = head.split(b"\r\n", 1)[0].decode().split(" ")
        if method != "CONNECT":
            writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            writer.close()
            return
        self.targets.append(target)
        host, _, port = target.rpartition(":")
        try:
            up_reader, up_writer = await asyncio.open_connection(host, int(port))
        except OSError:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            writer.close()
            return
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(self._pipe(reader, up_writer), self._pipe(up_reader, writer))

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()

        async def main() -> None:
            self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
            self.port = self._server.sockets[0].getsockname()[1]
            self._ready.set()
            async with self._server:
                await self._server.serve_forever()

        with contextlib.suppress(asyncio.CancelledError):
            self._loop.run_until_complete(main())

    def __enter__(self) -> Self:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(5)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._loop and self._server:
            self._loop.call_soon_threadsafe(self._server.close)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"
