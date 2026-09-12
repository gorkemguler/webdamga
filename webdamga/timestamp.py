"""Güvenilir zaman damgası: manifestonun belirli bir anda var olduğunun kanıtı.

İmza "kim mühürledi" sorusunu cevaplar ama zamanı yakalayanın kendi saati
söyler; saat geri alınabilir. Zaman damgası bunu üçüncü bir tarafa bağlar.
İki bağımsız yol birlikte kullanılabilir:

RFC 3161
    Bir zaman damgası otoritesi (TSA) manifestonun SHA-256 özetini ve o anki
    zamanı imzalar. Varsayılan DigiCert'in herkese açık TSA'sıdır; token'ı
    işletim sisteminin standart kök sertifikalarıyla doğrulanır:

        openssl ts -verify -data manifest.json -in manifest.json.tsr -CAfile /etc/ssl/cert.pem

OpenTimestamps
    Özet, Bitcoin blok zincirine bağlanmak üzere birden çok takvim sunucusuna
    gönderilir. Tek bir kuruma güven gerektirmez ama onay birkaç saat sürer;
    ilk dosya "bekliyor" durumundadır, sonradan resmi istemciyle yükseltilir:

        ots upgrade manifest.json.ots && ots verify manifest.json.ots

Her iki durumda da dışarıya yalnızca manifestonun özeti gider; URL, içerik
ya da yakalamayla ilgili başka hiçbir bilgi gönderilmez.

Bu modül token'ları yapısal olarak kendisi çözer (durum, zaman, özet ve
nonce eşleşmesi). TSA imzasının ve sertifika zincirinin kriptografik
doğrulaması için sistemde `openssl` varsa onu çağırır, yoksa bunu açıkça
"kontrol edilmedi" olarak raporlar.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import os
import secrets
import shutil
import ssl
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .hashing import MANIFEST_NAME, OTS_NAME, RFC3161_NAME

DEFAULT_TSA_URL = "http://timestamp.digicert.com"
DEFAULT_OTS_CALENDARS = (
    "https://a.pool.opentimestamps.org",
    "https://b.pool.opentimestamps.org",
    "https://ots.btc.catallaxy.com",
)

_USER_AGENT = f"webdamga/{__version__}"


class TimestampError(ValueError):
    """Zaman damgası alınamadı ya da okunamadı."""


def tsa_url() -> str:
    return os.environ.get("WEBDAMGA_TSA_URL") or DEFAULT_TSA_URL


def ots_calendars() -> tuple[str, ...]:
    env = os.environ.get("WEBDAMGA_OTS_CALENDARS")
    if env:
        return tuple(c.strip().rstrip("/") for c in env.split(",") if c.strip())
    return DEFAULT_OTS_CALENDARS


# ================================================================== DER yardımcıları


def _der_length(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _der_length(len(content)) + content


def _der_uint(value: int) -> bytes:
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return _tlv(0x02, raw)


class _Node:
    __slots__ = ("constructed", "tag", "value")

    def __init__(self, tag: int, value: bytes) -> None:
        self.tag = tag
        self.value = value
        self.constructed = bool(tag & 0x20)

    def children(self) -> list[_Node]:
        return _der_parse_all(self.value)

    def as_int(self) -> int:
        return int.from_bytes(self.value, "big", signed=True)


def _der_parse_one(data: bytes, offset: int) -> tuple[_Node, int]:
    if offset + 2 > len(data):
        raise TimestampError("truncated DER data")
    tag = data[offset]
    if tag & 0x1F == 0x1F:
        raise TimestampError("multi-byte DER tags are not supported")
    length = data[offset + 1]
    pos = offset + 2
    if length == 0x80:
        raise TimestampError("indefinite-length (BER) encoding is not supported")
    if length & 0x80:
        count = length & 0x7F
        if count > 4 or pos + count > len(data):
            raise TimestampError("invalid DER length")
        length = int.from_bytes(data[pos : pos + count], "big")
        pos += count
    end = pos + length
    if end > len(data):
        raise TimestampError("DER element runs past the end of the data")
    return _Node(tag, data[pos:end]), end


def _der_parse_all(data: bytes) -> list[_Node]:
    nodes, offset = [], 0
    while offset < len(data):
        node, offset = _der_parse_one(data, offset)
        nodes.append(node)
    return nodes


def _oid(value: bytes) -> str:
    if not value:
        return ""
    parts = [value[0] // 40, value[0] % 40]
    acc = 0
    for byte in value[1:]:
        acc = (acc << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(acc)
            acc = 0
    return ".".join(str(p) for p in parts)


# ======================================================================= RFC 3161

_SHA256_ALGORITHM = _tlv(0x30, bytes.fromhex("0609608648016503040201") + b"\x05\x00")
_OID_SIGNED_DATA = "1.2.840.113549.1.7.2"
_OID_TST_INFO = "1.2.840.113549.1.9.16.1.4"
_OID_SHA256 = "2.16.840.1.101.3.4.2.1"
_PKI_STATUS = {
    0: "granted",
    1: "grantedWithMods",
    2: "rejection",
    3: "waiting",
    4: "revocationWarning",
    5: "revocationNotification",
}


def build_tsq(digest: bytes, nonce: int) -> bytes:
    """SHA-256 özeti için DER kodlu TimeStampReq (certReq=true)."""
    if len(digest) != 32:
        raise TimestampError("expected a SHA-256 digest")
    imprint = _tlv(0x30, _SHA256_ALGORITHM + _tlv(0x04, digest))
    return _tlv(0x30, _der_uint(1) + imprint + _der_uint(nonce) + b"\x01\x01\xff")


def _generalized_time(raw: bytes) -> str:
    text = raw.decode("ascii").rstrip("Z")
    main, _, fraction = text.partition(".")
    moment = datetime.strptime(main, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    iso = moment.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{iso}.{fraction}Z" if fraction else f"{iso}Z"


def parse_tsr(tsr: bytes) -> dict:
    """TimeStampResp'i çözer; bozuksa TimestampError."""
    try:
        (response,) = _der_parse_all(tsr)
        parts = response.children()
        status_info = parts[0].children()
        status_code = status_info[0].as_int()
        result: dict = {
            "status": _PKI_STATUS.get(status_code, str(status_code)),
            "granted": status_code in (0, 1),
        }
        if not result["granted"] or len(parts) < 2:
            return result

        content_info = parts[1].children()
        if _oid(content_info[0].value) != _OID_SIGNED_DATA:
            raise TimestampError("time stamp token is not CMS SignedData")
        signed_data = content_info[1].children()[0].children()
        encap = signed_data[2].children()
        if _oid(encap[0].value) != _OID_TST_INFO:
            raise TimestampError("token does not contain TSTInfo")
        tst_info_der = encap[1].children()[0].value
        fields = _der_parse_all(tst_info_der)[0].children()

        imprint = fields[2].children()
        algorithm = _oid(imprint[0].children()[0].value)
        result.update(
            {
                "policy": _oid(fields[1].value),
                "hash_algorithm": "sha256" if algorithm == _OID_SHA256 else algorithm,
                "imprint": imprint[1].value.hex(),
                "serial": format(fields[3].as_int(), "x"),
                "gen_time": _generalized_time(fields[4].value),
                "nonce": None,
            }
        )
        for field in fields[5:]:
            if field.tag == 0x02:  # accuracy bir SEQUENCE, ordering BOOLEAN; tek INTEGER nonce
                result["nonce"] = field.as_int()
        return result
    except TimestampError:
        raise
    except (ValueError, IndexError, UnicodeDecodeError) as exc:
        raise TimestampError(f"malformed time stamp response: {exc}") from exc


def check_tsr(data: bytes, tsr: bytes, expected_nonce: int | None = None) -> dict:
    """Token'ın bu veriye ait olduğunu yapısal olarak doğrular (TSA imzası hariç)."""
    try:
        info = parse_tsr(tsr)
    except TimestampError as exc:
        return {"ok": False, "error": str(exc)}
    if not info["granted"]:
        return {"ok": False, **info, "error": f"TSA did not grant the request ({info['status']})"}
    if info["hash_algorithm"] != "sha256":
        return {"ok": False, **info, "error": f"unexpected hash algorithm {info['hash_algorithm']}"}
    if info["imprint"] != hashlib.sha256(data).hexdigest():
        return {"ok": False, **info, "error": "token was issued for different data"}
    if expected_nonce is not None and info["nonce"] != expected_nonce:
        return {"ok": False, **info, "error": "nonce mismatch, the response does not answer our request"}
    return {"ok": True, **info}


def request_rfc3161(data: bytes, url: str | None = None, *, timeout: float = 20.0) -> bytes:
    url = url or tsa_url()
    nonce = secrets.randbits(63)
    query = build_tsq(hashlib.sha256(data).digest(), nonce)
    request = urllib.request.Request(
        url,
        data=query,
        headers={"Content-Type": "application/timestamp-query", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply = response.read()
    except OSError as exc:
        raise TimestampError(f"TSA {url} unreachable: {exc}") from exc
    checked = check_tsr(data, reply, nonce)
    if not checked["ok"]:
        raise TimestampError(f"TSA {url}: {checked['error']}")
    return reply


def _ca_bundle() -> str | None:
    candidates = [
        os.environ.get("WEBDAMGA_TSA_CA"),
        ssl.get_default_verify_paths().cafile,
        "/etc/ssl/cert.pem",
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ]
    return next((c for c in candidates if c and Path(c).is_file()), None)


def openssl_verify(data_path: Path, tsr_path: Path) -> dict:
    """TSA imzasını ve sertifika zincirini openssl ile doğrular.

    {"verified": True|False|None, "detail": ...}; None = kontrol edilemedi.
    """
    binary = shutil.which("openssl")
    ca = _ca_bundle()
    if binary is None or ca is None:
        reason = "openssl not found" if binary is None else "no CA bundle found (set WEBDAMGA_TSA_CA)"
        return {"verified": None, "detail": reason}
    try:
        run = subprocess.run(
            [binary, "ts", "-verify", "-data", str(data_path), "-in", str(tsr_path), "-CAfile", ca],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"verified": None, "detail": str(exc)}
    output = (run.stdout + run.stderr).strip()
    if "Verification: OK" in output:
        return {"verified": True, "detail": "Verification: OK", "ca_file": ca}
    last = output.splitlines()[-1] if output else f"exit code {run.returncode}"
    return {"verified": False, "detail": last, "ca_file": ca}


# ================================================================== OpenTimestamps

OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
_OTS_SHA256, _OTS_APPEND, _OTS_FORK, _OTS_ATTESTATION = 0x08, 0xF0, 0xFF, 0x00
_UNARY_OPS = {
    0x02: "sha1",
    0x03: "ripemd160",
    0x08: "sha256",
    0x67: "keccak256",
    0xF2: "reverse",
    0xF3: "hexlify",
}
_BINARY_OPS = {0xF0: "append", 0xF1: "prepend"}
_PENDING_TAG = bytes.fromhex("83dfe30d2ef90c8e")
_BITCOIN_TAG = bytes.fromhex("0588960d73d71901")


def _varuint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _read_varuint(data: bytes, pos: int) -> tuple[int, int]:
    value, shift = 0, 0
    while True:
        if pos >= len(data):
            raise TimestampError("truncated varuint")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise TimestampError("varuint too long")


def _read_varbytes(data: bytes, pos: int) -> tuple[bytes, int]:
    length, pos = _read_varuint(data, pos)
    if pos + length > len(data):
        raise TimestampError("truncated varbytes")
    return data[pos : pos + length], pos + length


def _submit_calendar(calendar: str, commitment: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(
        f"{calendar.rstrip('/')}/digest",
        data=commitment,
        headers={"Accept": "application/vnd.opentimestamps.v1", "User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    if not body:
        raise TimestampError("empty response")
    return body


def stamp_ots(
    digest: bytes, calendars: tuple[str, ...] | None = None, *, timeout: float = 15.0
) -> tuple[bytes, dict]:
    """Özeti takvimlere gönderir ve .ots dosyası üretir.

    Her takvime ayrı rastgele bir nonce ile gidilir; böylece hiçbir takvim
    diğerinin cevabını birleştirmek zorunda kalmaz ve dosya, resmi istemcinin
    okuyabildiği sade bir çatal (fork) yapısında olur. En az bir takvim cevap
    vermezse TimestampError.
    """
    calendars = calendars or ots_calendars()
    if len(digest) != 32:
        raise TimestampError("expected a SHA-256 digest")

    jobs = {cal: secrets.token_bytes(16) for cal in calendars}
    branches: list[tuple[bytes, bytes]] = []
    errors: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs) or 1) as pool:
        futures = {
            pool.submit(_submit_calendar, cal, hashlib.sha256(digest + nonce).digest(), timeout): (cal, nonce)
            for cal, nonce in jobs.items()
        }
        for future in concurrent.futures.as_completed(futures):
            cal, nonce = futures[future]
            try:
                branches.append((nonce, future.result()))
            except Exception as exc:  # noqa: BLE001 - tek takvimin düşmesi yeterli sebep değil
                errors[cal] = str(exc)

    if not branches:
        raise TimestampError(f"no OpenTimestamps calendar answered: {errors}")

    branches.sort(key=lambda branch: branch[0])  # istemcinin kanonik sırası: append argümanına göre
    node = b"".join(
        (bytes([_OTS_FORK]) if index < len(branches) - 1 else b"")
        + bytes([_OTS_APPEND])
        + _varuint(len(nonce))
        + nonce
        + bytes([_OTS_SHA256])
        + reply
        for index, (nonce, reply) in enumerate(branches)
    )
    ots = OTS_MAGIC + _varuint(1) + bytes([_OTS_SHA256]) + digest + node
    return ots, {"calendars": len(branches), "failed": errors}


def parse_ots(data: bytes) -> dict:
    """.ots dosyasını çözer: hangi özete ait olduğu ve tasdik (attestation) listesi."""
    if not data.startswith(OTS_MAGIC):
        raise TimestampError("not an OpenTimestamps proof")
    pos = len(OTS_MAGIC)
    version, pos = _read_varuint(data, pos)
    if version != 1:
        raise TimestampError(f"unsupported OpenTimestamps version {version}")
    if pos >= len(data) or data[pos] != _OTS_SHA256:
        raise TimestampError("only sha256 file hashes are supported")
    pos += 1
    digest = data[pos : pos + 32]
    if len(digest) != 32:
        raise TimestampError("truncated file digest")
    pos += 32

    attestations: list[dict] = []

    def walk(pos: int, depth: int) -> int:
        if depth > 256:
            raise TimestampError("proof is nested too deeply")
        while True:
            if pos >= len(data):
                raise TimestampError("truncated proof")
            tag = data[pos]
            pos += 1
            more = tag == _OTS_FORK
            if more:
                if pos >= len(data):
                    raise TimestampError("truncated proof")
                tag = data[pos]
                pos += 1
            if tag == _OTS_ATTESTATION:
                kind = data[pos : pos + 8]
                payload, pos = _read_varbytes(data, pos + 8)
                if kind == _PENDING_TAG:
                    uri, _ = _read_varbytes(payload, 0)
                    attestations.append({"type": "pending", "calendar": uri.decode("utf-8", "replace")})
                elif kind == _BITCOIN_TAG:
                    height, _ = _read_varuint(payload, 0)
                    attestations.append({"type": "bitcoin", "block_height": height})
                else:
                    attestations.append({"type": "unknown", "tag": kind.hex()})
            elif tag in _BINARY_OPS:
                _, pos = _read_varbytes(data, pos)
                pos = walk(pos, depth + 1)
            elif tag in _UNARY_OPS:
                pos = walk(pos, depth + 1)
            else:
                raise TimestampError(f"unknown OpenTimestamps operation 0x{tag:02x}")
            if not more:
                return pos

    end = walk(pos, 0)
    if end != len(data):
        raise TimestampError("trailing data after proof")
    return {"digest": digest.hex(), "attestations": attestations}


def check_ots(data: bytes, ots: bytes) -> dict:
    try:
        info = parse_ots(ots)
    except TimestampError as exc:
        return {"ok": False, "error": str(exc)}
    if info["digest"] != hashlib.sha256(data).hexdigest():
        return {"ok": False, **info, "error": "proof was made for different data"}
    confirmed = [a for a in info["attestations"] if a["type"] == "bitcoin"]
    return {
        "ok": True,
        **info,
        "state": "confirmed" if confirmed else "pending",
        "pending_calendars": [a["calendar"] for a in info["attestations"] if a["type"] == "pending"],
    }


# ======================================================================= yakalama


def timestamp_capture(
    capture_dir: Path,
    *,
    rfc3161: bool = True,
    opentimestamps: bool = True,
    tsa: str | None = None,
    calendars: tuple[str, ...] | None = None,
) -> dict:
    """manifest.json için zaman damgalarını alır ve yanına yazar.

    Ağ hataları yakalamayı bozmaz; sonuç sözlüğünde raporlanır.
    """
    capture_dir = Path(capture_dir)
    manifest = (capture_dir / MANIFEST_NAME).read_bytes()
    result: dict = {}

    if rfc3161:
        url = tsa or tsa_url()
        try:
            reply = request_rfc3161(manifest, url)
            (capture_dir / RFC3161_NAME).write_bytes(reply)
            info = parse_tsr(reply)
            result["rfc3161"] = {"ok": True, "tsa": url, "gen_time": info["gen_time"], "file": RFC3161_NAME}
        except TimestampError as exc:
            result["rfc3161"] = {"ok": False, "tsa": url, "error": str(exc)}

    if opentimestamps:
        try:
            proof, summary = stamp_ots(hashlib.sha256(manifest).digest(), calendars)
            (capture_dir / OTS_NAME).write_bytes(proof)
            result["opentimestamps"] = {"ok": True, "state": "pending", "file": OTS_NAME, **summary}
        except TimestampError as exc:
            result["opentimestamps"] = {"ok": False, "error": str(exc)}

    return result


def inspect_timestamps(capture_dir: Path, *, run_openssl: bool = True) -> dict:
    """Klasördeki zaman damgalarını mevcut manifest.json'a karşı kontrol eder."""
    capture_dir = Path(capture_dir)
    manifest_path = capture_dir / MANIFEST_NAME
    manifest = manifest_path.read_bytes() if manifest_path.is_file() else b""
    out: dict = {}

    tsr_path = capture_dir / RFC3161_NAME
    if tsr_path.is_file():
        entry = check_tsr(manifest, tsr_path.read_bytes())
        entry["present"] = True
        if entry["ok"] and run_openssl:
            entry["tsa_signature"] = openssl_verify(manifest_path, tsr_path)
        out["rfc3161"] = entry
    else:
        out["rfc3161"] = {"present": False}

    ots_path = capture_dir / OTS_NAME
    if ots_path.is_file():
        entry = check_ots(manifest, ots_path.read_bytes())
        entry["present"] = True
        out["opentimestamps"] = entry
    else:
        out["opentimestamps"] = {"present": False}
    return out
