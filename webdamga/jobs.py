"""Arka plan yakalama kuyruğu.

Web arayüzü bir yakalama isteğini beklemek yerine kuyruğa yazar ve hemen
döner; aynı süreçteki asyncio worker'ları işleri SQLite'tan sırayla alıp
çalıştırır. Kuyruk veritabanında durduğu için süreç yeniden başladığında
yarıda kalan işler kaybolmaz, tekrar kuyruğa alınır.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from .capture import capture as run_capture
from .capture import normalize_url
from .config import CaptureSettings
from .storage import Store

log = logging.getLogger("webdamga.jobs")

JobCallback = Callable[[dict, dict], Awaitable[None]]
CaptureFn = Callable[[str, Path, CaptureSettings], Awaitable[dict]]


class CaptureQueue:
    def __init__(
        self,
        store: Store,
        data_dir: Path,
        *,
        concurrency: int = 1,
        poll_interval: float = 2.0,
        capture_fn: CaptureFn = run_capture,
    ) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        self.concurrency = max(1, concurrency)
        self.poll_interval = poll_interval
        self._capture_fn = capture_fn
        self._callbacks: list[JobCallback] = []
        self._workers: list[asyncio.Task] = []
        self._wake: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ public

    def on_finished(self, callback: JobCallback) -> None:
        """İş bittiğinde (başarılı ya da değil) çağrılacak async fonksiyon ekler."""
        self._callbacks.append(callback)

    def enqueue(
        self,
        url: str,
        settings: CaptureSettings | None = None,
        *,
        source: str = "web",
        monitor_id: int | None = None,
    ) -> dict:
        settings = settings or CaptureSettings()
        job = self.store.create_job(
            normalize_url(url),
            json.dumps(settings.to_storage()),
            source=source,
            monitor_id=monitor_id,
        )
        self._notify()
        return job

    @property
    def running(self) -> bool:
        return bool(self._workers)

    async def start(self) -> None:
        if self._workers:
            return
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        requeued, failed = await asyncio.to_thread(self.store.recover_interrupted_jobs)
        if requeued or failed:
            log.warning("recovered interrupted jobs: %d requeued, %d failed", requeued, failed)
        self._workers = [
            asyncio.create_task(self._worker(n), name=f"webdamga-worker-{n}") for n in range(self.concurrency)
        ]

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._workers = []

    async def run_once(self) -> dict | None:
        """Bekleyen tek bir işi çalıştırır (testler ve CLI için)."""
        job = await asyncio.to_thread(self.store.claim_next_job)
        if job is not None:
            await self._run(job)
            return await asyncio.to_thread(self.store.get_job, job["id"])
        return None

    # ---------------------------------------------------------------- internals

    def _notify(self) -> None:
        # enqueue FastAPI'nin thread havuzundan da çağrılabilir; Event
        # thread-safe olmadığı için uyandırmayı event loop'a devrediyoruz.
        if self._loop is not None and self._wake is not None:
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._wake.set)

    async def _worker(self, n: int) -> None:
        assert self._wake is not None
        while True:
            job = await asyncio.to_thread(self.store.claim_next_job)
            if job is None:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval)
                continue
            await self._run(job)

    async def _run(self, job: dict) -> None:
        settings = CaptureSettings.from_storage(json.loads(job["settings_json"]))
        meta: dict = {}
        try:
            meta = await self._capture_fn(job["url"], self.data_dir, settings)
            await asyncio.to_thread(
                self.store.record,
                meta,
                manifest_sha256=meta.get("manifest_sha256"),
                ok=bool(meta.get("ok")),
                error=meta.get("error"),
            )
            status = "done" if meta.get("ok") else "failed"
            await asyncio.to_thread(
                self.store.finish_job,
                job["id"],
                status=status,
                capture_id=meta.get("capture_id"),
                error=meta.get("error"),
            )
        except asyncio.CancelledError:
            # Kapanışta yarıda kalan iş, sonraki açılışta tekrar kuyruğa alınır.
            raise
        except Exception as exc:
            log.exception("job %s crashed", job["id"])
            await asyncio.to_thread(
                self.store.finish_job,
                job["id"],
                status="failed",
                capture_id=meta.get("capture_id"),
                error=f"{type(exc).__name__}: {exc}",
            )

        finished = await asyncio.to_thread(self.store.get_job, job["id"])
        for callback in self._callbacks:
            try:
                await callback(finished or job, meta)
            except Exception:
                log.exception("job callback failed for %s", job["id"])
