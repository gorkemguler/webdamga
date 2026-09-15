"""Zamanlanmış izleme: bir URL'yi aralıklarla yakalayıp değişiklikleri işaretler.

Phishing sayfaları çoğu zaman canlı değişir: önce masum görünür, sonra formu
açılır, ihbardan sonra başka bir alan adına taşınır ya da tamamen kapanır.
İzleyici her turda kuyruğa normal bir yakalama işi ekler; iş bitince yeni
yakalama, izleyicinin son *başarılı* yakalamasıyla karşılaştırılır.

- Değişiklik yoksa sadece taban güncellenir.
- Küçük ya da önemli değişiklikte işe ve izleyiciye yargı yazılır.
- Yakalama başarısızsa (ör. alan adı artık çözülmüyor, site kapandı) taban
  değiştirilmez; bir sonraki başarılı yakalama yine son sağlam hâlle
  karşılaştırılır, başarısızlığın kendisi de iş geçmişinde görünür.

Zamanlayıcı, web arayüzüyle aynı süreçte (webdamga serve) ya da tek başına
(webdamga monitor run) çalışır.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from datetime import UTC, datetime, timedelta

from .capture import normalize_url
from .config import CaptureSettings
from .diff import compare_captures, describe_reason, diff_dir
from .jobs import CaptureQueue
from .notify import ChangeEvent, configured_channels, dispatch, should_notify
from .storage import Store, now_iso

log = logging.getLogger("webdamga.monitor")

MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 60 * 24 * 30


class MonitorError(ValueError):
    pass


def _after(minutes: int, start: datetime | None = None) -> str:
    moment = (start or datetime.now(UTC)) + timedelta(minutes=minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_interval(minutes: int) -> int:
    if not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
        raise MonitorError(
            f"interval must be between {MIN_INTERVAL_MINUTES} minutes and {MAX_INTERVAL_MINUTES // 1440} days"
        )
    return minutes


def add_monitor(
    store: Store,
    url: str,
    interval_minutes: int,
    settings: CaptureSettings | None = None,
    *,
    label: str | None = None,
) -> dict:
    validate_interval(interval_minutes)
    settings = settings or CaptureSettings()
    return store.create_monitor(
        normalize_url(url),
        interval_minutes,
        json.dumps(settings.to_storage()),
        label=(label or "").strip() or None,
    )


class Scheduler:
    """Zamanı gelen izleyicileri kuyruğa ekler ve biten işleri karşılaştırır."""

    def __init__(self, store: Store, queue: CaptureQueue, *, tick_seconds: float = 20.0) -> None:
        self.store = store
        self.queue = queue
        self.data_dir = queue.data_dir
        self.tick_seconds = tick_seconds
        self._task: asyncio.Task | None = None
        queue.on_finished(self.on_job_finished)

    # ------------------------------------------------------------- zamanlama

    def tick(self, now: datetime | None = None) -> list[dict]:
        """Zamanı gelenleri kuyruğa ekler; eklenen işleri döner."""
        moment = now or datetime.now(UTC)
        stamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        jobs = []
        for monitor in self.store.due_monitors(stamp):
            jobs.append(self.run_now(monitor, now=moment))
        return jobs

    def run_now(self, monitor: dict, *, now: datetime | None = None) -> dict:
        moment = now or datetime.now(UTC)
        settings = CaptureSettings.from_storage(json.loads(monitor["settings_json"]))
        job = self.queue.enqueue(monitor["url"], settings, source="monitor", monitor_id=monitor["id"])
        # Bir sonraki tur, bu turun başladığı andan itibaren sayılır; uzun süren
        # yakalamalar aralığı kaydırmasın.
        self.store.update_monitor(
            monitor["id"],
            last_run_utc=moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
            next_run_utc=_after(monitor["interval_minutes"], moment),
        )
        return job

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="webdamga-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(self.tick_seconds)

    # ----------------------------------------------------------- karşılaştırma

    async def on_job_finished(self, job: dict, meta: dict) -> None:
        if not job.get("monitor_id"):
            return
        await asyncio.to_thread(self._record_result, job, meta)

    def _record_result(self, job: dict, meta: dict) -> None:
        monitor = self.store.get_monitor(job["monitor_id"])
        if monitor is None or job.get("status") != "done" or not job.get("capture_id"):
            return  # silinmiş izleyici ya da başarısız yakalama: taban korunur

        new_id = job["capture_id"]
        previous = monitor.get("last_capture_id")
        captures = self.data_dir / "captures"
        if previous and (captures / previous / "metadata.json").is_file():
            result = compare_captures(
                captures / previous, captures / new_id, diff_dir(self.data_dir, previous, new_id)
            )
            level = result["verdict"]
            self.store.set_job_change(job["id"], level, previous)
            if level != "identical":
                changed_at = now_iso()
                self.store.update_monitor(monitor["id"], last_change_utc=changed_at, last_change_level=level)
                log.info("monitor %s: %s change (%s -> %s)", monitor["id"], level, previous, new_id)
                self._notify_change(monitor, result, previous, new_id, changed_at)
        self.store.update_monitor(monitor["id"], last_capture_id=new_id)

    def _notify_change(
        self, monitor: dict, result: dict, previous: str, new_id: str, changed_at: str
    ) -> None:
        """Eşiği geçen değişikliği yapılandırılmış kanallara bildirir (hata yakalamayı bozmaz)."""
        level = result["verdict"]
        if not (configured_channels() and should_notify(level)):
            return
        lang = os.environ.get("WEBDAMGA_LANG", "en")
        event = ChangeEvent(
            monitor_id=monitor["id"],
            label=monitor.get("label"),
            url=monitor["url"],
            level=level,
            previous_id=previous,
            capture_id=new_id,
            reasons=[describe_reason(r, lang) for r in result.get("reasons", [])],
            detected_utc=changed_at,
        )
        try:
            dispatch(event)
        except Exception:
            log.exception("notification dispatch failed for monitor %s", monitor["id"])
