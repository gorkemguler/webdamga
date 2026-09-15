"""Cihaz, referer ve dil taklidi."""

from __future__ import annotations

import typing

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webdamga.config import CaptureSettings
from webdamga.devices import FEATURED, Device, known_device_names, resolve_device


class _FakePlaywright:
    """Playwright'in pw.devices sözlüğünü taklit eder."""

    devices: typing.ClassVar[dict] = {
        "iPhone 15": {
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari",
            "viewport": {"width": 393, "height": 659},
            "device_scale_factor": 3,
            "is_mobile": True,
            "has_touch": True,
        },
        "Desktop Chrome": {
            "user_agent": "Mozilla/5.0 (Macintosh) Chrome",
            "viewport": {"width": 1280, "height": 720},
            "device_scale_factor": 1,
            "is_mobile": False,
            "has_touch": False,
        },
    }


def test_resolve_device_returns_full_profile() -> None:
    device = resolve_device(_FakePlaywright(), "iPhone 15")
    assert device.name == "iPhone 15"
    assert device.is_mobile and device.has_touch
    assert device.viewport == {"width": 393, "height": 659}
    opts = device.context_options()
    assert opts["is_mobile"] is True
    assert "iPhone" in opts["user_agent"]
    # Çağıran viewport'u değiştirse orijinali bozulmamalı.
    opts["viewport"]["width"] = 1
    assert device.viewport["width"] == 393


@pytest.mark.parametrize("name", ["iPhone 15", "iphone 15", "IPHONE15", "iphone-15"])
def test_device_lookup_is_forgiving(name: str) -> None:
    assert resolve_device(_FakePlaywright(), name).name == "iPhone 15"


def test_unknown_device_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        resolve_device(_FakePlaywright(), "Nokia 3310")


def test_known_device_names_sorted() -> None:
    assert known_device_names(_FakePlaywright()) == ["Desktop Chrome", "iPhone 15"]


def test_featured_devices_are_nonempty_strings() -> None:
    assert FEATURED and all(isinstance(name, str) for name in FEATURED)


def test_settings_round_trip_keeps_new_fields() -> None:
    original = CaptureSettings(device="iPhone 15", referer="https://t.co/x", accept_language="tr-TR,tr;q=0.9")
    restored = CaptureSettings.from_storage(json.loads(json.dumps(original.to_storage())))
    assert restored == original
    shown = original.as_dict()
    assert shown["device"] == "iPhone 15"
    assert shown["referer"] == "https://t.co/x"
    assert shown["accept_language"] == "tr-TR,tr;q=0.9"


def test_device_dataclass_is_frozen() -> None:
    device = Device("x", "ua", {"width": 1, "height": 1}, 1, False, False)
    with pytest.raises(AttributeError):
        device.name = "y"  # type: ignore[misc]


# --------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    from webdamga import api

    importlib.reload(api)
    return TestClient(api.app), api


def test_form_carries_device_referer_language_into_settings(client) -> None:
    http, api = client
    response = http.post(
        "/captures",
        data={
            "url": "example.com",
            "device": "iPhone 15",
            "referer": "https://t.co/abc",
            "accept_language": "tr-TR,tr;q=0.9",
        },
        follow_redirects=False,
    )
    job_id = response.headers["location"].rsplit("/", 1)[1]
    settings = json.loads(api._store.get_job(job_id)["settings_json"])
    assert settings["device"] == "iPhone 15"
    assert settings["referer"] == "https://t.co/abc"
    assert settings["accept_language"] == "tr-TR,tr;q=0.9"


def test_blank_device_stays_none(client) -> None:
    http, api = client
    response = http.post("/captures", data={"url": "example.com", "device": ""}, follow_redirects=False)
    job_id = response.headers["location"].rsplit("/", 1)[1]
    assert json.loads(api._store.get_job(job_id)["settings_json"])["device"] is None


def test_api_job_accepts_device_fields(client) -> None:
    http, _ = client
    body = http.post(
        "/api/jobs", json={"url": "example.com", "device": "Pixel 7", "accept_language": "en-GB"}
    ).json()
    assert body["settings"]["device"] == "Pixel 7"
    assert body["settings"]["accept_language"] == "en-GB"


def test_devices_endpoint_and_form(client) -> None:
    http, _ = client
    assert http.get("/api/devices").json() == list(FEATURED)
    page = http.get("/?lang=en").text
    assert 'name="device"' in page
    assert "iPhone 15" in page
    assert 'name="referer"' in page
    assert 'name="accept_language"' in page


def test_monitor_can_carry_a_device(client) -> None:
    http, _ = client
    # Monitor API'si cihazı doğrudan almıyor; ama form yakalamalarında olduğu
    # gibi izleyici de sonraki turlarda ayarları taşımalı (route/timestamp).
    body = http.post("/api/monitors", json={"url": "example.com", "interval_minutes": 60}).json()
    assert body["settings"]["device"] is None  # varsayılan


# ------------------------------------------------------------- integration


@pytest.mark.skipif(
    not __import__("os").environ.get("WEBDAMGA_INTEGRATION"), reason="needs Chromium"
)
def test_real_device_emulation_changes_user_agent(tmp_path: Path) -> None:
    import asyncio
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from webdamga.capture import capture

    page = (
        "<!doctype html><title>t</title><script>addEventListener('DOMContentLoaded',"
        "()=>{document.title=JSON.stringify({ua:navigator.userAgent,lang:navigator.language,"
        "ref:document.referrer,touch:'ontouchstart' in window})})</script><body>x"
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        meta = asyncio.run(
            capture(
                url,
                tmp_path,
                CaptureSettings(
                    pdf=False,
                    warc=False,
                    device="iPhone 15",
                    accept_language="tr-TR,tr;q=0.9",
                    referer="https://t.co/abc",
                ),
            )
        )
    finally:
        server.shutdown()

    assert meta["ok"], meta.get("error")
    assert meta["emulated_device"] == "iPhone 15"
    info = json.loads(meta["page_title"])
    assert "iPhone" in info["ua"]
    assert info["lang"] == "tr-TR"
    assert info["ref"] == "https://t.co/abc"
    assert info["touch"] is True
