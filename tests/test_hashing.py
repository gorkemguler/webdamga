"""hashing modülü için bütünlük/doğrulama testleri."""

from __future__ import annotations

import json
from pathlib import Path

from webdamga.hashing import build_manifest, verify_capture, write_manifest


def _make_capture(tmp_path: Path) -> Path:
    cap = tmp_path / "captures" / "20260101T000000Z-example-com-abc123"
    cap.mkdir(parents=True)
    (cap / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n fake image bytes")
    (cap / "dom.html").write_text("<html><body>merhaba</body></html>", encoding="utf-8")
    (cap / "metadata.json").write_text(
        json.dumps({"requested_url": "https://example.com", "completed_at_utc": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    return cap


def test_manifest_roundtrip_is_intact(tmp_path: Path) -> None:
    cap = _make_capture(tmp_path)
    manifest = build_manifest(
        cap, tool="webdamga", tool_version="0.0.test", meta={"requested_url": "https://example.com"}
    )
    digest = write_manifest(cap, manifest)

    assert (cap / "manifest.json").is_file()
    assert (cap / "manifest.sha256").read_text().startswith(digest)
    assert manifest["file_count"] == 3

    result = verify_capture(cap)
    assert result["ok"] is True
    assert result["sidecar_ok"] is True
    assert {f["status"] for f in result["files"]} == {"ok"}


def test_verify_detects_modified_file(tmp_path: Path) -> None:
    cap = _make_capture(tmp_path)
    write_manifest(cap, build_manifest(cap, tool="webdamga", tool_version="0.0.test", meta={}))

    (cap / "dom.html").write_text("<html><body>DEĞİŞTİRİLDİ</body></html>", encoding="utf-8")

    result = verify_capture(cap)
    assert result["ok"] is False
    statuses = {f["name"]: f["status"] for f in result["files"]}
    assert statuses["dom.html"] == "modified"
    assert statuses["screenshot.png"] == "ok"


def test_verify_detects_unlisted_and_missing(tmp_path: Path) -> None:
    cap = _make_capture(tmp_path)
    write_manifest(cap, build_manifest(cap, tool="webdamga", tool_version="0.0.test", meta={}))

    (cap / "sonradan-eklendi.txt").write_text("şüpheli", encoding="utf-8")
    (cap / "screenshot.png").unlink()

    result = verify_capture(cap)
    assert result["ok"] is False
    statuses = {f["name"]: f["status"] for f in result["files"]}
    assert statuses["screenshot.png"] == "missing"
    assert statuses["sonradan-eklendi.txt"] == "unlisted"
