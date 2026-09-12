"""FastAPI uygulaması, yakalama başlatma ve gezinme için yerel web arayüzü."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import __version__
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
from .jobs import CaptureQueue
from .network import ProxyError, load_profiles
from .report import default_package_name, export_package, render_report_pdf
from .storage import JOB_ACTIVE, Store

DATA_DIR = default_data_dir().resolve()
_BASE = Path(__file__).parent
_templates = Jinja2Templates(directory=str(_BASE / "web" / "templates"))

_store = Store(DATA_DIR)
queue = CaptureQueue(_store, DATA_DIR, concurrency=int(os.environ.get("WEBDAMGA_CONCURRENCY", "1")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    await queue.start()
    try:
        yield
    finally:
        await queue.stop()


app = FastAPI(title="webdamga", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_BASE / "web" / "static")), name="static")

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


def _route_names() -> list[str]:
    """Web'den seçilebilecek profil adları. Ham proxy adresi web'den kabul edilmez."""
    try:
        return sorted(load_profiles(DATA_DIR))
    except ProxyError:
        return []


def _checked_route(route: str | None) -> str | None:
    route = (route or "").strip() or None
    if route is not None and route not in _route_names():
        raise HTTPException(status_code=422, detail=f"unknown network route '{route}'")
    return route


def _public_job(job: dict) -> dict:
    """settings_json'ı açılmış hâlde döner."""
    out = {k: v for k, v in job.items() if k != "settings_json"}
    out["settings"] = json.loads(job["settings_json"])
    return out


# ------------------------------------------------------------------------ pages


@app.get("/", response_class=HTMLResponse)
def index(request: Request, lang: str = Depends(get_lang)) -> HTMLResponse:
    return _render(
        request,
        "index.html",
        lang,
        {
            "captures": _store.list(200),
            "active_jobs": list(reversed(_store.list_jobs(statuses=JOB_ACTIVE, limit=50))),
            "routes": _route_names(),
        },
    )


@app.post("/captures")
def create_capture(
    url: str = Form(...),
    full_page: bool = Form(False),
    wait_until: str = Form("load"),
    timeout: int = Form(30),
    wait: float = Form(1.5),
    width: int = Form(1280),
    height: int = Form(800),
    route: str = Form(""),
    record_egress: bool = Form(False),
) -> RedirectResponse:
    settings = CaptureSettings(
        wait_until=wait_until,
        timeout_ms=int(timeout * 1000),
        extra_wait_ms=int(wait * 1000),
        full_page=full_page,
        viewport_width=width,
        viewport_height=height,
        proxy_profile=_checked_route(route),
        record_egress=record_egress,
    )
    job = queue.enqueue(url, settings, source="web")
    return RedirectResponse(url=f"/jobs/{job['id']}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str, lang: str = Depends(get_lang)) -> Response:
    job = _store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] == "done" and job["capture_id"]:
        return RedirectResponse(url=f"/captures/{job['capture_id']}", status_code=303)
    return _render(request, "job.html", lang, {"job": job})


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


# -------------------------------------------------------------------------- API


class CaptureRequest(BaseModel):
    url: str = Field(..., min_length=1)
    full_page: bool = True
    wait_until: str = "load"
    timeout: int = Field(30, ge=5, le=120)
    wait: float = Field(1.5, ge=0, le=30)
    width: int = Field(1280, ge=320, le=3840)
    height: int = Field(800, ge=320, le=4320)
    route: str | None = Field(None, description="proxy profile name, e.g. 'tor'")
    record_egress: bool = False


@app.get("/api/captures")
def api_list() -> list[dict]:
    return _store.list(500)


@app.get("/api/captures/{capture_id}")
def api_get(capture_id: str) -> dict:
    return _load_meta(capture_id)


@app.post("/api/jobs", status_code=202)
def api_create_job(body: CaptureRequest) -> dict:
    settings = CaptureSettings(
        wait_until=body.wait_until,
        timeout_ms=body.timeout * 1000,
        extra_wait_ms=int(body.wait * 1000),
        full_page=body.full_page,
        viewport_width=body.width,
        viewport_height=body.height,
        proxy_profile=_checked_route(body.route),
        record_egress=body.record_egress,
    )
    return _public_job(queue.enqueue(body.url, settings, source="api"))


@app.get("/api/routes")
def api_routes() -> list[str]:
    return _route_names()


@app.get("/api/jobs")
def api_list_jobs(status: str | None = None, limit: int = 50) -> list[dict]:
    statuses = tuple(s for s in (status or "").split(",") if s) or None
    return [_public_job(j) for j in _store.list_jobs(statuses=statuses, limit=min(limit, 500))]


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str) -> dict:
    job = _store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _public_job(job)


@app.delete("/api/jobs/{job_id}")
def api_cancel_job(job_id: str) -> JSONResponse:
    if _store.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not _store.cancel_job(job_id):
        raise HTTPException(status_code=409, detail="only queued jobs can be cancelled")
    return JSONResponse(_public_job(_store.get_job(job_id) or {}))
