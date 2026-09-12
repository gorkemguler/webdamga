"""Güvenilir zaman damgası: RFC 3161 ve OpenTimestamps."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import webdamga.timestamp as ts
from webdamga.hashing import OTS_NAME, RFC3161_NAME, verify_capture
from webdamga.report import build_package, build_readme
from webdamga.seal import seal_capture

FIXTURES = Path(__file__).parent / "fixtures"
DATA = (FIXTURES / "ts-manifest.json").read_bytes()
DIGICERT = (FIXTURES / "digicert.tsr").read_bytes()
FREETSA = (FIXTURES / "freetsa.tsr").read_bytes()
REAL_OTS = (FIXTURES / "ts-manifest.json.ots").read_bytes()
FIXTURE_NONCE = 8211047024919109777  # sabit veriler bu nonce ile istendi


class _Server:
    """Verilen yanıtı döndüren küçük bir POST sunucusu."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body, self.status, self.received = body, status, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.received.append((self.path, self.headers.get("Content-Type"), self.rfile.read(length)))
                self.send_response(outer.status)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()


# ======================================================================= RFC 3161


def test_tsq_is_valid_der_with_nonce_and_cert_request() -> None:
    digest = hashlib.sha256(b"hello").digest()
    query = ts.build_tsq(digest, 123456789)
    (root,) = ts._der_parse_all(query)
    version, imprint, nonce, cert_req = root.children()
    assert version.as_int() == 1
    assert imprint.children()[1].value == digest
    assert nonce.as_int() == 123456789
    assert cert_req.value == b"\xff"


def test_tsq_encodes_high_bit_nonce_as_positive() -> None:
    query = ts.build_tsq(bytes(32), 0xFF)
    nonce = ts._der_parse_all(query)[0].children()[2]
    assert nonce.value == b"\x00\xff"
    assert nonce.as_int() == 255


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_openssl_accepts_our_request(tmp_path: Path) -> None:
    path = tmp_path / "q.tsq"
    path.write_bytes(ts.build_tsq(hashlib.sha256(b"x").digest(), 42))
    out = subprocess.run(
        ["openssl", "ts", "-query", "-in", str(path), "-text"], capture_output=True, text=True, check=False
    )
    assert "Hash Algorithm: sha256" in out.stdout
    assert "Nonce: 0x2A" in out.stdout


@pytest.mark.parametrize(
    ("token", "serial", "policy"),
    [
        (DIGICERT, "89b92226fb919c2a9d5fecae233d8726", "2.16.840.1.114412.7.1"),
        (FREETSA, "7f5c411", "1.2.3.4.1"),
    ],
)
def test_parses_real_tsa_tokens(token: bytes, serial: str, policy: str) -> None:
    info = ts.check_tsr(DATA, token, FIXTURE_NONCE)
    assert info["ok"], info.get("error")
    assert info["status"] == "granted"
    assert info["gen_time"] == "2026-09-12T21:52:15Z"
    assert info["serial"] == serial
    assert info["policy"] == policy
    assert info["imprint"] == hashlib.sha256(DATA).hexdigest()


def test_token_for_other_data_is_rejected() -> None:
    result = ts.check_tsr(b"something else", DIGICERT)
    assert not result["ok"]
    assert result["error"] == "token was issued for different data"


def test_replayed_token_fails_nonce_check() -> None:
    result = ts.check_tsr(DATA, DIGICERT, expected_nonce=1)
    assert not result["ok"]
    assert "nonce mismatch" in result["error"]


@pytest.mark.parametrize(
    "garbage",
    [b"", b"\x30", DIGICERT[:100], b"\x30\x80\x00\x00", b"not der at all"],
)
def test_malformed_tokens_raise(garbage: bytes) -> None:
    with pytest.raises(ts.TimestampError):
        ts.parse_tsr(garbage)
    assert ts.check_tsr(DATA, garbage)["ok"] is False


def test_rejected_status_is_reported() -> None:
    # PKIStatusInfo { status 2 (rejection) }, token yok.
    rejection = ts._tlv(0x30, ts._tlv(0x30, ts._der_uint(2)))
    info = ts.parse_tsr(rejection)
    assert info == {"status": "rejection", "granted": False}
    assert "did not grant" in ts.check_tsr(DATA, rejection)["error"]


def test_request_rfc3161_succeeds_against_a_tsa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ts.secrets, "randbits", lambda bits: FIXTURE_NONCE)
    with _Server(DIGICERT) as tsa:
        reply = ts.request_rfc3161(DATA, tsa.url)
    assert reply == DIGICERT
    (_, content_type, body) = tsa.received[0]
    assert content_type == "application/timestamp-query"
    assert body == ts.build_tsq(hashlib.sha256(DATA).digest(), FIXTURE_NONCE)


def test_request_rfc3161_refuses_a_response_to_someone_elses_request() -> None:
    """Rastgele nonce ile istenir; kayıtlı eski bir yanıt kabul edilmemeli."""
    with _Server(DIGICERT) as tsa, pytest.raises(ts.TimestampError, match="nonce mismatch"):
        ts.request_rfc3161(DATA, tsa.url)


def test_request_rfc3161_reports_unreachable_tsa() -> None:
    with pytest.raises(ts.TimestampError, match="unreachable"):
        ts.request_rfc3161(DATA, "http://127.0.0.1:1", timeout=2)


def test_openssl_verify_without_openssl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ts.shutil, "which", lambda name: None)
    result = ts.openssl_verify(tmp_path / "a", tmp_path / "b")
    assert result == {"verified": None, "detail": "openssl not found"}


@pytest.mark.skipif(
    not os.environ.get("WEBDAMGA_INTEGRATION"), reason="depends on current TSA certificate validity"
)
def test_openssl_verifies_real_digicert_token() -> None:
    result = ts.openssl_verify(FIXTURES / "ts-manifest.json", FIXTURES / "digicert.tsr")
    assert result["verified"] is True, result


# ================================================================== OpenTimestamps


def _pending(uri: str) -> bytes:
    payload = ts._varuint(len(uri)) + uri.encode()
    return b"\x00" + ts._PENDING_TAG + ts._varuint(len(payload)) + payload


@pytest.mark.parametrize("n", [0, 1, 127, 128, 300, 2**32])
def test_varuint_round_trip(n: int) -> None:
    value, end = ts._read_varuint(ts._varuint(n), 0)
    assert (value, end) == (n, len(ts._varuint(n)))


def test_parses_real_opentimestamps_proof() -> None:
    info = ts.check_ots(DATA, REAL_OTS)
    assert info["ok"], info.get("error")
    assert info["state"] == "pending"
    assert info["pending_calendars"] == [
        "https://alice.btc.calendar.opentimestamps.org",
        "https://bob.btc.calendar.opentimestamps.org",
    ]


def test_proof_for_other_data_is_rejected() -> None:
    assert ts.check_ots(b"else", REAL_OTS)["error"] == "proof was made for different data"


@pytest.mark.parametrize(
    "broken",
    [
        b"",
        b"not an ots file",
        REAL_OTS[:-5],
        REAL_OTS + b"\x00",
        ts.OTS_MAGIC + b"\x02" + b"\x08" + bytes(32),  # sürüm 2
        ts.OTS_MAGIC + b"\x01\x08" + bytes(32) + b"\x99",  # bilinmeyen işlem
    ],
)
def test_malformed_proofs_raise(broken: bytes) -> None:
    with pytest.raises(ts.TimestampError):
        ts.parse_ots(broken)


def test_bitcoin_attestation_is_recognised() -> None:
    payload = ts._varuint(912345)
    proof = (
        ts.OTS_MAGIC
        + b"\x01\x08"
        + bytes(32)
        + b"\x00"
        + ts._BITCOIN_TAG
        + ts._varuint(len(payload))
        + payload
    )
    info = ts.parse_ots(proof)
    assert info["attestations"] == [{"type": "bitcoin", "block_height": 912345}]


def test_stamp_ots_builds_one_branch_per_answering_calendar() -> None:
    digest = hashlib.sha256(DATA).digest()
    with _Server(_pending("https://alice.example")) as a, _Server(_pending("https://bob.example")) as b:
        proof, summary = ts.stamp_ots(digest, (a.url, b.url, "http://127.0.0.1:1"), timeout=2)

    assert summary["calendars"] == 2
    assert list(summary["failed"]) == ["http://127.0.0.1:1"]
    info = ts.check_ots(DATA, proof)
    assert info["ok"]
    assert sorted(info["pending_calendars"]) == ["https://alice.example", "https://bob.example"]

    # Takvimler dosya özetini değil, nonce eklenmiş özetin özetini görmeli.
    for server in (a, b):
        path, _, body = server.received[0]
        assert path == "/digest"
        assert body != digest and len(body) == 32


def test_stamp_ots_fails_when_no_calendar_answers() -> None:
    with pytest.raises(ts.TimestampError, match="no OpenTimestamps calendar answered"):
        ts.stamp_ots(bytes(32), ("http://127.0.0.1:1",), timeout=1)


@pytest.mark.skipif(
    not (os.environ.get("WEBDAMGA_INTEGRATION") and shutil.which("ots")), reason="needs the ots client"
)
def test_official_client_reads_our_proof(tmp_path: Path) -> None:
    (tmp_path / "m.json").write_bytes(DATA)
    (tmp_path / "m.json.ots").write_bytes(REAL_OTS)
    out = subprocess.run(
        ["ots", "info", str(tmp_path / "m.json.ots")], capture_output=True, text=True, check=False
    )
    assert "PendingAttestation" in out.stdout


# ===================================================================== yakalama


@pytest.fixture
def sealed(tmp_path: Path) -> Path:
    folder = tmp_path / "captures" / "cap-1"
    folder.mkdir(parents=True)
    (folder / "dom.html").write_text("<html></html>")
    seal_capture(folder, {"capture_id": "cap-1", "completed_at_utc": "2026-01-01T00:00:00Z"}, None)
    return folder


def _fake_timestamps(monkeypatch: pytest.MonkeyPatch) -> None:
    """TSA ve takvimleri taklit eder: gerçek biçimde, çağrılan veri için geçerli token/kanıt."""

    def fake_rfc(data: bytes, url=None, *, timeout=20.0) -> bytes:
        return _make_token_for(data)

    def fake_ots(digest: bytes, calendars=None, *, timeout=15.0):
        proof = (
            ts.OTS_MAGIC
            + b"\x01\x08"
            + digest
            + b"\xf0\x10"
            + bytes(16)
            + b"\x08"
            + _pending("https://cal.example")
        )
        return proof, {"calendars": 1, "failed": {}}

    monkeypatch.setattr(ts, "request_rfc3161", fake_rfc)
    monkeypatch.setattr(ts, "stamp_ots", fake_ots)


def _make_token_for(data: bytes) -> bytes:
    """Sabit DigiCert yanıtının imprint'ini değiştirerek başka veri için yapısal token üretir."""
    fixture_imprint = hashlib.sha256(DATA).digest()
    assert DIGICERT.count(fixture_imprint) == 1
    return DIGICERT.replace(fixture_imprint, hashlib.sha256(data).digest())


def test_timestamp_capture_writes_both_proofs(sealed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_timestamps(monkeypatch)
    result = ts.timestamp_capture(sealed)
    assert result["rfc3161"]["ok"] and result["rfc3161"]["gen_time"] == "2026-09-12T21:52:15Z"
    assert result["opentimestamps"]["ok"]
    assert (sealed / RFC3161_NAME).is_file() and (sealed / OTS_NAME).is_file()

    verified = verify_capture(sealed)
    assert verified["ok"] is True
    assert verified["timestamps"]["rfc3161"]["ok"] is True
    assert verified["timestamps"]["opentimestamps"]["state"] == "pending"
    # Zaman damgası dosyaları "listede yok" sayılmamalı.
    assert all(f["status"] == "ok" for f in verified["files"])


def test_network_failure_is_reported_not_raised(sealed: Path) -> None:
    result = ts.timestamp_capture(sealed, tsa="http://127.0.0.1:1", calendars=("http://127.0.0.1:1",))
    assert result["rfc3161"]["ok"] is False
    assert result["opentimestamps"]["ok"] is False
    assert not (sealed / RFC3161_NAME).exists()


def test_timestamp_for_a_different_manifest_breaks_verification(sealed: Path) -> None:
    (sealed / RFC3161_NAME).write_bytes(DIGICERT)  # başka bir manifestoya ait
    result = verify_capture(sealed)
    assert result["ok"] is False
    assert result["timestamps"]["rfc3161"]["error"] == "token was issued for different data"


def test_package_readme_explains_timestamps(
    sealed: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    meta = {"capture_id": "cap-1", "completed_at_utc": "2026-01-01T00:00:00Z"}
    assert "WHEN IT EXISTED" not in build_readme(meta, "en")

    _fake_timestamps(monkeypatch)
    ts.timestamp_capture(sealed)
    out, _ = build_package(sealed, meta, tmp_path / "pkg.zip", "en")
    with zipfile.ZipFile(out) as zf:
        names = {n.split("/", 1)[1] for n in zf.namelist()}
        readme = zf.read("cap-1/README.txt").decode()
    assert {RFC3161_NAME, OTS_NAME} <= names
    assert "WHEN IT EXISTED" in readme
    assert "openssl ts -verify -data manifest.json -in manifest.json.tsr" in readme
    assert "ots verify manifest.json.ots" in readme
    assert "{" not in readme


def test_api_timestamps_existing_capture_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    from webdamga import api

    importlib.reload(api)
    folder = tmp_path / "captures" / "cap-1"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(json.dumps({"capture_id": "cap-1", "capture_host": {}}))
    seal_capture(folder, {"capture_id": "cap-1"}, None)

    _fake_timestamps(monkeypatch)
    http = TestClient(api.app)
    first = http.post("/captures/cap-1/timestamp")
    assert first.status_code == 200
    assert first.json()["timestamps"]["rfc3161"]["ok"] is True
    assert http.post("/captures/cap-1/timestamp").status_code == 409

    page = http.get("/captures/cap-1?lang=en").text
    assert "2026-09-12T21:52:15Z" in page


@pytest.mark.skipif(not os.environ.get("WEBDAMGA_INTEGRATION"), reason="needs network")
def test_real_tsa_and_calendars(sealed: Path) -> None:
    result = ts.timestamp_capture(sealed)
    assert result["rfc3161"]["ok"], result
    assert result["opentimestamps"]["ok"], result
    assert verify_capture(sealed)["ok"] is True
