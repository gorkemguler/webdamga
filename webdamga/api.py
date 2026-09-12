"""FastAPI uygulaması, yakalama başlatma ve gezinme için yerel web arayüzü."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from . import __version__
from .capture import capture as run_capture
from .config import CaptureSettings, default_data_dir
from .hashing import MANIFEST_NAME, MANIFEST_SIDECAR, verify_capture
from .i18n import (
    DEFAULT_LANG,
    LANG_COOKIE,
    SUPPORTED_LANGS,
    normalize_lang,
    parse_accept_language,
    translator,
)
from .report import default_package_name, export_package, render_report_pdf
from .storage import Store

DATA_DIR = default_data_dir().resolve()
_BASE = Path(__file__).parent
_templates = Jinja2Templates(directory=str(_BASE / "web" / "templates"))

app = FastAPI(title="webdamga", version=__version__)
app.mount("/static", StaticFiles(directory=str(_BASE / "web" / "static")), name="static")

_store = Store(DATA_DIR)

_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def get_lang(request: Request) -> str:
    """Sırasıyla ?lang=, çerez, Accept-Language, varsayılan."""
    explicit = normalize_lang(request.query_params.get("lang"))
    if explicit:
        return explicit
    stored = normalize_lang(request.cookies.get(LANG_COOKIE))
    if stored:
        return stored
    accepted = parse_accept_language(request.headers.get("accept-language"))
    return accepted or DEFAULT_LANG


def _render(request: Request, template: str, lang: str, context: dict) -> HTMLResponse:
    response = _templates.TemplateResponse(
        request,
        template,
        {
            **context,
            "lang": lang,
            "langs": SUPPORTED_LANGS,
            "_": translator(lang),
            "version": __version__,
        },
    )
    # ?lang= ile açık seçim yapıldıysa tercihi hatırla.
    if normalize_lang(request.query_params.get("lang")):
        response.set_cookie(LANG_COOKIE, lang, max_age=_COOKIE_MAX_AGE, httponly=False, samesite="lax")
    return response


def _capture_dir(capture_id: str) -> Path:
    cap_dir = (DATA_DIR / "captures" / capture_id).resolve()
    if cap_dir.parent != (DATA_DIR / "captures").resolve() or not cap_dir.is_dir():
        raise HTTPException(status_code=404, detail="capture not found")
    return cap_dir


def _load_meta(capture_id: str) -> dict:
    meta_path = _capture_dir(capture_id) / "metadata.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail="metadata.json missing")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _load_manifest(capture_id: str) -> dict:
    manifest_path = _capture_dir(capture_id) / MANIFEST_NAME
    if not manifest_path.is_file():
        return {"files": []}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request, lang: str = Depends(get_lang)) -> HTMLResponse:
    return _render(request, "index.html", lang, {"captures": _store.list(200)})


@app.post("/captures")
async def create_capture(
    url: str = Form(...),
    full_page: bool = Form(True),
    wait_until: str = Form("load"),
    timeout: int = Form(30),
    wait: float = Form(1.5),
    width: int = Form(1280),
    height: int = Form(800),
) -> RedirectResponse:
    settings = CaptureSettings(
        wait_until=wait_until,
        timeout_ms=int(timeout * 1000),
        extra_wait_ms=int(wait * 1000),
        full_page=full_page,
        viewport_width=width,
        viewport_height=height,
    )
    meta = await run_capture(url, DATA_DIR, settings)
    _store.record(
        meta,
        manifest_sha256=meta.get("manifest_sha256"),
        ok=bool(meta.get("ok")),
        error=meta.get("error"),
    )
    return RedirectResponse(url=f"/captures/{meta['capture_id']}", status_code=303)


@app.get("/captures/{capture_id}", response_class=HTMLResponse)
def capture_detail(request: Request, capture_id: str, lang: str = Depends(get_lang)) -> HTMLResponse:
    return _render(
        request,
        "capture.html",
        lang,
        {
            "m": _load_meta(capture_id),
            "manifest": _load_manifest(capture_id),
            "capture_id": capture_id,
        },
    )


@app.get("/captures/{capture_id}/verify")
def capture_verify(capture_id: str) -> dict:
    return verify_capture(_capture_dir(capture_id))


@app.get("/captures/{capture_id}/report.pdf")
async def capture_report(capture_id: str, lang: str = Depends(get_lang)) -> Response:
    """İnsan okur, kısa PDF kanıt raporu."""
    cap_dir = _capture_dir(capture_id)
    pdf = await render_report_pdf(cap_dir, _load_meta(capture_id), _load_manifest(capture_id), lang)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"content-disposition": f'inline; filename="webdamga-{capture_id}-report.pdf"'},
    )


@app.get("/captures/{capture_id}/export.zip")
async def capture_export(capture_id: str, lang: str = Depends(get_lang)) -> FileResponse:
    """Bütün delilleri, manifestoyu ve PDF raporu içeren gönderilebilir paket."""
    cap_dir = _capture_dir(capture_id)
    meta = _load_meta(capture_id)
    tmp_dir = Path(tempfile.mkdtemp(prefix="webdamga-export-"))
    name = default_package_name(capture_id)
    package, digest = await export_package(cap_dir, meta, _load_manifest(capture_id), tmp_dir / name, lang)

    def _cleanup() -> None:
        package.unlink(missing_ok=True)
        tmp_dir.rmdir()

    return FileResponse(
        str(package),
        media_type="application/zip",
        filename=name,
        # Alıcının gönderdiği dosyayla eşleştirebilmesi için paket özeti.
        headers={"x-webdamga-package-sha256": digest},
        background=BackgroundTask(_cleanup),
    )


@app.get("/captures/{capture_id}/files/{name}")
def capture_file(capture_id: str, name: str) -> FileResponse:
    cap_dir = _capture_dir(capture_id)
    allowed = {MANIFEST_NAME, MANIFEST_SIDECAR}
    allowed |= {entry["name"] for entry in _load_manifest(capture_id).get("files", [])}
    if name not in allowed:
        raise HTTPException(status_code=404, detail="no such file in this capture")
    path = (cap_dir / name).resolve()
    if path.parent != cap_dir or not path.is_file():
        raise HTTPException(status_code=404)
    inline = path.suffix in {".png", ".pdf", ".html", ".log", ".json", ".sha256", ".har", ".mhtml"}
    media = "text/plain; charset=utf-8" if path.suffix in {".log", ".sha256"} else None
    return FileResponse(
        str(path),
        media_type=media,
        content_disposition_type="inline" if inline else "attachment",
        filename=name,
    )


@app.get("/api/captures")
def api_list() -> list[dict]:
    return _store.list(500)


@app.get("/api/captures/{capture_id}")
def api_get(capture_id: str) -> dict:
    return _load_meta(capture_id)
