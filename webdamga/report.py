"""Gönderilebilir kanıt çıktıları: PDF rapor ve ZIP paketi.

Amaç, bir yakalamayı ihbar ekine koyulabilecek tek bir dosyaya indirmek.
Paket, yakalama klasörünün tamamını, insan okur bir PDF özeti ve karşı
tarafın webdamga kurmadan doğrulama yapabilmesi için bir README.txt içerir.
"""

from __future__ import annotations

import base64
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__
from .hashing import MANIFEST_NAME, MANIFEST_SIDECAR, SIGNATURE_NAME, sha256_bytes, sha256_file
from .i18n import DEFAULT_LANG, t, translator
from .signing import SigningError, parse_signature
from .timestamp import inspect_timestamps

REPORT_NAME = "evidence-report.pdf"
PACKAGE_README = "README.txt"
SIGNER_PUB = "signer.pub"

# ZIP girdilerinin tarihleri sabit tutulur ki paket, dosyaların yerel diskteki
# değişiklik zamanlarını sızdırmasın. Paket yine de her üretildiğinde farklı
# bir özete sahip olabilir: README.txt paketleme zamanını, PDF üretim zamanını
# taşır. Bu yüzden kayda geçirilmesi gereken, gönderim anındaki paket özetidir.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "web" / "templates")),
    autoescape=select_autoescape(["html"]),
)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _data_uri(path: Path) -> str | None:
    if not path.is_file():
        return None
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _manifest_sha256(capture_dir: Path) -> str | None:
    sidecar = capture_dir / MANIFEST_SIDECAR
    if sidecar.is_file():
        return sidecar.read_text(encoding="utf-8").split()[0]
    manifest = capture_dir / MANIFEST_NAME
    return sha256_file(manifest) if manifest.is_file() else None


def signature_info(capture_dir: Path, meta: dict) -> dict | None:
    """Klasörde imza varsa anahtar kimliği, güvenilir yorum ve public key."""
    sig_path = Path(capture_dir) / SIGNATURE_NAME
    if not sig_path.is_file():
        return None
    try:
        _, key_id, _, comment, _ = parse_signature(sig_path.read_text(encoding="utf-8"))
    except SigningError:
        return None
    signing = meta.get("signing") or {}
    key_hex = key_id[::-1].hex().upper()
    public = signing.get("public_key") if signing.get("key_id") == key_hex else None
    return {"key_id": key_hex, "trusted_comment": comment, "public_key": public}


def _signer_pub_file(info: dict) -> str | None:
    if not info or not info.get("public_key"):
        return None
    return f"untrusted comment: minisign public key {info['key_id']}\n{info['public_key']}\n"


def build_report_html(capture_dir: Path, meta: dict, manifest: dict, lang: str = DEFAULT_LANG) -> str:
    """PDF'e basılacak raporun HTML'ini üretir."""
    # Rapora ekran üstü görüntüyü gömüyoruz; tam sayfa görüntü çok büyük
    # olabildiği için pakette ayrı dosya olarak kalıyor.
    screenshot = _data_uri(capture_dir / "screenshot-viewport.png") or _data_uri(
        capture_dir / "screenshot.png"
    )
    return _env.get_template("report.html").render(
        m=meta,
        manifest=manifest,
        lang=lang,
        _=translator(lang),
        version=__version__,
        screenshot=screenshot,
        generated_utc=_now_iso(),
        manifest_sha256=_manifest_sha256(capture_dir),
        signature=signature_info(capture_dir, meta),
        timestamps=inspect_timestamps(capture_dir, run_openssl=False),
    )


async def render_report_pdf(capture_dir: Path, meta: dict, manifest: dict, lang: str = DEFAULT_LANG) -> bytes:
    """Raporu Chromium ile PDF'e basar."""
    from playwright.async_api import async_playwright

    html = build_report_html(capture_dir, meta, manifest, lang)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html, wait_until="load")
        pdf = await page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"},
        )
        await browser.close()
    return pdf


def _timestamp_section(timestamps: dict | None, lang: str) -> str:
    if not timestamps:
        return ""
    rfc = timestamps.get("rfc3161") or {}
    ots = timestamps.get("opentimestamps") or {}
    rfc_text = t("pkg.readme.rfc3161", lang, time=rfc["gen_time"]) if rfc.get("ok") else ""
    ots_text = t("pkg.readme.ots", lang) if ots.get("ok") else ""
    if not (rfc_text or ots_text):
        return ""
    return t("pkg.readme.timestamps", lang, rfc3161=rfc_text, ots=ots_text)


def build_readme(
    meta: dict,
    lang: str = DEFAULT_LANG,
    *,
    signature: dict | None = None,
    pdf: bool = True,
    timestamps: dict | None = None,
) -> str:
    packaging = [PACKAGE_README] + ([REPORT_NAME] if pdf else [])
    section = ""
    if signature:
        section = t("pkg.readme.signature", lang, key_id=signature["key_id"])
        if signature.get("public_key"):
            packaging.append(SIGNER_PUB)
    joiner = " ve " if lang == "tr" else " and "
    files = ", ".join(packaging[:-1]) + joiner + packaging[-1] if len(packaging) > 1 else packaging[0]
    return t(
        "pkg.readme",
        lang,
        capture_id=meta.get("capture_id", "?"),
        url=meta.get("final_url") or meta.get("requested_url", "?"),
        captured=meta.get("completed_at_utc", "?"),
        packaged=_now_iso(),
        version=__version__,
        signature_section=section,
        timestamp_section=_timestamp_section(timestamps, lang),
        packaging_files=files,
    )


def build_package(
    capture_dir: Path,
    meta: dict,
    out_path: Path,
    lang: str = DEFAULT_LANG,
    pdf_bytes: bytes | None = None,
) -> tuple[Path, str]:
    """Yakalama klasörünü tek bir ZIP'e paketler, (yol, sha256) döner."""
    capture_id = meta.get("capture_id") or capture_dir.name
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _write(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
        info = zipfile.ZipInfo(f"{capture_id}/{name}", date_time=_ZIP_EPOCH)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        zf.writestr(info, data)

    signature = signature_info(capture_dir, meta)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        timestamps = inspect_timestamps(capture_dir, run_openssl=False)
        readme = build_readme(meta, lang, signature=signature, pdf=bool(pdf_bytes), timestamps=timestamps)
        _write(zf, PACKAGE_README, readme.encode("utf-8"))
        if pdf_bytes:
            _write(zf, REPORT_NAME, pdf_bytes)
        pub = _signer_pub_file(signature)
        if pub:
            _write(zf, SIGNER_PUB, pub.encode("utf-8"))
        for path in sorted(capture_dir.iterdir()):
            if path.is_file():
                _write(zf, path.name, path.read_bytes())

    return out_path, sha256_file(out_path)


async def export_package(
    capture_dir: Path,
    meta: dict,
    manifest: dict,
    out_path: Path,
    lang: str = DEFAULT_LANG,
    include_pdf: bool = True,
) -> tuple[Path, str]:
    """PDF raporu üretip ZIP paketini yazar, (yol, paket sha256) döner."""
    pdf = await render_report_pdf(capture_dir, meta, manifest, lang) if include_pdf else None
    return build_package(capture_dir, meta, out_path, lang, pdf)


def default_package_name(capture_id: str) -> str:
    return f"webdamga-{capture_id}.zip"


__all__ = [
    "PACKAGE_README",
    "REPORT_NAME",
    "build_package",
    "build_readme",
    "build_report_html",
    "default_package_name",
    "export_package",
    "render_report_pdf",
    "sha256_bytes",
]
