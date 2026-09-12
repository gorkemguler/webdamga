"""Kanıt paketi ve rapor üretimi."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from webdamga.hashing import build_manifest, sha256_file, write_manifest
from webdamga.report import (
    PACKAGE_README,
    REPORT_NAME,
    build_package,
    build_readme,
    build_report_html,
    default_package_name,
)

CAPTURE_ID = "20260101T000000Z-example-com-abc123"


@pytest.fixture
def capture(tmp_path: Path) -> tuple[Path, dict, dict]:
    """Gerçekçi bir yakalama klasörü kurar."""
    cap = tmp_path / "captures" / CAPTURE_ID
    cap.mkdir(parents=True)
    (cap / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n full")
    (cap / "screenshot-viewport.png").write_bytes(b"\x89PNG\r\n\x1a\n viewport")
    (cap / "dom.html").write_text("<html><body>merhaba</body></html>", encoding="utf-8")
    (cap / "console.log").write_text("", encoding="utf-8")

    meta = {
        "capture_id": CAPTURE_ID,
        "requested_url": "https://example.com",
        "final_url": "https://example.com/",
        "http_status": 200,
        "http_status_text": "",
        "page_title": "Example Domain",
        "requested_at_utc": "2026-01-01T00:00:00Z",
        "completed_at_utc": "2026-01-01T00:00:03Z",
        "remote_address": {"ipAddress": "93.184.216.34", "port": 443},
        "tls": {
            "protocol": "TLS 1.3",
            "issuer": "Example CA",
            "subjectName": "example.com",
            "validFrom_iso": "2026-01-01T00:00:00Z",
            "validTo_iso": "2026-06-01T00:00:00Z",
        },
        "browser": {"name": "chromium", "version": "151.0"},
        "user_agent": "Mozilla/5.0",
        "capture_host": {"hostname": "test-host", "platform": "macOS"},
        "resource_summary": {"request_count": 1, "transfer_bytes": 512},
        "redirect_chain": [{"url": "http://example.com/", "status": 301}],
    }
    (cap / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    manifest = build_manifest(cap, tool="webdamga", tool_version="0.0.test", meta=meta)
    write_manifest(cap, manifest)
    return cap, meta, manifest


def test_default_package_name() -> None:
    assert default_package_name(CAPTURE_ID) == f"webdamga-{CAPTURE_ID}.zip"


def test_package_contains_every_artefact(capture, tmp_path: Path) -> None:
    cap, meta, _ = capture
    out, digest = build_package(cap, meta, tmp_path / "pkg.zip", "en", pdf_bytes=b"%PDF-fake")

    with zipfile.ZipFile(out) as zf:
        names = {n.split("/", 1)[1] for n in zf.namelist()}

    on_disk = {p.name for p in cap.iterdir() if p.is_file()}
    assert on_disk <= names, "yakalama klasöründeki her dosya pakette olmalı"
    assert PACKAGE_README in names
    assert REPORT_NAME in names
    assert len(digest) == 64


def test_package_entries_live_under_capture_id_folder(capture, tmp_path: Path) -> None:
    cap, meta, _ = capture
    out, _ = build_package(cap, meta, tmp_path / "pkg.zip", "en")
    with zipfile.ZipFile(out) as zf:
        assert all(n.startswith(f"{CAPTURE_ID}/") for n in zf.namelist())


def test_package_files_survive_the_round_trip(capture, tmp_path: Path) -> None:
    """Paketten çıkan dosyalar manifestodaki özetlerle hâlâ eşleşmeli."""
    cap, meta, manifest = capture
    out, _ = build_package(cap, meta, tmp_path / "pkg.zip", "en")

    extracted = tmp_path / "out"
    with zipfile.ZipFile(out) as zf:
        zf.extractall(extracted)
    root = extracted / CAPTURE_ID

    for entry in manifest["files"]:
        assert sha256_file(root / entry["name"]) == entry["sha256"], entry["name"]


def test_package_is_deterministic_for_identical_inputs(capture, tmp_path: Path, monkeypatch) -> None:
    """Girdiler (README zamanı ve PDF dahil) aynıysa paket özeti de aynı olmalı.

    Farklı zamanlarda üretilen paketler README.txt'deki paketleme zamanı
    yüzünden farklı özet verir; bu beklenen davranış.
    """
    from webdamga import report

    monkeypatch.setattr(report, "_now_iso", lambda: "2026-01-01T00:00:00Z")
    cap, meta, _ = capture
    _, first = build_package(cap, meta, tmp_path / "a.zip", "en", pdf_bytes=b"%PDF-fake")
    _, second = build_package(cap, meta, tmp_path / "b.zip", "en", pdf_bytes=b"%PDF-fake")
    assert first == second


def test_package_without_pdf(capture, tmp_path: Path) -> None:
    cap, meta, _ = capture
    out, _ = build_package(cap, meta, tmp_path / "pkg.zip", "en")
    with zipfile.ZipFile(out) as zf:
        assert not any(n.endswith(REPORT_NAME) for n in zf.namelist())


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_readme_carries_capture_details(capture, lang: str) -> None:
    _, meta, _ = capture
    readme = build_readme(meta, lang)
    assert CAPTURE_ID in readme
    assert "https://example.com/" in readme
    assert "manifest.sha256" in readme
    assert "{" not in readme, "biçimlendirilmemiş yer tutucu kalmış"


def test_report_html_includes_key_evidence(capture) -> None:
    cap, meta, manifest = capture
    html = build_report_html(cap, meta, manifest, "en")

    assert "Web capture evidence report" in html
    assert CAPTURE_ID in html
    assert "https://example.com/" in html
    assert "93.184.216.34" in html
    assert "TLS 1.3" in html
    for entry in manifest["files"]:
        assert entry["sha256"] in html, f"{entry['name']} özeti raporda yok"
    # Ekran görüntüsü gömülü olmalı, dış dosyaya bağımlı kalmamalı.
    assert "data:image/png;base64," in html


def test_report_html_is_translated(capture) -> None:
    cap, meta, manifest = capture
    assert "Web yakalama kanıt raporu" in build_report_html(cap, meta, manifest, "tr")


def test_report_html_handles_missing_screenshot(capture, tmp_path: Path) -> None:
    cap, meta, manifest = capture
    (cap / "screenshot.png").unlink()
    (cap / "screenshot-viewport.png").unlink()
    html = build_report_html(cap, meta, manifest, "en")
    assert "No screenshot was produced" in html
