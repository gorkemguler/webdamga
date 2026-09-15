"""Uzun süreli çalışma için bakım: saklama süresi ve OTS yükseltme.

Saatlik izlemede yakalamalar diski hızla doldurur (bir sayfa 30+ MB). Bu
modül iki bakım işini yürütür:

  budama (prune)   Belirli bir yaştan eski yakalamaları siler. Bir izleyicinin
                   son karşılaştırma tabanı ve imzalı/zaman damgalı yakalamalar
                   korunur; delil kasten atılmaz.
  OTS yükseltme    Bekleyen OpenTimestamps kanıtlarını Bitcoin onayı geldikçe
                   günceller. Kanıt protokolünü elle yeniden yazmak geçersiz
                   kanıt riski taşıdığından resmi `ots` istemcisi kullanılır;
                   yoksa atlanır ve açıkça bildirilir. manifest.json.ots bir
                   mühür dosyasıdır, manifestoda listelenmez; yükseltmek
                   doğrulamayı bozmaz.

İşler idempotent ve en iyi çaba temellidir; biri patlarsa diğerleri sürer.
`webdamga prune` ve `webdamga upgrade-timestamps` ile elle, ya da bir cron /
systemd timer ile düzenli çalıştırılır.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .hashing import OTS_NAME, SIGNATURE_NAME
from .timestamp import check_ots

log = logging.getLogger("webdamga.maintenance")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


# --------------------------------------------------------------------- budama


@dataclass(frozen=True, slots=True)
class PrunePlan:
    """Budamanın ne yapacağı; --dry-run bunu uygulamadan gösterir."""

    delete: list[str]
    kept_signed: list[str]
    kept_baseline: list[str]
    freed_bytes: int


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _protected_baselines(store) -> set[str]:
    return {m["last_capture_id"] for m in store.list_monitors() if m.get("last_capture_id")}


def plan_prune(store, data_dir: Path, *, older_than_days: int, keep_signed: bool = True) -> PrunePlan:
    """Silinecek yakalamaları belirler (uygulamadan)."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    baselines = _protected_baselines(store)
    captures_dir = Path(data_dir) / "captures"

    delete, kept_signed, kept_baseline, freed = [], [], [], 0
    for row in store.list(100000):
        created = _parse_iso(row.get("created_utc"))
        if created is None or created >= cutoff:
            continue
        capture_id = row["id"]
        folder = captures_dir / capture_id
        if not folder.is_dir():
            continue
        if capture_id in baselines:
            kept_baseline.append(capture_id)
            continue
        if keep_signed and (folder / SIGNATURE_NAME).is_file():
            kept_signed.append(capture_id)
            continue
        delete.append(capture_id)
        freed += _dir_size(folder)
    return PrunePlan(delete, kept_signed, kept_baseline, freed)


def run_prune(store, data_dir: Path, plan: PrunePlan) -> int:
    """Planı uygular: klasörleri ve indeks kaydını siler. Silinen sayısını döner."""
    captures_dir = Path(data_dir) / "captures"
    removed = 0
    for capture_id in plan.delete:
        folder = captures_dir / capture_id
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
        store.delete_capture(capture_id)
        # Varsa yan istihbarat ve karşılaştırma çıktıları da gitsin.
        shutil.rmtree(Path(data_dir) / "intel" / capture_id, ignore_errors=True)
        removed += 1
    _prune_diffs(store, data_dir)
    return removed


def _prune_diffs(store, data_dir: Path) -> None:
    """Artık var olmayan yakalamalara ait diff klasörlerini temizler."""
    diffs = Path(data_dir) / "diffs"
    if not diffs.is_dir():
        return
    alive = {row["id"] for row in store.list(100000)}
    for folder in diffs.iterdir():
        if not folder.is_dir():
            continue
        parts = folder.name.split("__")
        if len(parts) == 2 and not (parts[0] in alive and parts[1] in alive):
            shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------- OTS yükseltme


def ots_client_available() -> bool:
    return shutil.which("ots") is not None


def pending_ots_captures(store, data_dir: Path) -> list[str]:
    """Bekleyen (Bitcoin onayı gelmemiş) OTS kanıtı olan yakalamalar."""
    captures_dir = Path(data_dir) / "captures"
    pending = []
    for row in store.list(100000):
        folder = captures_dir / row["id"]
        ots, manifest = folder / OTS_NAME, folder / "manifest.json"
        if not (ots.is_file() and manifest.is_file()):
            continue
        info = check_ots(manifest.read_bytes(), ots.read_bytes())
        if info.get("ok") and info.get("state") == "pending":
            pending.append(row["id"])
    return pending


def upgrade_ots(data_dir: Path, capture_id: str) -> str:
    """Bir yakalamanın OTS kanıtını resmi istemciyle yükseltir.

    Döner: 'upgraded' (Bitcoin onayı geldi), 'pending' (henüz değil),
    'no-client' (ots kurulu değil), 'error'.
    """
    ots = Path(data_dir) / "captures" / capture_id / OTS_NAME
    if not ots.is_file():
        return "error"
    if not ots_client_available():
        return "no-client"
    before = ots.read_bytes()
    try:
        subprocess.run(
            ["ots", "upgrade", str(ots)],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("ots upgrade failed for %s: %s", capture_id, exc)
        return "error"
    # ots başarıda .ots'u yeniden yazar, .bak bırakır; onu temizle.
    backup = ots.with_suffix(ots.suffix + ".bak")
    backup.unlink(missing_ok=True)
    manifest = ots.parent / "manifest.json"
    info = check_ots(manifest.read_bytes(), ots.read_bytes()) if manifest.is_file() else {}
    if info.get("state") == "confirmed":
        return "upgraded"
    return "pending" if ots.read_bytes() == before else "upgraded"


def upgrade_all_pending(store, data_dir: Path) -> dict[str, int]:
    """Bekleyen tüm OTS kanıtlarını yükseltmeyi dener; sonuç sayımlarını döner."""
    counts = {"upgraded": 0, "pending": 0, "error": 0, "no-client": 0}
    if not ots_client_available():
        pending = pending_ots_captures(store, data_dir)
        counts["no-client"] = len(pending)
        return counts
    for capture_id in pending_ots_captures(store, data_dir):
        counts[upgrade_ots(data_dir, capture_id)] += 1
    return counts
