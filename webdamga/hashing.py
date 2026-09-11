"""SHA-256 özetleri, bütünlük manifestosu ve doğrulama.

Bir yakalama klasörünün tamamı `manifest.json` içinde listelenen dosya
adları + boyutları + SHA-256 özetleriyle "mühürlenir". `manifest.sha256`
sidecar dosyası manifestonun kendi özetini tutar. `verify_capture` her iki
katmanı da yeniden hesaplayıp değişiklik/eksik/fazla dosya olup olmadığını
raporlar — delilin sonradan oynanmadığını göstermek için.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_BUFSIZE = 1 << 20
MANIFEST_NAME = "manifest.json"
MANIFEST_SIDECAR = "manifest.sha256"
_EXCLUDE = {MANIFEST_NAME, MANIFEST_SIDECAR}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_BUFSIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest(capture_dir: Path, *, tool: str, tool_version: str, meta: dict) -> dict:
    files = []
    for path in sorted(capture_dir.iterdir()):
        if not path.is_file() or path.name in _EXCLUDE:
            continue
        files.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "tool": tool,
        "tool_version": tool_version,
        "algorithm": "sha256",
        "capture_id": capture_dir.name,
        "created_utc": meta.get("completed_at_utc"),
        "requested_url": meta.get("requested_url"),
        "final_url": meta.get("final_url"),
        "http_status": meta.get("http_status"),
        "file_count": len(files),
        "files": files,
    }


def write_manifest(capture_dir: Path, manifest: dict) -> str:
    """Manifestoyu yazar, sidecar özetini yazar ve manifesto özetini döner."""
    raw = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
    (capture_dir / MANIFEST_NAME).write_bytes(raw)
    digest = sha256_bytes(raw)
    (capture_dir / MANIFEST_SIDECAR).write_text(f"{digest}  {MANIFEST_NAME}\n", encoding="utf-8")
    return digest


def verify_capture(capture_dir: Path) -> dict:
    """Yakalama klasörünü manifestoya göre doğrular."""
    manifest_path = capture_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return {"ok": False, "capture_id": capture_dir.name, "error": "manifest.json yok", "files": []}

    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    listed = {entry["name"] for entry in manifest.get("files", [])}
    results: list[dict] = []
    ok = True

    for entry in manifest.get("files", []):
        path = capture_dir / entry["name"]
        if not path.is_file():
            results.append({"name": entry["name"], "status": "missing"})
            ok = False
            continue
        actual = sha256_file(path)
        if actual == entry["sha256"]:
            results.append({"name": entry["name"], "status": "ok", "sha256": actual})
        else:
            results.append(
                {"name": entry["name"], "status": "modified", "expected": entry["sha256"], "actual": actual}
            )
            ok = False

    for path in sorted(capture_dir.iterdir()):
        if path.is_file() and path.name not in listed and path.name not in _EXCLUDE:
            results.append({"name": path.name, "status": "unlisted"})
            ok = False

    manifest_digest = sha256_bytes(manifest_bytes)
    sidecar = capture_dir / MANIFEST_SIDECAR
    sidecar_ok = None
    if sidecar.exists():
        expected = sidecar.read_text(encoding="utf-8").split()[0]
        sidecar_ok = expected == manifest_digest
        if not sidecar_ok:
            ok = False

    return {
        "ok": ok,
        "capture_id": capture_dir.name,
        "manifest_sha256": manifest_digest,
        "sidecar_ok": sidecar_ok,
        "files": results,
    }
