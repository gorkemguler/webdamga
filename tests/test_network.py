"""Proxy / Tor ağ yolu."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webdamga.capture import capture
from webdamga.config import CaptureSettings
from webdamga.network import (
    TOR_PROFILE,
    TOR_PROXY,
    ProxyError,
    ensure_reachable,
    load_profiles,
    parse_egress,
    parse_proxy,
    redact_proxy,
    resolve_route,
)


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("raw", "server"),
    [
        ("socks5://127.0.0.1:9050", "socks5://127.0.0.1:9050"),
        ("socks5h://127.0.0.1:9050", "socks5://127.0.0.1:9050"),
        ("SOCKS5://Example.com:1080", "socks5://example.com:1080"),
        ("http://proxy.local", "http://proxy.local:80"),
        ("https://proxy.local", "https://proxy.local:443"),
        ("http://[::1]:3128", "http://[::1]:3128"),
    ],
)
def test_parse_proxy(raw: str, server: str) -> None:
    assert parse_proxy(raw).server == server


def test_parse_proxy_keeps_http_credentials_for_playwright() -> None:
    config = parse_proxy("http://user%40corp:p%3Ass@proxy.local:3128")
    assert config.playwright() == {
        "server": "http://proxy.local:3128",
        "username": "user@corp",
        "password": "p:ss",
    }


@pytest.mark.parametrize(
    "raw",
    ["", "127.0.0.1:9050", "ftp://proxy.local", "http://", "http://proxy.local:notaport"],
)
def test_parse_proxy_rejects_bad_addresses(raw: str) -> None:
    with pytest.raises(ProxyError):
        parse_proxy(raw)


def test_authenticated_socks_is_rejected_instead_of_silently_ignored() -> None:
    with pytest.raises(ProxyError, match="SOCKS"):
        parse_proxy("socks5://user:pass@127.0.0.1:1080")


def test_redact_proxy_strips_credentials() -> None:
    assert redact_proxy("http://alice:hunter2@proxy.local:3128") == "http://proxy.local:3128"
    assert redact_proxy(None) is None
    assert "hunter2" not in redact_proxy("http://alice:hunter2@")


# ------------------------------------------------------------------ profiles


def test_tor_profile_is_always_available(tmp_path: Path) -> None:
    assert load_profiles(tmp_path) == {TOR_PROFILE: TOR_PROXY}


def test_profiles_are_loaded_from_data_dir(tmp_path: Path) -> None:
    (tmp_path / "proxies.json").write_text(json.dumps({"de": "socks5://10.0.0.2:1080"}))
    assert load_profiles(tmp_path)["de"] == "socks5://10.0.0.2:1080"


@pytest.mark.parametrize(
    "content",
    ["{not json", '["a list"]', '{"de": 5}', '{"de": "ftp://nope"}'],
)
def test_broken_profiles_file_fails_loudly(tmp_path: Path, content: str) -> None:
    (tmp_path / "proxies.json").write_text(content)
    with pytest.raises(ProxyError):
        load_profiles(tmp_path)


def test_resolve_route(tmp_path: Path) -> None:
    (tmp_path / "proxies.json").write_text(json.dumps({"de": "http://10.0.0.2:3128"}))

    assert resolve_route(None, None, tmp_path).describe() == {
        "mode": "direct",
        "profile": None,
        "proxy": None,
    }
    assert resolve_route(None, "tor", tmp_path).mode == "tor"
    assert resolve_route(TOR_PROXY, None, tmp_path).mode == "tor"

    route = resolve_route(None, "de", tmp_path)
    assert (route.mode, route.profile, route.proxy.server) == ("proxy", "de", "http://10.0.0.2:3128")

    with pytest.raises(ProxyError, match="unknown proxy profile"):
        resolve_route(None, "mars", tmp_path)
    with pytest.raises(ProxyError, match="either"):
        resolve_route("http://a:1", "de", tmp_path)


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


@pytest.mark.skipif(_port_open(9050), reason="tor is actually running on this machine")
def test_ensure_reachable_explains_missing_tor() -> None:
    with pytest.raises(ProxyError, match="is tor running"):
        ensure_reachable(parse_proxy(TOR_PROXY), timeout=0.5)


def test_ensure_reachable_on_closed_port() -> None:
    with pytest.raises(ProxyError, match="not reachable"):
        ensure_reachable(parse_proxy(f"http://127.0.0.1:{_closed_port()}"), timeout=0.5)


def test_parse_egress() -> None:
    assert parse_egress('{"IsTor": true, "IP": "185.220.101.1"}') == {
        "ip": "185.220.101.1",
        "is_tor": True,
        "source": "https://check.torproject.org/api/ip",
    }


# ------------------------------------------------------------------- capture


def test_unreachable_proxy_finalizes_evidence_without_leaking_credentials(tmp_path: Path) -> None:
    settings = CaptureSettings(proxy=f"http://alice:hunter2@127.0.0.1:{_closed_port()}")
    meta = asyncio.run(capture("https://example.com", tmp_path, settings))

    assert meta["ok"] is False
    assert meta["error"].startswith("network:")
    assert meta["network"]["proxy"].startswith("http://127.0.0.1:")

    folder = Path(meta["dir"])
    assert (folder / "manifest.json").is_file()  # yine de mühürlendi
    for path in folder.iterdir():
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "hunter2" not in text and "alice" not in text, path.name


def test_unknown_profile_is_recorded_as_network_error(tmp_path: Path) -> None:
    meta = asyncio.run(capture("https://example.com", tmp_path, CaptureSettings(proxy_profile="mars")))
    assert meta["ok"] is False
    assert "unknown proxy profile" in meta["error"]
    assert meta["network"]["mode"] == "unavailable"


# ----------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    (tmp_path / "proxies.json").write_text(json.dumps({"de": "http://10.0.0.2:3128"}))
    from webdamga import api

    importlib.reload(api)
    return TestClient(api.app), api


def test_form_offers_known_routes(client) -> None:
    http, _ = client
    page = http.get("/?lang=en").text
    assert '<option value="tor">' in page
    assert '<option value="de">' in page


def test_form_and_api_accept_known_route(client) -> None:
    http, api = client
    response = http.post("/captures", data={"url": "example.com", "route": "tor"}, follow_redirects=False)
    job_id = response.headers["location"].rsplit("/", 1)[1]
    assert json.loads(api._store.get_job(job_id)["settings_json"])["proxy_profile"] == "tor"

    body = http.post("/api/jobs", json={"url": "example.com", "route": "de", "record_egress": True}).json()
    assert body["settings"]["proxy_profile"] == "de"
    assert body["settings"]["record_egress"] is True
    assert http.get("/api/routes").json() == ["de", "tor"]


def test_unknown_route_is_rejected(client) -> None:
    http, _ = client
    assert http.post("/captures", data={"url": "example.com", "route": "mars"}).status_code == 422
    assert http.post("/api/jobs", json={"url": "example.com", "route": "mars"}).status_code == 422


def test_raw_proxy_address_is_not_accepted_from_the_web(client) -> None:
    http, _ = client
    body = {"url": "example.com", "route": "http://evil.example:8080"}
    assert http.post("/api/jobs", json=body).status_code == 422


def test_detail_page_renders_capture_that_never_reached_a_browser(client) -> None:
    http, api = client
    meta = asyncio.run(capture("https://example.com", api.DATA_DIR, CaptureSettings(proxy_profile="mars")))
    page = http.get(f"/captures/{meta['capture_id']}?lang=en")
    assert page.status_code == 200
    assert "unknown proxy profile" in page.text


# --------------------------------------------------------------- integration


@pytest.mark.skipif(not os.environ.get("WEBDAMGA_INTEGRATION"), reason="needs network and Chromium")
def test_capture_really_goes_through_the_proxy(tmp_path: Path) -> None:
    from proxy_server import RecordingProxy

    with RecordingProxy() as proxy:
        settings = CaptureSettings(proxy=proxy.url, record_egress=True, pdf=False)
        meta = asyncio.run(capture("https://example.com", tmp_path, settings))

    assert meta["ok"], meta.get("error")
    assert "example.com:443" in proxy.targets
    assert "check.torproject.org:443" in proxy.targets  # çıkış kontrolü de aynı yoldan
    assert meta["network"]["egress"]["ip"]
