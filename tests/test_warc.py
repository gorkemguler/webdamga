"""WARC çıktısı: biçim, digest'ler, başlık uyarlaması ve gövde sadakati."""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
import os
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from warcio.archiveiterator import ArchiveIterator

from webdamga.warc import Exchange, ResponseRecorder, exchanges_from_har, write_warc

META = {
    "capture_id": "20260101T000000Z-example-com-abc123",
    "requested_url": "https://example.com/",
    "final_url": "https://example.com/",
    "requested_at_utc": "2026-01-01T00:00:00Z",
    "completed_at_utc": "2026-01-01T00:00:05Z",
}

# windows-1254 ile kodlanmış, UTF-8 olarak geçersiz baytlar içeren bir gövde.
TURKISH = "<html><title>Şifre güncelleme</title><h1>ğüşiöç ĞÜŞİÖÇ</h1></html>".encode("windows-1254")


def _exchange(**overrides) -> Exchange:
    base = {
        "url": "https://example.com/",
        "method": "GET",
        "request_headers": [(":authority", "example.com"), ("user-agent", "test")],
        "request_body": None,
        "status": 200,
        "status_text": "",
        "response_headers": [
            ("content-type", "text/html; charset=windows-1254"),
            ("content-encoding", "br"),
            ("content-length", "31"),
            ("set-cookie", "a=1"),
            ("set-cookie", "b=2"),
        ],
        "body": TURKISH,
        "started": datetime(2026, 1, 1, 0, 0, 1, 250_000, tzinfo=UTC),
        "server_ip": "93.184.216.34",
    }
    base.update(overrides)
    return Exchange(**base)


def _records(path: Path) -> list:
    out = []
    with path.open("rb") as fh:
        for record in ArchiveIterator(fh, check_digests=True):
            payload = record.content_stream().read()
            out.append((record, payload))
    return out


def test_warc_parses_and_every_digest_verifies(tmp_path: Path) -> None:
    exchanges = [_exchange(), _exchange(url="https://example.com/app.js", body=b"console.log(1)")]
    summary = write_warc(tmp_path / "a.warc.gz", exchanges, meta=META)

    records = _records(tmp_path / "a.warc.gz")
    types = [r.rec_type for r, _ in records]
    assert types == ["warcinfo", "response", "request", "response", "request"]
    assert summary == {
        "file": "a.warc.gz",
        "records": 5,
        "response": 2,
        "request": 2,
        "resource": 0,
        "truncated": 0,
    }
    for record, _ in records:
        assert record.rec_headers.get_header("WARC-Record-ID")
        # warcio digest'leri gerçekten okuyup karşılaştırdı mı?
        assert record.digest_checker.passed is not False, record.digest_checker.problems


def test_each_record_is_a_separate_gzip_member(tmp_path: Path) -> None:
    write_warc(tmp_path / "a.warc.gz", [_exchange()], meta=META)
    raw = (tmp_path / "a.warc.gz").read_bytes()
    # 3 kayıt (warcinfo, response, request) = 3 gzip üyesi.
    assert raw.count(b"\x1f\x8b\x08") >= 3
    assert gzip.decompress(raw).startswith(b"WARC/1.1\r\n")


def test_payload_keeps_original_bytes(tmp_path: Path) -> None:
    write_warc(tmp_path / "a.warc.gz", [_exchange()], meta=META)
    (_, _), (_, payload), *_ = _records(tmp_path / "a.warc.gz")
    assert payload == TURKISH


def test_decoded_body_headers_are_rewritten_for_replay(tmp_path: Path) -> None:
    write_warc(tmp_path / "a.warc.gz", [_exchange()], meta=META)
    response = _records(tmp_path / "a.warc.gz")[1][0]
    h = response.http_headers

    assert h.get_statuscode() == "200"
    assert h.protocol == "HTTP/1.1"
    assert h.get_header("Content-Encoding") is None
    assert h.get_header("X-Archive-Orig-Content-Encoding") == "br"
    assert h.get_header("Content-Length") == str(len(TURKISH))
    assert h.get_header("Content-Type") == "text/html; charset=windows-1254"
    # Tekrarlanan başlıklar (set-cookie) korunmalı.
    assert [v for k, v in h.headers if k.lower() == "set-cookie"] == ["a=1", "b=2"]


def test_status_line_gets_reason_phrase_for_http2(tmp_path: Path) -> None:
    write_warc(tmp_path / "a.warc.gz", [_exchange(status=404, status_text="")], meta=META)
    assert _records(tmp_path / "a.warc.gz")[1][0].http_headers.statusline == "404 Not Found"


def test_request_record_is_linked_and_well_formed(tmp_path: Path) -> None:
    ex = _exchange(
        url="https://example.com/login?next=%2F",
        method="POST",
        request_body=b"user=a&pass=b",
    )
    write_warc(tmp_path / "a.warc.gz", [ex], meta=META)
    _, (response, _), (request, body) = _records(tmp_path / "a.warc.gz")

    assert request.rec_headers.get_header("WARC-Concurrent-To") == response.rec_headers.get_header(
        "WARC-Record-ID"
    )
    assert request.http_headers.protocol == "POST"
    assert request.http_headers.statusline == "/login?next=%2F HTTP/1.1"
    assert request.http_headers.get_header("Host") == "example.com"
    assert not any(k.startswith(":") for k, _ in request.http_headers.headers)
    assert body == b"user=a&pass=b"


def test_warc_metadata_headers(tmp_path: Path) -> None:
    write_warc(tmp_path / "a.warc.gz", [_exchange()], meta=META)
    (info, fields), (response, _), _ = _records(tmp_path / "a.warc.gz")

    assert b"software: webdamga/" in fields
    assert META["capture_id"].encode() in fields
    assert response.rec_headers.get_header("WARC-Date") == "2026-01-01T00:00:01.250Z"
    assert response.rec_headers.get_header("WARC-IP-Address") == "93.184.216.34"
    assert response.rec_headers.get_header("WARC-Warcinfo-ID") == info.rec_headers.get_header(
        "WARC-Record-ID"
    )
    assert response.rec_headers.get_header("WARC-Payload-Digest").startswith("sha256:")


def test_records_are_ordered_by_start_time(tmp_path: Path) -> None:
    late = _exchange(url="https://example.com/late", started=datetime(2026, 1, 1, 0, 0, 9, tzinfo=UTC))
    early = _exchange(url="https://example.com/early", started=datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC))
    write_warc(tmp_path / "a.warc.gz", [late, early], meta=META)
    uris = [
        r.rec_headers.get_header("WARC-Target-URI")
        for r, _ in _records(tmp_path / "a.warc.gz")
        if r.rec_type == "response"
    ]
    assert uris == ["https://example.com/early", "https://example.com/late"]


def test_output_is_reproducible(tmp_path: Path) -> None:
    # WARC-Filename başlığı dosya adını taşıdığı için aynı adla iki ayrı klasöre yazılıyor.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    write_warc(tmp_path / "a" / "x.warc.gz", [_exchange()], meta=META)
    write_warc(tmp_path / "b" / "x.warc.gz", [_exchange()], meta=META)
    assert (tmp_path / "a" / "x.warc.gz").read_bytes() == (tmp_path / "b" / "x.warc.gz").read_bytes()


def test_screenshots_become_resource_records(tmp_path: Path) -> None:
    (tmp_path / "screenshot.png").write_bytes(b"\x89PNG full")
    (tmp_path / "screenshot-viewport.png").write_bytes(b"\x89PNG view")
    summary = write_warc(tmp_path / "a.warc.gz", [_exchange()], meta=META, capture_dir=tmp_path)

    resources = {
        r.rec_headers.get_header("WARC-Target-URI"): payload
        for r, payload in _records(tmp_path / "a.warc.gz")
        if r.rec_type == "resource"
    }
    assert resources == {
        "urn:view:https://example.com/": b"\x89PNG view",
        "urn:fullPage:https://example.com/": b"\x89PNG full",
    }
    assert summary["resource"] == 2


def test_truncated_and_fallback_bodies_are_flagged(tmp_path: Path) -> None:
    ex = _exchange(truncated=True, body_source="browser-decoded")
    summary = write_warc(tmp_path / "a.warc.gz", [ex], meta=META)
    response = _records(tmp_path / "a.warc.gz")[1][0]
    assert response.rec_headers.get_header("WARC-Truncated") == "length"
    assert response.rec_headers.get_header("WebDamga-Body-Source") == "browser-decoded"
    assert summary["truncated"] == 1


def test_raw_bodies_are_not_flagged(tmp_path: Path) -> None:
    write_warc(tmp_path / "a.warc.gz", [_exchange()], meta=META)
    assert _records(tmp_path / "a.warc.gz")[1][0].rec_headers.get_header("WebDamga-Body-Source") is None


def test_header_injection_is_neutralised(tmp_path: Path) -> None:
    ex = _exchange(response_headers=[("x-evil", "a\r\nWARC-Type: revisit")])
    write_warc(tmp_path / "a.warc.gz", [ex], meta=META)
    records = _records(tmp_path / "a.warc.gz")
    assert [r.rec_type for r, _ in records] == ["warcinfo", "response", "request"]


# --------------------------------------------------------------- HAR fallback


def test_exchanges_from_har_marks_lossy_text(tmp_path: Path) -> None:
    har = {
        "log": {
            "entries": [
                {
                    "startedDateTime": "2026-01-01T00:00:01.000Z",
                    "serverIPAddress": "[2606:4700::1]",
                    "request": {"method": "GET", "url": "https://example.com/", "headers": []},
                    "response": {
                        "status": 200,
                        "statusText": "OK",
                        "headers": [{"name": "content-type", "value": "text/html"}],
                        "content": {"text": "<html>é</html>"},
                    },
                },
                {
                    "startedDateTime": "2026-01-01T00:00:02.000Z",
                    "request": {"method": "GET", "url": "https://example.com/x.png", "headers": []},
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {"text": base64.b64encode(b"\x89PNG").decode(), "encoding": "base64"},
                    },
                },
                {
                    "startedDateTime": "2026-01-01T00:00:03.000Z",
                    "request": {"method": "GET", "url": "data:text/plain,hi", "headers": []},
                    "response": {"status": 200, "headers": [], "content": {}},
                },
            ]
        }
    }
    (tmp_path / "network.har").write_text(json.dumps(har))
    exchanges = exchanges_from_har(tmp_path / "network.har")

    assert [ex.url for ex in exchanges] == ["https://example.com/", "https://example.com/x.png"]
    assert exchanges[0].body_source == "har-text"
    assert exchanges[0].server_ip == "2606:4700::1"
    assert exchanges[1].body == b"\x89PNG"
    assert exchanges[1].body_source == "har-base64"


# ------------------------------------------------------------ recorder join


class _FakeRequest:
    def __init__(self, url: str, method: str = "GET", resource_type: str = "document") -> None:
        self.url, self.method, self.resource_type = url, method, resource_type
        self.post_data_buffer = None
        self.timing = {"startTime": 1_767_225_601_000}

    async def headers_array(self):
        return [{"name": "user-agent", "value": "test"}]


class _FakeResponse:
    def __init__(self, url: str, body: bytes, status: int = 200, **req) -> None:
        self.url, self._body, self.status, self.status_text = url, body, status, ""
        self.request = _FakeRequest(url, **req)

    async def headers_array(self):
        return [{"name": "content-type", "value": "text/html"}]

    async def server_addr(self):
        return {"ipAddress": "[::1]", "port": 443}

    async def body(self):
        return self._body


def test_recorder_prefers_raw_cdp_body_and_falls_back_to_browser_body() -> None:
    async def scenario():
        recorder = ResponseRecorder()
        recorder._on_response(_FakeResponse("https://a.example/", b"decoded-by-browser"))
        recorder._on_response(
            _FakeResponse("https://b.example/", b"iframe-body", resource_type="subdocument")
        )
        recorder._raw[("GET", "https://a.example/")].append(b"raw-bytes")
        await recorder.drain()
        return recorder

    recorder = asyncio.run(scenario())
    by_url = {ex.url: ex for ex in recorder.exchanges}
    assert (by_url["https://a.example/"].body, by_url["https://a.example/"].body_source) == (
        b"raw-bytes",
        "raw",
    )
    assert by_url["https://b.example/"].body_source == "browser-decoded"
    assert by_url["https://a.example/"].server_ip == "::1"
    assert recorder.main_document("https://a.example/") is by_url["https://a.example/"]
    assert recorder.main_document("https://b.example/") is None  # belge değil


def test_recorder_matches_repeated_urls_in_order() -> None:
    async def scenario():
        recorder = ResponseRecorder()
        first, second = _FakeResponse("https://a.example/", b"x"), _FakeResponse("https://a.example/", b"y")
        second.request.timing = {"startTime": first.request.timing["startTime"] + 5}
        recorder._on_response(first)
        recorder._on_response(second)
        recorder._raw[("GET", "https://a.example/")].extend([b"raw-1", b"raw-2"])
        await recorder.drain()
        return recorder

    assert [ex.body for ex in asyncio.run(scenario()).exchanges] == [b"raw-1", b"raw-2"]


def test_recorder_caps_body_size() -> None:
    async def scenario():
        recorder = ResponseRecorder(max_body=4)
        recorder._on_response(_FakeResponse("https://a.example/", b"0123456789"))
        await recorder.drain()
        return recorder

    (ex,) = asyncio.run(scenario()).exchanges
    assert ex.body == b"0123"
    assert ex.truncated is True


def test_recorder_skips_non_http_urls() -> None:
    async def scenario():
        recorder = ResponseRecorder()
        recorder._on_response(_FakeResponse("data:text/plain,hi", b"hi"))
        await recorder.drain()
        return recorder

    assert asyncio.run(scenario()).exchanges == []


# --------------------------------------------------------------- integration


@pytest.mark.skipif(not os.environ.get("WEBDAMGA_INTEGRATION"), reason="needs Chromium")
def test_non_utf8_gzip_page_is_archived_byte_for_byte(tmp_path: Path) -> None:
    """HAR ve Playwright'in body()'si bu sayfanın baytlarını değiştirir; WARC ve response.html değiştirmemeli."""
    from webdamga.capture import capture
    from webdamga.config import CaptureSettings

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            packed = gzip.compress(TURKISH)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=windows-1254")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(packed)))
            self.end_headers()
            self.wfile.write(packed)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        meta = asyncio.run(capture(url, tmp_path, CaptureSettings(pdf=False)))
    finally:
        server.shutdown()

    folder = Path(meta["dir"])
    assert meta["ok"], meta.get("error")
    assert meta["page_title"] == "Şifre güncelleme"
    assert (folder / "response.html").read_bytes() == TURKISH
    assert meta["response_body_source"] == "raw"

    responses = [
        (r, p)
        for r, p in _records(folder / "archive.warc.gz")
        if r.rec_type == "response" and r.rec_headers.get_header("WARC-Target-URI") == url
    ]
    ((record, payload),) = responses
    assert payload == TURKISH
    assert record.http_headers.get_header("X-Archive-Orig-Content-Encoding") == "gzip"
    assert record.digest_checker.passed is not False
