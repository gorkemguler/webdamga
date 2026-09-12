"""Arka plan kuyruğu: depolama, worker ve API davranışı."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webdamga.config import CaptureSettings
from webdamga.jobs import CaptureQueue
from webdamga.storage import MAX_ATTEMPTS, Store


def _fake_capture(ok: bool = True, error: str | None = None):
    """Tarayıcı açmadan yakalama klasörü ve metadata üreten sahte fonksiyon."""
    calls: list[tuple[str, CaptureSettings]] = []

    async def capture(url: str, data_dir: Path, settings: CaptureSettings) -> dict:
        calls.append((url, settings))
        capture_id = f"cap-{len(calls)}"
        folder = data_dir / "captures" / capture_id
        folder.mkdir(parents=True, exist_ok=True)
        meta = {
            "capture_id": capture_id,
            "dir": str(folder),
            "requested_url": url,
            "final_url": url,
            "completed_at_utc": "2026-01-01T00:00:00Z",
            "ok": ok,
        }
        if error:
            meta["error"] = error
        return meta

    capture.calls = calls  # type: ignore[attr-defined]
    return capture


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path)


def test_settings_round_trip() -> None:
    original = CaptureSettings(full_page=False, viewport_width=1440, wait_until="networkidle")
    restored = CaptureSettings.from_storage(json.loads(json.dumps(original.to_storage())))
    assert restored == original


def test_settings_ignore_unknown_fields() -> None:
    restored = CaptureSettings.from_storage({"full_page": False, "from_the_future": 1})
    assert restored.full_page is False


def test_enqueue_creates_queued_job(store: Store, tmp_path: Path) -> None:
    queue = CaptureQueue(store, tmp_path, capture_fn=_fake_capture())
    job = queue.enqueue("example.com", source="cli")
    assert job["status"] == "queued"
    assert job["url"] == "https://example.com"  # normalize edildi
    assert job["source"] == "cli"


def test_run_once_completes_job_and_records_capture(store: Store, tmp_path: Path) -> None:
    fake = _fake_capture()
    queue = CaptureQueue(store, tmp_path, capture_fn=fake)
    queue.enqueue("https://example.com", CaptureSettings(viewport_width=999))

    finished = asyncio.run(queue.run_once())

    assert finished is not None
    assert finished["status"] == "done"
    assert finished["capture_id"] == "cap-1"
    assert finished["attempts"] == 1
    assert store.get("cap-1") is not None
    # Kuyrukta saklanan ayarlar worker'a aynen ulaşmalı.
    assert fake.calls[0][1].viewport_width == 999


def test_run_once_returns_none_when_empty(store: Store, tmp_path: Path) -> None:
    queue = CaptureQueue(store, tmp_path, capture_fn=_fake_capture())
    assert asyncio.run(queue.run_once()) is None


def test_failed_capture_marks_job_failed_but_keeps_capture(store: Store, tmp_path: Path) -> None:
    queue = CaptureQueue(store, tmp_path, capture_fn=_fake_capture(ok=False, error="navigation: DNS"))
    queue.enqueue("https://does-not-resolve.invalid")
    finished = asyncio.run(queue.run_once())
    assert finished["status"] == "failed"
    assert finished["error"] == "navigation: DNS"
    # Başarısız yakalama da kanıt klasörü üretir, iş ona bağlı kalmalı.
    assert finished["capture_id"] == "cap-1"


def test_crashing_capture_does_not_kill_the_queue(store: Store, tmp_path: Path) -> None:
    async def boom(url, data_dir, settings):
        raise RuntimeError("browser exploded")

    queue = CaptureQueue(store, tmp_path, capture_fn=boom)
    queue.enqueue("https://example.com")
    finished = asyncio.run(queue.run_once())
    assert finished["status"] == "failed"
    assert "browser exploded" in finished["error"]


def test_jobs_are_processed_in_fifo_order(store: Store, tmp_path: Path) -> None:
    fake = _fake_capture()
    queue = CaptureQueue(store, tmp_path, capture_fn=fake)
    for n in range(3):
        queue.enqueue(f"https://example.com/{n}")

    async def drain():
        while await queue.run_once():
            pass

    asyncio.run(drain())
    assert [url for url, _ in fake.calls] == [f"https://example.com/{n}" for n in range(3)]


def test_cancel_only_affects_queued_jobs(store: Store, tmp_path: Path) -> None:
    queue = CaptureQueue(store, tmp_path, capture_fn=_fake_capture())
    waiting = queue.enqueue("https://example.com/a")
    assert store.cancel_job(waiting["id"]) is True
    assert store.get_job(waiting["id"])["status"] == "cancelled"
    assert store.cancel_job(waiting["id"]) is False  # zaten iptal

    queue.enqueue("https://example.com/b")
    finished = asyncio.run(queue.run_once())
    assert store.cancel_job(finished["id"]) is False  # bitmiş iş iptal edilemez


def test_cancelled_jobs_are_never_run(store: Store, tmp_path: Path) -> None:
    fake = _fake_capture()
    queue = CaptureQueue(store, tmp_path, capture_fn=fake)
    job = queue.enqueue("https://example.com")
    store.cancel_job(job["id"])
    assert asyncio.run(queue.run_once()) is None
    assert fake.calls == []


def test_interrupted_jobs_are_requeued(store: Store, tmp_path: Path) -> None:
    queue = CaptureQueue(store, tmp_path, capture_fn=_fake_capture())
    job = queue.enqueue("https://example.com")
    store.claim_next_job()  # süreç işi alıp çökmüş gibi
    assert store.get_job(job["id"])["status"] == "running"

    requeued, failed = store.recover_interrupted_jobs()
    assert (requeued, failed) == (1, 0)
    assert store.get_job(job["id"])["status"] == "queued"


def test_repeatedly_interrupted_job_gives_up(store: Store, tmp_path: Path) -> None:
    queue = CaptureQueue(store, tmp_path, capture_fn=_fake_capture())
    job = queue.enqueue("https://example.com")
    for _ in range(MAX_ATTEMPTS):
        store.claim_next_job()
        store.recover_interrupted_jobs()
    row = store.get_job(job["id"])
    assert row["status"] == "failed"
    assert "interrupted" in row["error"]


def test_worker_loop_picks_up_new_jobs_and_fires_callbacks(store: Store, tmp_path: Path) -> None:
    seen: list[str] = []

    async def scenario():
        queue = CaptureQueue(store, tmp_path, capture_fn=_fake_capture(), poll_interval=0.05)

        async def on_done(job, meta):
            seen.append(job["status"])

        queue.on_finished(on_done)
        await queue.start()
        try:
            job = queue.enqueue("https://example.com")
            for _ in range(100):
                if store.get_job(job["id"])["status"] == "done" and seen:
                    break
                await asyncio.sleep(0.02)
        finally:
            await queue.stop()
        return store.get_job(job["id"])

    job = asyncio.run(scenario())
    assert job["status"] == "done"
    assert seen == ["done"]


def test_worker_recovers_jobs_left_running_on_start(store: Store, tmp_path: Path) -> None:
    queue = CaptureQueue(store, tmp_path, capture_fn=_fake_capture(), poll_interval=0.05)
    job = queue.enqueue("https://example.com")
    store.claim_next_job()  # önceki süreçte yarıda kalmış

    async def scenario():
        await queue.start()
        try:
            for _ in range(100):
                if store.get_job(job["id"])["status"] == "done":
                    break
                await asyncio.sleep(0.02)
        finally:
            await queue.stop()

    asyncio.run(scenario())
    assert store.get_job(job["id"])["status"] == "done"


# ----------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    from webdamga import api

    importlib.reload(api)
    # Lifespan çalıştırılmıyor: worker yok, işler kuyrukta bekler ve test
    # deterministik kalır.
    return TestClient(api.app), api


def test_form_submit_enqueues_and_redirects_to_job(client) -> None:
    http, api = client
    response = http.post("/captures", data={"url": "example.com"}, follow_redirects=False)
    assert response.status_code == 303
    job_id = response.headers["location"].rsplit("/", 1)[1]
    job = api._store.get_job(job_id)
    assert job["status"] == "queued"
    assert job["source"] == "web"


def test_unchecked_full_page_checkbox_is_respected(client) -> None:
    """Checkbox işaretsizken tarayıcı alanı hiç göndermez; False olmalı."""
    http, api = client
    response = http.post("/captures", data={"url": "example.com"}, follow_redirects=False)
    job_id = response.headers["location"].rsplit("/", 1)[1]
    assert json.loads(api._store.get_job(job_id)["settings_json"])["full_page"] is False

    response = http.post(
        "/captures", data={"url": "example.com", "full_page": "true"}, follow_redirects=False
    )
    job_id = response.headers["location"].rsplit("/", 1)[1]
    assert json.loads(api._store.get_job(job_id)["settings_json"])["full_page"] is True


def test_job_page_renders_status(client) -> None:
    http, api = client
    job = api.queue.enqueue("https://example.com")
    page = http.get(f"/jobs/{job['id']}?lang=en").text
    assert "Capture job" in page
    assert "queued" in page


def test_finished_job_page_redirects_to_capture(client) -> None:
    http, api = client
    job = api.queue.enqueue("https://example.com")
    api._store.finish_job(job["id"], status="done", capture_id="some-capture")
    response = http.get(f"/jobs/{job['id']}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/captures/some-capture"


def test_api_job_lifecycle(client) -> None:
    http, _ = client
    created = http.post("/api/jobs", json={"url": "example.com", "width": 1440})
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "queued"
    assert body["settings"]["viewport_width"] == 1440
    assert "settings_json" not in body

    assert http.get(f"/api/jobs/{body['id']}").json()["id"] == body["id"]
    assert [j["id"] for j in http.get("/api/jobs?status=queued").json()] == [body["id"]]

    assert http.delete(f"/api/jobs/{body['id']}").json()["status"] == "cancelled"
    assert http.delete(f"/api/jobs/{body['id']}").status_code == 409
    assert http.get("/api/jobs/nope").status_code == 404


def test_api_rejects_invalid_capture_request(client) -> None:
    http, _ = client
    assert http.post("/api/jobs", json={"url": "example.com", "timeout": 1}).status_code == 422
    assert http.post("/api/jobs", json={}).status_code == 422


def test_index_lists_active_jobs(client) -> None:
    http, api = client
    api.queue.enqueue("https://queued.example")
    page = http.get("/?lang=en").text
    assert "In progress" in page
    assert "https://queued.example" in page
