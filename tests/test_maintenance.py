"""Bakım: saklama/budama ve OTS yükseltme."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from webdamga import maintenance
from webdamga.maintenance import (
    plan_prune,
    run_prune,
    upgrade_all_pending,
    upgrade_ots,
)
from webdamga.storage import Store


def _capture(store: Store, data_dir: Path, capture_id: str, *, days_old: int, signed: bool = False) -> Path:
    folder = data_dir / "captures" / capture_id
    folder.mkdir(parents=True)
    (folder / "dom.html").write_text("<html>" + "x" * 1000 + "</html>")
    (folder / "manifest.json").write_text("{}")
    if signed:
        (folder / "manifest.json.minisig").write_text("sig")
    when = (datetime.now(UTC) - timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.record(
        {
            "capture_id": capture_id,
            "requested_url": "https://example.com",
            "final_url": "https://example.com",
            "completed_at_utc": when,
            "dir": str(folder),
        },
        manifest_sha256=None,
        ok=True,
        error=None,
    )
    # created_utc'yi geçmişe çek (record completed_at'i kullanır).
    with store._conn() as conn:
        conn.execute("UPDATE captures SET created_utc = ? WHERE id = ?", (when, capture_id))
        conn.commit()
    return folder


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path)


# --------------------------------------------------------------------- budama


def test_prune_deletes_only_old_captures(store: Store, tmp_path: Path) -> None:
    _capture(store, tmp_path, "old", days_old=40)
    _capture(store, tmp_path, "recent", days_old=5)

    plan = plan_prune(store, tmp_path, older_than_days=30)
    assert plan.delete == ["old"]
    assert plan.freed_bytes > 0

    removed = run_prune(store, tmp_path, plan)
    assert removed == 1
    assert not (tmp_path / "captures" / "old").exists()
    assert (tmp_path / "captures" / "recent").exists()
    assert store.get("old") is None
    assert store.get("recent") is not None


def test_prune_keeps_signed_captures(store: Store, tmp_path: Path) -> None:
    _capture(store, tmp_path, "old-signed", days_old=40, signed=True)
    plan = plan_prune(store, tmp_path, older_than_days=30, keep_signed=True)
    assert plan.delete == []
    assert plan.kept_signed == ["old-signed"]


def test_prune_can_include_signed_when_asked(store: Store, tmp_path: Path) -> None:
    _capture(store, tmp_path, "old-signed", days_old=40, signed=True)
    plan = plan_prune(store, tmp_path, older_than_days=30, keep_signed=False)
    assert plan.delete == ["old-signed"]


def test_prune_keeps_monitor_baseline(store: Store, tmp_path: Path) -> None:
    _capture(store, tmp_path, "baseline", days_old=40)
    store.create_monitor("https://example.com", 60, "{}")
    store.update_monitor(1, last_capture_id="baseline")

    plan = plan_prune(store, tmp_path, older_than_days=30)
    assert plan.delete == []
    assert plan.kept_baseline == ["baseline"]


def test_prune_dry_run_leaves_everything(store: Store, tmp_path: Path) -> None:
    _capture(store, tmp_path, "old", days_old=40)
    plan = plan_prune(store, tmp_path, older_than_days=30)
    # run_prune çağrılmazsa hiçbir şey silinmez.
    assert (tmp_path / "captures" / "old").exists()
    assert plan.delete == ["old"]


def test_prune_also_removes_side_intel_and_diffs(store: Store, tmp_path: Path) -> None:
    _capture(store, tmp_path, "old", days_old=40)
    _capture(store, tmp_path, "recent", days_old=1)
    (tmp_path / "intel" / "old").mkdir(parents=True)
    (tmp_path / "intel" / "old" / "intel.json").write_text("{}")
    (tmp_path / "diffs" / "old__recent").mkdir(parents=True)
    (tmp_path / "diffs" / "old__recent" / "diff.json").write_text("{}")

    run_prune(store, tmp_path, plan_prune(store, tmp_path, older_than_days=30))
    assert not (tmp_path / "intel" / "old").exists()
    assert not (tmp_path / "diffs" / "old__recent").exists()


# --------------------------------------------------------------- OTS yükseltme


def _ots_capture(store: Store, tmp_path: Path, capture_id: str, *, pending: bool) -> Path:
    import hashlib

    folder = _capture(store, tmp_path, capture_id, days_old=1)
    digest = hashlib.sha256((folder / "manifest.json").read_bytes()).digest()
    proof = _pending_proof(digest) if pending else _confirmed_proof(digest)
    (folder / "manifest.json.ots").write_bytes(proof)
    return folder


def _pending_proof(digest: bytes) -> bytes:
    from webdamga.timestamp import _PENDING_TAG, OTS_MAGIC, _varuint

    uri = b"https://a.calendar.example"
    payload = _varuint(len(uri)) + uri
    return OTS_MAGIC + b"\x01\x08" + digest + b"\x00" + _PENDING_TAG + _varuint(len(payload)) + payload


def _confirmed_proof(digest: bytes) -> bytes:
    from webdamga.timestamp import _BITCOIN_TAG, OTS_MAGIC, _varuint

    payload = _varuint(800000)
    return OTS_MAGIC + b"\x01\x08" + digest + b"\x00" + _BITCOIN_TAG + _varuint(len(payload)) + payload


def test_pending_ots_captures_lists_only_pending(store: Store, tmp_path: Path) -> None:
    _ots_capture(store, tmp_path, "pend", pending=True)
    _ots_capture(store, tmp_path, "done", pending=False)
    _capture(store, tmp_path, "no-ots", days_old=1)
    assert maintenance.pending_ots_captures(store, tmp_path) == ["pend"]


def test_upgrade_without_client_reports_no_client(store: Store, tmp_path: Path, monkeypatch) -> None:
    _ots_capture(store, tmp_path, "pend", pending=True)
    monkeypatch.setattr(maintenance.shutil, "which", lambda name: None)
    counts = upgrade_all_pending(store, tmp_path)
    assert counts["no-client"] == 1
    assert counts["upgraded"] == 0


def test_upgrade_ots_runs_client_and_detects_confirmation(store: Store, tmp_path: Path, monkeypatch) -> None:
    folder = _ots_capture(store, tmp_path, "pend", pending=True)
    import hashlib

    digest = hashlib.sha256((folder / "manifest.json").read_bytes()).digest()

    monkeypatch.setattr(maintenance.shutil, "which", lambda name: "/usr/bin/ots")

    def fake_run(cmd, **kwargs):
        # ots upgrade'i taklit et: kanıtı onaylanmışla değiştir.
        (folder / "manifest.json.ots").write_bytes(_confirmed_proof(digest))

    monkeypatch.setattr(maintenance.subprocess, "run", fake_run)
    assert upgrade_ots(tmp_path, "pend") == "upgraded"
    # Artık onaylı olduğu için bekleyenler listesinde görünmemeli.
    assert maintenance.pending_ots_captures(store, tmp_path) == []


def test_upgrade_ots_still_pending(store: Store, tmp_path: Path, monkeypatch) -> None:
    _ots_capture(store, tmp_path, "pend", pending=True)
    monkeypatch.setattr(maintenance.shutil, "which", lambda name: "/usr/bin/ots")
    monkeypatch.setattr(maintenance.subprocess, "run", lambda cmd, **k: None)  # kanıt değişmez
    assert upgrade_ots(tmp_path, "pend") == "pending"


# --------------------------------------------------------------------- CLI


def test_cli_prune_dry_run(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from webdamga.cli import app

    store = Store(tmp_path)
    _capture(store, tmp_path, "old", days_old=40)
    runner = CliRunner()
    result = runner.invoke(app, ["prune", "--older-than", "30", "--dry-run", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "old" in result.output
    assert (tmp_path / "captures" / "old").exists()  # dry-run silmedi


def test_cli_prune_applies(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from webdamga.cli import app

    store = Store(tmp_path)
    _capture(store, tmp_path, "old", days_old=40)
    result = CliRunner().invoke(app, ["prune", "--older-than", "30", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert not (tmp_path / "captures" / "old").exists()
