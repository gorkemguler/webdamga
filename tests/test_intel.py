"""İhbar istihbaratı: RDAP alan adı/IP ayrıştırma, ASN, abuse toplama."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webdamga import intel

DOMAIN_RDAP = {
    "objectClassName": "domain",
    "ldhName": "EXAMPLE.COM",
    "status": ["client transfer prohibited"],
    "events": [
        {"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"},
        {"eventAction": "expiration", "eventDate": "2027-08-13T04:00:00Z"},
        {"eventAction": "last changed", "eventDate": "2026-08-14T08:01:43Z"},
    ],
    "nameservers": [{"ldhName": "A.IANA-SERVERS.NET"}, {"ldhName": "B.IANA-SERVERS.NET"}],
    "entities": [
        {
            "roles": ["registrar"],
            "handle": "376",
            "vcardArray": ["vcard", [["fn", {}, "text", "MarkMonitor Inc."]]],
            "entities": [
                {
                    "roles": ["abuse"],
                    "vcardArray": [
                        "vcard",
                        [
                            ["fn", {}, "text", "MarkMonitor Abuse"],
                            ["email", {}, "text", "abuse@markmonitor.com"],
                        ],
                    ],
                }
            ],
        }
    ],
}

IP_RDAP = {
    "objectClassName": "ip network",
    "handle": "NET-140-82-112-0-1",
    "name": "GITHU",
    "startAddress": "140.82.112.0",
    "endAddress": "140.82.127.255",
    "cidr0_cidrs": [{"v4prefix": "140.82.112.0", "length": 20}],
    "entities": [
        {
            "roles": ["registrant"],
            "handle": "GITHU",
            "entities": [
                {
                    "roles": ["abuse"],
                    "handle": "GITHU1-ARIN",
                    "vcardArray": [
                        "vcard",
                        [["fn", {}, "text", "GitHub Abuse"], ["email", {}, "text", "noc@github.com"]],
                    ],
                }
            ],
        }
    ],
}

CYMRU = (
    "Bulk mode; whois.cymru.com [2026-09-15 08:22:47 +0000]\n"
    "36459   | 140.82.121.3     | 140.82.121.0/24     | US | arin     | 2018-04-25 | GITHUB - GitHub, Inc., US\n"
)


class _FakeSock:
    """Cymru whois yanıtını döndüren sahte soket; gerçek asn_intel'i çalıştırır."""

    def __init__(self, payload: bytes = CYMRU.encode()) -> None:
        self._payload = payload

    def sendall(self, data: bytes) -> None:
        pass

    def recv(self, n: int) -> bytes:
        chunk, self._payload = self._payload[:n], self._payload[n:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch):
    """RDAP'i sabit veriye, Cymru'yu sahte sokete yönlendirir; ağ kullanılmaz.

    asn_intel taklit edilmez; gerçek ayrıştırma kodu sahte soket üstünde çalışır.
    """

    def fake_rdap(path: str) -> dict:
        if path.startswith("domain/"):
            return DOMAIN_RDAP
        if path.startswith("ip/"):
            return IP_RDAP
        raise intel.IntelError(f"unexpected path {path}")

    monkeypatch.setattr(intel, "_rdap", fake_rdap)
    monkeypatch.setattr(intel.socket, "create_connection", lambda *a, **k: _FakeSock())


# ------------------------------------------------------------------ ayrıştırma


def test_domain_intel_extracts_registrar_and_dates() -> None:
    info = intel.domain_intel("example.com")
    assert info["domain"] == "example.com"
    assert info["registrar"] == "MarkMonitor Inc."
    assert info["registered"] == "1995-08-14T04:00:00Z"
    assert info["expires"] == "2027-08-13T04:00:00Z"
    assert info["nameservers"] == ["A.IANA-SERVERS.NET", "B.IANA-SERVERS.NET"]
    assert info["abuse"]["emails"] == ["abuse@markmonitor.com"]


def test_ip_intel_extracts_owner_and_abuse() -> None:
    info = intel.ip_intel("140.82.121.3")
    assert info["network_name"] == "GITHU"
    assert info["cidr"] == "140.82.112.0/20"
    assert info["range"] == "140.82.112.0 - 140.82.127.255"
    assert info["abuse"]["emails"] == ["noc@github.com"]
    assert info["abuse"]["handle"] == "GITHU1-ARIN"


def test_nested_abuse_entity_is_found() -> None:
    # abuse iletişimi registrar entity'sinin ALTINDA; düz gezme bulmalı.
    assert intel._abuse_contact(DOMAIN_RDAP["entities"])["emails"] == ["abuse@markmonitor.com"]


def test_missing_abuse_returns_none() -> None:
    assert intel._abuse_contact([{"roles": ["registrar"], "handle": "x"}]) is None


def test_asn_intel_parses_cymru_response() -> None:
    # Fixture soketi taklit ediyor; asn_intel'in gerçek ayrıştırması çalışır.
    result = intel.asn_intel("140.82.121.3")
    assert result == {
        "asn": "36459",
        "cidr": "140.82.121.0/24",
        "country": "US",
        "org": "GITHUB - GitHub, Inc., US",
    }


def test_asn_intel_without_origin_line_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        intel.socket, "create_connection", lambda *a, **k: _FakeSock(b"Bulk mode; no data here\n")
    )
    with pytest.raises(intel.IntelError):
        intel.asn_intel("10.0.0.1")


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("www.github.com", "github.com"),
        ("github.com", "github.com"),
        ("login.secure.example.co.uk", "example.co.uk"),
        ("a.b.c.example.com", "example.com"),
    ],
)
def test_registrable_domain(host: str, expected: str) -> None:
    assert intel._registrable(host) == expected


# --------------------------------------------------------------------- gather


def test_gather_combines_all_sources_and_dedupes_abuse() -> None:
    meta = {
        "final_url": "https://www.example.com/login",
        "remote_address": {"ipAddress": "140.82.121.3", "port": 443},
    }
    report = intel.gather(meta)
    assert report["domain"]["registrar"] == "MarkMonitor Inc."
    assert report["ip"]["network_name"] == "GITHU"
    assert report["asn"]["asn"] == "36459"
    assert report["abuse_emails"] == ["abuse@markmonitor.com", "noc@github.com"]
    assert "collected_at_utc" in report


def test_gather_skips_domain_for_ip_targets() -> None:
    meta = {"final_url": "https://140.82.121.3/", "remote_address": {"ipAddress": "140.82.121.3"}}
    report = intel.gather(meta)
    assert "domain" not in report
    assert report["ip"]["network_name"] == "GITHU"


def test_gather_survives_a_failing_source(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(path: str) -> dict:
        if path.startswith("domain/"):
            raise intel.IntelError("RDAP domain: HTTP 404")
        return IP_RDAP

    monkeypatch.setattr(intel, "_rdap", boom)
    report = intel.gather({"final_url": "https://example.com/", "remote_address": {"ipAddress": "1.2.3.4"}})
    assert report["domain"]["error"].startswith("RDAP domain")
    assert report["ip"]["network_name"] == "GITHU"  # IP yine geldi


def test_gather_without_ip_only_does_domain() -> None:
    report = intel.gather({"final_url": "https://example.com/"})
    assert report["domain"]["registrar"] == "MarkMonitor Inc."
    assert "ip" not in report and "asn" not in report


# ---------------------------------------------------------------- vcard robust


def test_vcard_handles_missing_fields() -> None:
    assert intel._vcard_fields({}) == {"emails": [], "phones": []}
    assert intel._vcard_fields({"vcardArray": ["vcard", []]}) == {"emails": [], "phones": []}


# --------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    from webdamga import api

    importlib.reload(api)
    # api kendi intel modülünü import ediyor; onu da taklit edelim.
    import webdamga.intel as api_intel

    monkeypatch.setattr(
        api_intel, "_rdap", lambda path: DOMAIN_RDAP if path.startswith("domain/") else IP_RDAP
    )
    monkeypatch.setattr(
        api_intel, "asn_intel", lambda ip: {"asn": "36459", "org": "GITHUB - GitHub, Inc., US"}
    )
    return TestClient(api.app), api


def _seal(api, name: str, meta_extra: dict) -> None:
    from webdamga.seal import seal_capture

    cap = api.DATA_DIR / "captures" / name
    cap.mkdir(parents=True)
    meta = {"capture_id": name, "final_url": "https://example.com/", **meta_extra}
    (cap / "metadata.json").write_text(json.dumps(meta))
    seal_capture(cap, meta, None)


def test_capture_form_carries_intel_flag(client) -> None:
    http, api = client
    r = http.post("/captures", data={"url": "example.com", "intel": "true"}, follow_redirects=False)
    job_id = r.headers["location"].rsplit("/", 1)[1]
    assert json.loads(api._store.get_job(job_id)["settings_json"])["intel"] is True


def test_intel_endpoint_writes_outside_the_sealed_folder(client) -> None:
    http, api = client
    _seal(api, "cap1", {"remote_address": {"ipAddress": "140.82.121.3"}})
    before = sorted(p.name for p in (api.DATA_DIR / "captures" / "cap1").iterdir())

    report = http.post("/captures/cap1/intel").json()
    assert report["abuse_emails"] == ["abuse@markmonitor.com", "noc@github.com"]
    # Mühürlü klasöre dokunulmamalı.
    assert sorted(p.name for p in (api.DATA_DIR / "captures" / "cap1").iterdir()) == before
    assert (api.DATA_DIR / "intel" / "cap1" / "intel.json").is_file()
    # Doğrulama hâlâ bütün demeli.
    assert http.get("/captures/cap1/verify").json()["ok"] is True


def test_detail_page_shows_button_then_results(client) -> None:
    http, api = client
    _seal(api, "cap2", {"remote_address": {"ipAddress": "140.82.121.3"}})
    assert "intel-btn" in http.get("/captures/cap2?lang=en").text  # henüz yok, buton var
    http.post("/captures/cap2/intel")
    page = http.get("/captures/cap2?lang=en").text
    assert "abuse@markmonitor.com" in page
