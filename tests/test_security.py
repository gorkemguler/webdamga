"""Güvenlik: şema kısıtı, CSRF, DNS rebinding, yakalanan içeriğin sunumu."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webdamga.capture import capture
from webdamga.config import CaptureSettings
from webdamga.security import (
    UrlNotAllowed,
    artifact_headers,
    host_is_allowed,
    origin_is_allowed,
    safe_download_name,
    validate_capture_url,
)

# ------------------------------------------------------------------- şema


@pytest.mark.parametrize("url", ["https://example.com", "http://example.com/a?b=1", "https://[::1]:8443/x"])
def test_http_urls_are_allowed(url: str) -> None:
    assert validate_capture_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file:///Users/me/.ssh/id_rsa",
        "chrome://settings",
        "javascript:alert(1)",
        "data:text/html,<script>x</script>",
        "ftp://host/f",
        "https://",
    ],
)
def test_dangerous_schemes_are_rejected(url: str) -> None:
    with pytest.raises(UrlNotAllowed):
        validate_capture_url(url)


def test_capture_refuses_local_files_without_opening_a_browser(tmp_path: Path) -> None:
    meta = asyncio.run(capture("file:///etc/hosts", tmp_path, CaptureSettings()))
    assert meta["ok"] is False
    assert "only http and https" in meta["error"]
    # Tarayıcı hiç açılmamalı, dolayısıyla dom.html üretilmemeli.
    assert not (Path(meta["dir"]) / "dom.html").exists()
    assert "browser" not in meta
    # Başarısız da olsa klasör mühürlenmeli (delil zinciri korunur).
    assert (Path(meta["dir"]) / "manifest.json").is_file()


def test_capture_folder_never_contains_the_local_file_content(tmp_path: Path) -> None:
    meta = asyncio.run(capture("file:///etc/hosts", tmp_path, CaptureSettings()))
    for path in Path(meta["dir"]).iterdir():
        assert "localhost" not in path.read_text(encoding="utf-8", errors="ignore")


# --------------------------------------------------------------- host / CSRF


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000", "127.0.0.1"])
def test_loopback_hosts_are_allowed(host: str) -> None:
    assert host_is_allowed(host, ("localhost", "127.0.0.1", "[::1]", "::1"))


@pytest.mark.parametrize("host", ["attacker.example", "evil.example:8000", None, ""])
def test_foreign_hosts_are_rejected(host) -> None:
    assert not host_is_allowed(host, ("localhost", "127.0.0.1", "[::1]", "::1"))


def test_configured_host_is_allowed() -> None:
    assert host_is_allowed("tools.internal:8000", ("localhost", "tools.internal"))


def test_origin_check() -> None:
    allowed = ("localhost", "127.0.0.1", "[::1]", "::1")
    assert origin_is_allowed("http://localhost:8000", None, allowed)
    assert origin_is_allowed("http://127.0.0.1:8000", None, allowed)
    assert not origin_is_allowed("https://attacker.example", None, allowed)
    assert not origin_is_allowed("null", None, allowed)  # sandboxed iframe
    # Origin/Referer yoksa istek tarayıcı formundan gelmemiştir (curl): serbest.
    assert origin_is_allowed(None, None, allowed)
    # Origin yoksa Referer'a bakılır.
    assert not origin_is_allowed(None, "https://attacker.example/x", allowed)


# --------------------------------------------------------- artefakt başlıkları


@pytest.mark.parametrize("name", ["dom.html", "page.mhtml", "response.html", "x.svg"])
def test_active_artifacts_are_downloaded_with_sandbox(name: str) -> None:
    inline, headers = artifact_headers(name)
    assert inline is False
    assert "sandbox" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("name", ["screenshot.png", "page.pdf", "metadata.json"])
def test_passive_artifacts_may_render_inline(name: str) -> None:
    inline, headers = artifact_headers(name)
    assert inline is True
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_safe_download_name() -> None:
    assert safe_download_name('a"b\r\nContent-Type: x') == "a_b__Content-Type__x"
    assert safe_download_name("dom.html") == "dom.html"


# --------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    from webdamga import api

    importlib.reload(api)
    return TestClient(api.app), api


def _seal(api, name: str, files: dict[str, str]) -> None:
    from webdamga.seal import seal_capture

    cap = api.DATA_DIR / "captures" / name
    cap.mkdir(parents=True)
    for filename, content in files.items():
        (cap / filename).write_text(content, encoding="utf-8")
    (cap / "metadata.json").write_text(json.dumps({"capture_id": name}))
    seal_capture(cap, {"capture_id": name}, None)


def test_captured_html_is_served_as_a_sandboxed_download(client) -> None:
    http, api = client
    _seal(api, "evil", {"dom.html": "<script>fetch('/api/monitors')</script>"})
    r = http.get("/captures/evil/files/dom.html")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    # text/html olarak servis edilmemeli.
    assert "text/html" not in r.headers["content-type"]


def test_screenshot_still_renders_inline(client) -> None:
    http, api = client
    _seal(api, "shot", {"screenshot.png": "\x89PNG"})
    r = http.get("/captures/shot/files/screenshot.png")
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["content-type"] == "image/png"


def test_api_rejects_dangerous_capture_urls(client) -> None:
    http, _ = client
    assert http.post("/api/jobs", json={"url": "file:///etc/passwd"}).status_code == 422
    assert http.post("/api/jobs", json={"url": "chrome://settings"}).status_code == 422
    assert http.post("/captures", data={"url": "file:///etc/passwd"}).status_code == 422
    assert http.post("/api/monitors", json={"url": "file:///etc/passwd"}).status_code == 422


def test_cross_origin_post_is_refused(client) -> None:
    http, api = client
    api.add_monitor(api._store, "https://example.com", 60)
    mid = api._store.list_monitors()[0]["id"]

    blocked = http.post(
        f"/monitors/{mid}/delete",
        headers={"Origin": "https://attacker.example"},
        follow_redirects=False,
    )
    assert blocked.status_code == 403
    assert api._store.get_monitor(mid) is not None  # silinmedi

    started = http.post(
        "/captures", data={"url": "https://example.com"}, headers={"Origin": "https://attacker.example"}
    )
    assert started.status_code == 403


def test_same_origin_post_is_allowed(client) -> None:
    http, _ = client
    r = http.post(
        "/captures",
        data={"url": "https://example.com"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_get_requests_are_not_csrf_checked(client) -> None:
    http, _ = client
    # GET durum değiştirmez; başka origin'den gelse de okunabilir.
    r = http.get("/api/captures", headers={"Origin": "https://attacker.example"})
    assert r.status_code == 200


def test_unknown_host_is_refused(client) -> None:
    http, _ = client
    assert http.get("/", headers={"Host": "attacker.example"}).status_code == 421
    assert http.get("/", headers={"Host": "127.0.0.1:8000"}).status_code == 200


def test_extra_allowed_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WEBDAMGA_ALLOWED_HOSTS", "tools.internal")
    from webdamga import api

    importlib.reload(api)
    http = TestClient(api.app)
    assert http.get("/", headers={"Host": "tools.internal"}).status_code == 200
    assert http.get("/", headers={"Host": "elsewhere.example"}).status_code == 421
