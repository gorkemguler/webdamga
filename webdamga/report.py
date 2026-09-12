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
from .hashing import MANIFEST_NAME, MANIFEST_SIDECAR, sha256_bytes, sha256_file
from .i18n import DEFAULT_LANG, t, translator

REPORT_NAME = "evidence-report.pdf"
PACKAGE_README = "README.txt"

# ZIP içindeki zaman damgaları yakalama anına sabitlenir; aynı yakalamadan
# üretilen paketler böylece bit bit aynı olur ve özeti tekrar üretilebilir.
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


def build_readme(meta: dict, lang: str = DEFAULT_LANG) -> str:
    return t(
        "pkg.readme",
        lang,
        capture_id=meta.get("capture_id", "?"),
        url=meta.get("final_url") or meta.get("requested_url", "?"),
        captured=meta.get("completed_at_utc", "?"),
        packaged=_now_iso(),
        version=__version__,
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

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _write(zf, PACKAGE_README, build_readme(meta, lang).encode("utf-8"))
        if pdf_bytes:
            _write(zf, REPORT_NAME, pdf_bytes)
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
