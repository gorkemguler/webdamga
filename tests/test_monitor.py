"""Zamanlanmış izleme: zamanlayıcı, değişiklik tespiti, API ve CLI."""

from __future__ import annotations

import asyncio
import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_diff import CLEAN, PHISH, _capture
from typer.testing import CliRunner

from webdamga.config import CaptureSettings
from webdamga.jobs import CaptureQueue
from webdamga.monitor import MIN_INTERVAL_MINUTES, MonitorError, Scheduler, add_monitor
from webdamga.storage import Store


class _Site:
    """Yakalama fonksiyonunu taklit eder: o anki içerikle bir yakalama klasörü üretir."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.html = CLEAN
        self.up = True
        self.count = 0

    async def capture(self, url: str, data_dir: Path, settings: CaptureSettings) -> dict:
        self.count += 1
        name = f"cap-{self.count}"
        completed = f"2026-01-01T00:{self.count:02d}:00Z"
        if not self.up:
            folder = data_dir / "captures" / name
            folder.mkdir(parents=True)
            meta = {
                "capture_id": name,
                "dir": str(folder),
                "requested_url": url,
                "completed_at_utc": completed,
            }
            (folder / "metadata.json").write_text(json.dumps(meta))
            return {**meta, "ok": False, "error": "navigation: net::ERR_NAME_NOT_RESOLVED"}
        folder = _capture(data_dir, name, html=self.html, final_url=url, completed=completed)
        meta = json.loads((folder / "metadata.json").read_text())
        return {**meta, "dir": str(folder), "ok": True}


@pytest.fixture
def setup(tmp_path: Path):
    store = Store(tmp_path)
    site = _Site(tmp_path)
    queue = CaptureQueue(store, tmp_path, capture_fn=site.capture)
    scheduler = Scheduler(store, queue)
    return store, site, queue, scheduler


def _drain(queue: CaptureQueue) -> None:
    async def run():
        while await queue.run_once():
            pass

    asyncio.run(run())


# ------------------------------------------------------------------ doğrulama


@pytest.mark.parametrize("minutes", [0, 4, 60 * 24 * 31])
def test_interval_limits(setup, minutes: int) -> None:
    store, *_ = setup
    with pytest.raises(MonitorError):
        add_monitor(store, "https://example.com", minutes)


def test_add_monitor_normalises_and_is_due_immediately(setup) -> None:
    store, *_ = setup
    monitor = add_monitor(store, "example.com", MIN_INTERVAL_MINUTES, label="  Banka  ")
    assert monitor["url"] == "https://example.com"
    assert monitor["label"] == "Banka"
    assert monitor["enabled"] == 1
    assert store.due_monitors(monitor["next_run_utc"]) == [monitor]


# ------------------------------------------------------------------ zamanlama


def test_tick_enqueues_due_monitors_and_schedules_next_run(setup) -> None:
    store, _, _, scheduler = setup
    monitor = add_monitor(store, "https://example.com", 30)
    now = datetime.now(UTC)

    (job,) = scheduler.tick(now)
    assert job["monitor_id"] == monitor["id"]
    assert job["source"] == "monitor"

    updated = store.get_monitor(monitor["id"])
    expected_next = (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert updated["next_run_utc"] == expected_next
    assert scheduler.tick(now) == []  # zamanı gelmedi


def test_no_duplicate_job_while_previous_run_is_active(setup) -> None:
    store, _, _, scheduler = setup
    monitor = add_monitor(store, "https://example.com", 5)
    scheduler.tick()
    store.update_monitor(monitor["id"], next_run_utc="2000-01-01T00:00:00Z")  # yine vakti geldi
    assert scheduler.tick() == []  # ilk iş hâlâ kuyrukta


def test_paused_monitors_are_skipped(setup) -> None:
    store, _, _, scheduler = setup
    monitor = add_monitor(store, "https://example.com", 5)
    store.update_monitor(monitor["id"], enabled=0)
    assert scheduler.tick() == []


def test_monitor_settings_reach_the_capture(setup) -> None:
    store, site, queue, scheduler = setup
    add_monitor(store, "https://example.com", 5, CaptureSettings(proxy_profile="tor", timestamp=True))
    received: list[CaptureSettings] = []
    original = site.capture

    async def spy(url, data_dir, settings):
        received.append(settings)
        return await original(url, data_dir, settings)

    queue._capture_fn = spy
    scheduler.tick()
    _drain(queue)
    assert received[0].proxy_profile == "tor" and received[0].timestamp is True


# ----------------------------------------------------------- değişiklik tespiti


def test_first_run_sets_baseline_without_verdict(setup) -> None:
    store, _, queue, scheduler = setup
    monitor = add_monitor(store, "https://bank.example/login", 5)
    scheduler.tick()
    _drain(queue)

    updated = store.get_monitor(monitor["id"])
    assert updated["last_capture_id"] == "cap-1"
    assert updated["last_change_level"] is None
    (run,) = store.list_jobs(monitor_id=monitor["id"])
    assert run["change_level"] is None


def test_unchanged_page_is_identical(setup) -> None:
    store, _, queue, scheduler = setup
    monitor = add_monitor(store, "https://bank.example/login", 5)
    for _ in range(2):
        scheduler.run_now(store.get_monitor(monitor["id"]))
        _drain(queue)

    latest = store.list_jobs(monitor_id=monitor["id"])[0]
    assert (latest["change_level"], latest["compared_to"]) == ("identical", "cap-1")
    assert store.get_monitor(monitor["id"])["last_change_level"] is None


def test_page_turning_into_phishing_is_flagged(setup) -> None:
    store, site, queue, scheduler = setup
    monitor = add_monitor(store, "https://bank.example/login", 5)
    scheduler.run_now(monitor)
    _drain(queue)

    site.html = PHISH
    scheduler.run_now(store.get_monitor(monitor["id"]))
    _drain(queue)

    latest = store.list_jobs(monitor_id=monitor["id"])[0]
    assert latest["change_level"] == "major"
    assert latest["compared_to"] == "cap-1"
    updated = store.get_monitor(monitor["id"])
    assert updated["last_change_level"] == "major"
    assert updated["last_capture_id"] == "cap-2"
    assert (store.data_dir / "diffs" / "cap-1__cap-2" / "diff.json").is_file()


def test_failed_capture_keeps_the_last_good_baseline(setup) -> None:
    store, site, queue, scheduler = setup
    monitor = add_monitor(store, "https://bank.example/login", 5)
    scheduler.run_now(monitor)
    _drain(queue)

    site.up = False  # site kapandı
    scheduler.run_now(store.get_monitor(monitor["id"]))
    _drain(queue)
    assert store.list_jobs(monitor_id=monitor["id"])[0]["status"] == "failed"
    assert store.get_monitor(monitor["id"])["last_capture_id"] == "cap-1"

    site.up, site.html = True, PHISH  # başka içerikle geri geldi
    scheduler.run_now(store.get_monitor(monitor["id"]))
    _drain(queue)
    latest = store.list_jobs(monitor_id=monitor["id"])[0]
    assert (latest["change_level"], latest["compared_to"]) == ("major", "cap-1")


def test_deleted_monitor_does_not_break_a_finishing_job(setup) -> None:
    store, _, queue, scheduler = setup
    monitor = add_monitor(store, "https://example.com", 5)
    scheduler.run_now(monitor)
    store.delete_monitor(monitor["id"])
    _drain(queue)  # hata vermemeli
    assert store.get_monitor(monitor["id"]) is None


def test_existing_database_gains_new_columns(tmp_path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(tmp_path / "webdamga.db")
    conn.execute(
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, url TEXT NOT NULL, settings_json TEXT NOT NULL,"
        " status TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'web', monitor_id INTEGER, capture_id TEXT,"
        " error TEXT, attempts INTEGER NOT NULL DEFAULT 0, created_utc TEXT NOT NULL, started_utc TEXT,"
        " finished_utc TEXT)"
    )
    conn.commit()
    conn.close()

    store = Store(tmp_path)
    job = store.create_job("https://example.com", "{}")
    store.set_job_change(job["id"], "minor", "prev")
    assert store.get_job(job["id"])["change_level"] == "minor"


# ----------------------------------------------------------------- arayüzler


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    from webdamga import api

    importlib.reload(api)
    return TestClient(api.app), api


def test_api_monitor_lifecycle(client) -> None:
    http, _ = client
    created = http.post(
        "/api/monitors", json={"url": "example.com", "interval_minutes": 15, "label": "x", "route": "tor"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["enabled"] is True and body["settings"]["proxy_profile"] == "tor"
    mid = body["id"]

    assert http.post(f"/api/monitors/{mid}/run").json()["monitor_id"] == mid
    assert len(http.get(f"/api/monitors/{mid}").json()["runs"]) == 1
    assert http.patch(f"/api/monitors/{mid}", json={"enabled": False}).json()["enabled"] is False
    assert http.patch(f"/api/monitors/{mid}", json={"interval_minutes": 1}).status_code == 422
    assert [m["id"] for m in http.get("/api/monitors").json()] == [mid]
    assert http.delete(f"/api/monitors/{mid}").status_code == 204
    assert http.get(f"/api/monitors/{mid}").status_code == 404


def test_api_rejects_bad_monitors(client) -> None:
    http, _ = client
    assert http.post("/api/monitors", json={"url": "example.com", "interval_minutes": 1}).status_code == 422
    assert http.post("/api/monitors", json={"url": "example.com", "route": "mars"}).status_code == 422


def test_web_monitor_pages_and_actions(client) -> None:
    http, api = client
    response = http.post(
        "/monitors", data={"url": "example.com", "interval": "60", "label": "Banka"}, follow_redirects=False
    )
    assert response.status_code == 303
    location = response.headers["location"]
    mid = int(location.rsplit("/", 1)[1])

    assert "Banka" in http.get("/monitors?lang=en").text
    detail = http.get(f"{location}?lang=en")
    assert detail.status_code == 200 and "Banka" in detail.text
    assert http.post(f"/monitors/{mid}/run", follow_redirects=False).status_code == 303
    assert "queued" in http.get(f"{location}?lang=en").text

    http.post(f"/monitors/{mid}/pause")
    assert api._store.get_monitor(mid)["enabled"] == 0
    http.post(f"/monitors/{mid}/resume")
    assert api._store.get_monitor(mid)["enabled"] == 1
    assert http.post(f"/monitors/{mid}/explode").status_code == 404
    assert http.post(f"/monitors/{mid}/delete", follow_redirects=False).headers["location"] == "/monitors"
    assert api._store.get_monitor(mid) is None


def test_navigation_links_to_monitors(client) -> None:
    http, _ = client
    assert 'href="/monitors"' in http.get("/?lang=en").text


def test_cli_monitor_commands(tmp_path: Path) -> None:
    from webdamga.cli import app

    runner = CliRunner()
    base = ["--data-dir", str(tmp_path)]
    added = runner.invoke(app, ["monitor", "add", "example.com", "--every", "30", "--label", "Banka", *base])
    assert added.exit_code == 0, added.output

    listed = runner.invoke(app, ["monitor", "list", *base])
    assert "Banka" in listed.output

    assert runner.invoke(app, ["monitor", "pause", "1", *base]).exit_code == 0
    assert Store(tmp_path).get_monitor(1)["enabled"] == 0
    assert runner.invoke(app, ["monitor", "resume", "1", *base]).exit_code == 0
    assert runner.invoke(app, ["monitor", "add", "example.com", "--every", "1", *base]).exit_code == 2
    assert runner.invoke(app, ["monitor", "add", "example.com", "--tor", "--via", "de", *base]).exit_code == 2
    assert runner.invoke(app, ["monitor", "remove", "1", *base]).exit_code == 0
    assert runner.invoke(app, ["monitor", "remove", "1", *base]).exit_code == 1
