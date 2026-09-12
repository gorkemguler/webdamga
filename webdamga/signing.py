"""Manifestoyu Ed25519 ile imzalama, minisign ile uyumlu biçimde.

SHA-256 manifestosu bir klasörün sonradan değiştirilmediğini gösterir ama
kimin ürettiğini göstermez: dosyaları değiştiren biri manifestoyu da yeniden
üretebilir. İmza bu boşluğu kapatır; manifestoya dokunan herkes imzayı bozar
ve yeni imzayı ancak gizli anahtar sahibi üretebilir.

Üretilen `manifest.json.minisig` ve public key, minisign aracıyla birebir
doğrulanabilir; alıcının webdamga kurmasına gerek yoktur:

    minisign -Vm manifest.json -P <public key>

İmza "önceden özetlenmiş" (ED) biçimdedir: Ed25519(BLAKE2b-512(dosya)).
Güvenilir yorum (trusted comment) imzanın kapsamındadır; yakalama kimliğini
ve imza zamanını taşır, sonradan değiştirilemez.

Gizli anahtar webdamga'nın kendi basit biçiminde, şifrelenmeden ve 0600
izniyle saklanır; kuyruk ve izleme işlerinin gözetimsiz imzalayabilmesi için.
Anahtar dizini: WEBDAMGA_KEY_DIR ya da ~/.config/webdamga/keys.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PUBLIC_NAME = "webdamga.pub"
SECRET_NAME = "webdamga.key"
SIG_SUFFIX = ".minisig"

_PUB_ALG = b"Ed"
_SIG_PREHASHED = b"ED"
_SIG_LEGACY = b"Ed"


class SigningError(ValueError):
    """Anahtar ya da imza okunamadı / geçersiz."""


def default_key_dir() -> Path:
    env = os.environ.get("WEBDAMGA_KEY_DIR")
    return Path(env) if env else Path.home() / ".config" / "webdamga" / "keys"


def _display_id(key_id: bytes) -> str:
    # minisign anahtar kimliğini küçük-endian u64 olarak, büyük harf hex gösterir.
    return key_id[::-1].hex().upper()


def _raw_public(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


@dataclass(frozen=True, slots=True)
class PublicKey:
    key_id: bytes
    raw: bytes

    @property
    def id(self) -> str:
        return _display_id(self.key_id)

    @property
    def base64(self) -> str:
        return base64.b64encode(_PUB_ALG + self.key_id + self.raw).decode("ascii")

    def to_minisign(self) -> str:
        return f"untrusted comment: minisign public key {self.id}\n{self.base64}\n"

    @classmethod
    def parse(cls, text: str) -> PublicKey:
        """minisign .pub dosyası içeriği ya da yalnızca base64 satırı."""
        lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
        candidate = lines[-1] if lines else ""
        try:
            blob = base64.b64decode(candidate, validate=True)
        except ValueError as exc:
            raise SigningError("public key is not valid base64") from exc
        if len(blob) != 42 or blob[:2] != _PUB_ALG:
            raise SigningError("not a minisign Ed25519 public key")
        return cls(key_id=blob[2:10], raw=blob[10:])

    def _crypto(self) -> Ed25519PublicKey:
        return Ed25519PublicKey.from_public_bytes(self.raw)


@dataclass(frozen=True, slots=True)
class SecretKey:
    key_id: bytes
    seed: bytes

    @property
    def id(self) -> str:
        return _display_id(self.key_id)

    def _crypto(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(self.seed)

    def public_key(self) -> PublicKey:
        return PublicKey(self.key_id, _raw_public(self._crypto().public_key()))

    def serialize(self) -> str:
        return (
            json.dumps(
                {
                    "format": "webdamga-ed25519-secret-key",
                    "version": 1,
                    "key_id": self.key_id.hex(),
                    "seed": base64.b64encode(self.seed).decode("ascii"),
                },
                indent=2,
            )
            + "\n"
        )

    @classmethod
    def parse(cls, text: str) -> SecretKey:
        try:
            data = json.loads(text)
            key_id, seed = bytes.fromhex(data["key_id"]), base64.b64decode(data["seed"])
        except (ValueError, KeyError, TypeError) as exc:
            raise SigningError("secret key file is not a webdamga key") from exc
        if data.get("format") != "webdamga-ed25519-secret-key" or len(key_id) != 8 or len(seed) != 32:
            raise SigningError("secret key file is not a webdamga key")
        return cls(key_id, seed)

    def sign(self, message: bytes) -> bytes:
        return self._crypto().sign(message)


# ----------------------------------------------------------------------- anahtarlar


def generate_keypair(key_dir: Path | None = None, *, force: bool = False) -> SecretKey:
    key_dir = Path(key_dir) if key_dir else default_key_dir()
    secret_path, public_path = key_dir / SECRET_NAME, key_dir / PUBLIC_NAME
    if secret_path.exists() and not force:
        raise SigningError(f"a signing key already exists at {secret_path}")

    key_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(key_dir, 0o700)
    secret = SecretKey(key_id=secrets.token_bytes(8), seed=secrets.token_bytes(32))

    # Gizli anahtar hiçbir an başkalarınca okunabilir olmasın diye 0600 ile açılıyor.
    fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(secret.serialize())
    os.chmod(secret_path, 0o600)
    public_path.write_text(secret.public_key().to_minisign(), encoding="utf-8")
    return secret


def load_secret_key(key_dir: Path | None = None) -> SecretKey | None:
    path = (Path(key_dir) if key_dir else default_key_dir()) / SECRET_NAME
    if not path.is_file():
        return None
    return SecretKey.parse(path.read_text(encoding="utf-8"))


def load_public_key(source: Path | str | None = None) -> PublicKey | None:
    """Bir .pub dosyası, anahtar dizini ya da base64 anahtar metni."""
    if source is None:
        source = default_key_dir()
    if isinstance(source, str) and not Path(source).exists():
        return PublicKey.parse(source)
    path = Path(source)
    if path.is_dir():
        path = path / PUBLIC_NAME
    if not path.is_file():
        return None
    return PublicKey.parse(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------ imzalama


def sign_bytes(message: bytes, secret: SecretKey, trusted_comment: str) -> str:
    """minisign .minisig dosyası içeriğini döner."""
    if "\n" in trusted_comment or "\r" in trusted_comment:
        raise SigningError("trusted comment must be a single line")
    signature = secret.sign(hashlib.blake2b(message, digest_size=64).digest())
    comment = trusted_comment.encode("utf-8")
    global_signature = secret.sign(signature + comment)
    return (
        f"untrusted comment: signature from webdamga key {secret.id}\n"
        f"{base64.b64encode(_SIG_PREHASHED + secret.key_id + signature).decode('ascii')}\n"
        f"trusted comment: {trusted_comment}\n"
        f"{base64.b64encode(global_signature).decode('ascii')}\n"
    )


def sign_file(path: Path, secret: SecretKey, trusted_comment: str) -> Path:
    path = Path(path)
    sig_path = path.with_name(path.name + SIG_SUFFIX)
    sig_path.write_text(sign_bytes(path.read_bytes(), secret, trusted_comment), encoding="utf-8")
    return sig_path


@dataclass(frozen=True, slots=True)
class Verification:
    ok: bool
    key_id: str | None = None
    trusted_comment: str | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "key_id": self.key_id,
            "trusted_comment": self.trusted_comment,
            "error": self.error,
        }


def parse_signature(text: str) -> tuple[bytes, bytes, bytes, str, bytes]:
    """(algoritma, key_id, imza, güvenilir yorum, global imza)."""
    lines = text.splitlines()
    if len(lines) < 4 or not lines[2].startswith("trusted comment: "):
        raise SigningError("not a minisign signature file")
    try:
        blob = base64.b64decode(lines[1].strip(), validate=True)
        global_signature = base64.b64decode(lines[3].strip(), validate=True)
    except ValueError as exc:
        raise SigningError("signature is not valid base64") from exc
    if len(blob) != 74 or blob[:2] not in (_SIG_PREHASHED, _SIG_LEGACY) or len(global_signature) != 64:
        raise SigningError("unsupported minisign signature")
    return blob[:2], blob[2:10], blob[10:], lines[2][len("trusted comment: ") :], global_signature


def verify_bytes(message: bytes, signature_text: str, public: PublicKey) -> Verification:
    try:
        algorithm, key_id, signature, comment, global_signature = parse_signature(signature_text)
    except SigningError as exc:
        return Verification(False, error=str(exc))

    if key_id != public.key_id:
        return Verification(
            False,
            key_id=_display_id(key_id),
            trusted_comment=comment,
            error=f"signed by key {_display_id(key_id)}, not {public.id}",
        )
    signed = hashlib.blake2b(message, digest_size=64).digest() if algorithm == _SIG_PREHASHED else message
    try:
        public._crypto().verify(signature, signed)
    except InvalidSignature:
        return Verification(False, public.id, comment, "signature does not match the file")
    try:
        public._crypto().verify(global_signature, signature + comment.encode("utf-8"))
    except InvalidSignature:
        return Verification(False, public.id, comment, "trusted comment has been altered")
    return Verification(True, public.id, comment)


def verify_file(path: Path, public: PublicKey, sig_path: Path | None = None) -> Verification:
    path = Path(path)
    sig_path = Path(sig_path) if sig_path else path.with_name(path.name + SIG_SUFFIX)
    if not sig_path.is_file():
        return Verification(False, error="no signature file")
    return verify_bytes(path.read_bytes(), sig_path.read_text(encoding="utf-8"), public)
