"""Yakalama klasörünü mühürleme: manifesto, sidecar özet ve isteğe bağlı imza.

Sıra önemli: metadata.json yazılmadan önce hangi anahtarla imzalanacağı
metadata'ya işlenir (böylece anahtar kimliği de manifestonun kapsamına
girer); manifesto yazıldıktan sonra manifestonun kendisi imzalanır.

İmza ve zaman damgası dosyaları manifestodan *sonra* üretildikleri için
manifestoda listelenmezler; doğrulama onları ayrıca kontrol eder.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .hashing import MANIFEST_NAME, build_manifest, write_manifest
from .signing import SecretKey, SigningError, load_secret_key, sign_file

SIGNATURE_NAME = MANIFEST_NAME + ".minisig"


def prepare_signing(enabled: bool, key_dir: Path | None = None) -> tuple[SecretKey | None, dict | None]:
    """İmzalama açıksa ve anahtar varsa (anahtar, metadata bloğu) döner.

    Anahtar yoksa sessizce (None, None); anahtar bozuksa hatayı metadata'ya
    yazmak üzere (None, {"error": ...}).
    """
    if not enabled:
        return None, None
    try:
        secret = load_secret_key(key_dir)
    except SigningError as exc:
        return None, {"error": str(exc)}
    if secret is None:
        return None, None
    public = secret.public_key()
    return secret, {
        "algorithm": "minisign Ed25519, BLAKE2b-512 prehashed",
        "key_id": public.id,
        "public_key": public.base64,
        "signed_file": MANIFEST_NAME,
    }


def trusted_comment(capture_id: str) -> str:
    stamp = int(datetime.now(UTC).timestamp())
    return f"timestamp:{stamp} file:{MANIFEST_NAME} capture:{capture_id} tool:webdamga/{__version__}"


def seal_capture(capture_dir: Path, meta: dict, secret: SecretKey | None = None) -> dict:
    """Manifestoyu yazar, varsa imzalar. Özet bilgi döner."""
    capture_dir = Path(capture_dir)
    manifest = build_manifest(capture_dir, tool="webdamga", tool_version=__version__, meta=meta)
    digest = write_manifest(capture_dir, manifest)
    result: dict = {"manifest_sha256": digest, "signature": None}
    if secret is not None:
        sig_path = sign_file(
            capture_dir / MANIFEST_NAME, secret, trusted_comment(meta.get("capture_id", capture_dir.name))
        )
        result["signature"] = sig_path.name
    return result
