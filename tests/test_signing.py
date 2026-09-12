"""Manifest imzalama: minisign uyumluluğu, kurcalama tespiti, anahtar yönetimi."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

from webdamga.hashing import SIGNATURE_NAME, build_manifest, verify_capture, write_manifest
from webdamga.report import SIGNER_PUB, build_package, build_readme
from webdamga.seal import prepare_signing, seal_capture
from webdamga.signing import (
    PUBLIC_NAME,
    SECRET_NAME,
    PublicKey,
    SecretKey,
    SigningError,
    generate_keypair,
    load_public_key,
    load_secret_key,
    sign_bytes,
    sign_file,
    verify_bytes,
    verify_file,
)

# Gerçek minisign 0.12 ile üretildi (minisign -S -t ...). Kendi kodumuzu kendi
# kodumuzla değil, bağımsız bir uygulamanın çıktısıyla sınamak için.
MINISIGN_PUB = "RWS96FLi5eW1PaKaoksGxnTn8FoPHQw4YiVcokTFbU2wfDIOf3JGnlsw"
MINISIGN_MESSAGE = b'{"capture_id": "fixture", "files": []}\n'
MINISIGN_SIG = (
    "untrusted comment: signature from minisign secret key\n"
    "RUS96FLi5eW1PVGlG4ZBMnJQGWqHliZ4UPwaIqdQP64mpnk5Kri59s+LY5fDG9EoLc6D9gr45YwOFCRsGqujNoVDg03nIpYMXgw=\n"
    "trusted comment: timestamp:1757700000 file:manifest.json capture:fixture\n"
    "N3ZBprxBvpnGBny9fpAki2Y4pYVMYJatRafl6Gxv4bIWb9QauzHLh592Vl+BRfC97l7c4KJzXvW17p2AV3T9Cg==\n"
)


@pytest.fixture
def secret(_isolated_signing_keys: Path) -> SecretKey:
    return generate_keypair(_isolated_signing_keys)


# ------------------------------------------------------------ minisign formatı


def test_verifies_signature_made_by_real_minisign() -> None:
    result = verify_bytes(MINISIGN_MESSAGE, MINISIGN_SIG, PublicKey.parse(MINISIGN_PUB))
    assert result.ok, result.error
    assert result.key_id == "3DB5E5E5E252E8BD"
    assert result.trusted_comment == "timestamp:1757700000 file:manifest.json capture:fixture"


def test_real_minisign_signature_detects_tampering() -> None:
    public = PublicKey.parse(MINISIGN_PUB)
    assert not verify_bytes(MINISIGN_MESSAGE + b" ", MINISIGN_SIG, public).ok
    forged = MINISIGN_SIG.replace("capture:fixture", "capture:forged")
    result = verify_bytes(MINISIGN_MESSAGE, forged, public)
    assert not result.ok
    assert "trusted comment" in result.error


def test_public_key_file_round_trip(secret: SecretKey) -> None:
    public = secret.public_key()
    text = public.to_minisign()
    assert text.startswith(f"untrusted comment: minisign public key {public.id}\n")
    assert PublicKey.parse(text) == public
    assert PublicKey.parse(public.base64) == public


@pytest.mark.parametrize("bad", ["", "not base64!", "RWQ=", "AAAA" * 14])
def test_public_key_parse_rejects_garbage(bad: str) -> None:
    with pytest.raises(SigningError):
        PublicKey.parse(bad)


def test_signature_uses_prehashed_ed_format(secret: SecretKey) -> None:
    import base64

    text = sign_bytes(b"hello", secret, "timestamp:1 file:x")
    lines = text.splitlines()
    blob = base64.b64decode(lines[1])
    assert blob[:2] == b"ED" and blob[2:10] == secret.key_id and len(blob) == 74
    assert lines[2] == "trusted comment: timestamp:1 file:x"
    assert len(base64.b64decode(lines[3])) == 64


# ---------------------------------------------------------------- kurcalama


def test_sign_and_verify_round_trip(secret: SecretKey, tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    target.write_text('{"a": 1}')
    sign_file(target, secret, "timestamp:1 file:manifest.json")
    result = verify_file(target, secret.public_key())
    assert result.ok and result.key_id == secret.id


def test_modified_file_fails(secret: SecretKey, tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    target.write_text('{"a": 1}')
    sign_file(target, secret, "timestamp:1 file:manifest.json")
    target.write_text('{"a": 2}')
    result = verify_file(target, secret.public_key())
    assert not result.ok
    assert result.error == "signature does not match the file"


def test_wrong_key_is_named_in_the_error(secret: SecretKey, tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    target.write_text("{}")
    sign_file(target, secret, "timestamp:1 file:manifest.json")
    other = generate_keypair(tmp_path / "other")
    result = verify_file(target, other.public_key())
    assert not result.ok
    assert secret.id in result.error and other.id in result.error


def test_missing_signature_file(secret: SecretKey, tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    target.write_text("{}")
    assert verify_file(target, secret.public_key()).error == "no signature file"


def test_trusted_comment_must_be_single_line(secret: SecretKey) -> None:
    with pytest.raises(SigningError):
        sign_bytes(b"x", secret, "a\ntrusted comment: injected")


# ------------------------------------------------------------------ anahtarlar


def test_keygen_files_and_permissions(_isolated_signing_keys: Path, secret: SecretKey) -> None:
    secret_path = _isolated_signing_keys / SECRET_NAME
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(_isolated_signing_keys.stat().st_mode) == 0o700
    assert load_secret_key() == secret
    assert load_public_key() == secret.public_key()
    assert (
        (_isolated_signing_keys / PUBLIC_NAME)
        .read_text()
        .startswith("untrusted comment: minisign public key")
    )


def test_keygen_refuses_to_overwrite_without_force(_isolated_signing_keys: Path, secret: SecretKey) -> None:
    with pytest.raises(SigningError, match="already exists"):
        generate_keypair()
    replaced = generate_keypair(force=True)
    assert replaced.key_id != secret.key_id


def test_no_key_means_no_signing(_isolated_signing_keys: Path) -> None:
    assert load_secret_key() is None
    assert prepare_signing(True) == (None, None)


def test_disabled_signing_ignores_existing_key(secret: SecretKey) -> None:
    assert prepare_signing(False) == (None, None)


def test_corrupt_secret_key_is_reported(_isolated_signing_keys: Path) -> None:
    (_isolated_signing_keys / SECRET_NAME).write_text("definitely not a key")
    key, block = prepare_signing(True)
    assert key is None
    assert "not a webdamga key" in block["error"]


def test_load_public_key_accepts_file_dir_or_text(secret: SecretKey, tmp_path: Path) -> None:
    public = secret.public_key()
    pub_file = tmp_path / "someone.pub"
    pub_file.write_text(public.to_minisign())
    assert load_public_key(pub_file) == public
    assert load_public_key(public.base64) == public
    assert load_public_key(tmp_path / "empty-dir-without-key") is None


# ----------------------------------------------------------- yakalama akışı


def _capture_dir(tmp_path: Path) -> tuple[Path, dict]:
    folder = tmp_path / "captures" / "cap-1"
    folder.mkdir(parents=True)
    (folder / "dom.html").write_text("<html>orijinal</html>")
    (folder / "screenshot.png").write_bytes(b"\x89PNG")
    meta = {
        "capture_id": "cap-1",
        "requested_url": "https://example.com",
        "completed_at_utc": "2026-01-01T00:00:00Z",
    }
    return folder, meta


def test_sealed_capture_is_signed_and_verifies(secret: SecretKey, tmp_path: Path) -> None:
    folder, meta = _capture_dir(tmp_path)
    key, block = prepare_signing(True)
    meta["signing"] = block
    (folder / "metadata.json").write_text(json.dumps(meta))

    sealed = seal_capture(folder, meta, key)
    assert sealed["signature"] == SIGNATURE_NAME
    assert block["key_id"] == secret.id

    result = verify_capture(folder)
    assert result["ok"] is True
    assert result["signature"]["ok"] is True
    assert "capture:cap-1" in result["signature"]["trusted_comment"]
    # İmza dosyası "listede yok" sayılmamalı.
    assert all(f["status"] == "ok" for f in result["files"])


def test_regenerated_manifest_is_caught_only_by_the_signature(secret: SecretKey, tmp_path: Path) -> None:
    """Checksum'lar yeniden üretilince SHA-256 kontrolü geçer; imza geçmemeli."""
    folder, meta = _capture_dir(tmp_path)
    seal_capture(folder, meta, load_secret_key())

    (folder / "dom.html").write_text("<html>bu site masummuş</html>")
    write_manifest(folder, build_manifest(folder, tool="attacker", tool_version="1", meta=meta))

    result = verify_capture(folder)
    assert all(f["status"] == "ok" for f in result["files"])
    assert result["sidecar_ok"] is True
    assert result["signature"]["ok"] is False
    assert result["ok"] is False


def test_signature_without_available_public_key_does_not_fail_verification(
    secret: SecretKey, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, meta = _capture_dir(tmp_path)
    seal_capture(folder, meta, secret)
    monkeypatch.setenv("WEBDAMGA_KEY_DIR", str(tmp_path / "recipient-has-no-keys"))

    result = verify_capture(folder)
    assert result["ok"] is True
    assert result["signature"]["present"] is True
    assert result["signature"]["ok"] is None
    assert result["signature"]["key_id"] == secret.id

    explicit = verify_capture(folder, secret.public_key())
    assert explicit["signature"]["ok"] is True


# ------------------------------------------------------------------- paket


def test_signed_package_ships_public_key_and_instructions(secret: SecretKey, tmp_path: Path) -> None:
    folder, meta = _capture_dir(tmp_path)
    _, block = prepare_signing(True)
    meta["signing"] = block
    (folder / "metadata.json").write_text(json.dumps(meta))
    seal_capture(folder, meta, secret)

    out, _ = build_package(folder, meta, tmp_path / "pkg.zip", "en")
    with zipfile.ZipFile(out) as zf:
        names = {n.split("/", 1)[1] for n in zf.namelist()}
        readme = zf.read(f"cap-1/{'README.txt'}").decode()
        pub = zf.read(f"cap-1/{SIGNER_PUB}").decode()

    assert {SIGNATURE_NAME, SIGNER_PUB} <= names
    assert PublicKey.parse(pub) == secret.public_key()
    assert "minisign -Vm manifest.json -p signer.pub" in readme
    # PDF verilmedi: paketleme dosyaları README.txt ve signer.pub.
    assert "README.txt and signer.pub were created while packaging" in " ".join(readme.split())
    assert "{" not in readme


def test_unsigned_package_has_no_signature_section(tmp_path: Path) -> None:
    folder, meta = _capture_dir(tmp_path)
    seal_capture(folder, meta, None)
    for lang in ("en", "tr"):
        readme = build_readme(meta, lang, signature=None)
        assert "minisign" not in readme
        assert "{" not in readme


@pytest.mark.skipif(shutil.which("minisign") is None, reason="minisign is not installed")
def test_real_minisign_accepts_webdamga_signature(secret: SecretKey, tmp_path: Path) -> None:
    folder, meta = _capture_dir(tmp_path)
    seal_capture(folder, meta, secret)
    public_file = tmp_path / "signer.pub"
    public_file.write_text(secret.public_key().to_minisign())

    ok = subprocess.run(
        ["minisign", "-Vm", str(folder / "manifest.json"), "-p", str(public_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0, ok.stderr

    (folder / "manifest.json").write_bytes((folder / "manifest.json").read_bytes() + b" ")
    tampered = subprocess.run(
        ["minisign", "-Vm", str(folder / "manifest.json"), "-P", secret.public_key().base64],
        capture_output=True,
        check=False,
    )
    assert tampered.returncode != 0
