"""FastAPI uygulaması, yakalama başlatma ve gezinme için yerel web arayüzü."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import __version__
from .capture import normalize_url
from .config import CaptureSettings, default_data_dir
from .diff import compare_captures, describe_reason, diff_dir
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
from .monitor import MonitorError, Scheduler, add_monitor, validate_interval
from .network import ProxyError, load_profiles
from .report import default_package_name, export_package, render_report_pdf
from .security import (
    GuardMiddleware,
    UrlNotAllowed,
    artifact_headers,
    safe_download_name,
    validate_capture_url,
)
from .storage import JOB_ACTIVE, Store
from .timestamp import inspect_timestamps, timestamp_capture

DATA_DIR = default_data_dir().resolve()
_BASE = Path(__file__).parent
_templates = Jinja2Templates(directory=str(_BASE / "web" / "templates"))

_store = Store(DATA_DIR)
queue = CaptureQueue(_store, DATA_DIR, concurrency=int(os.environ.get("WEBDAMGA_CONCURRENCY", "1")))
scheduler = Scheduler(_store, queue)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await queue.start()
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()
        await queue.stop()


app = FastAPI(title="webdamga", version=__version__, lifespan=lifespan)
# Host ve CSRF koruması: kötü niyetli bir web sayfası localhost'taki arayüze
# istek gönderip yakalama başlatamasın, izleyici silemesin.
app.add_middleware(GuardMiddleware)
app.mount("/static", StaticFiles(directory=str(_BASE / "web" / "static")), name="static")


def _checked_url(url: str) -> str:
    """URL'yi normalleştirip şemasını doğrular; geçersizse 422."""
    try:
        return validate_capture_url(normalize_url(url))
    except UrlNotAllowed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


def _same_host_captures(capture_id: str, meta: dict) -> list[dict]:
    """Aynı sunucuya ait diğer yakalamalar, en yeniden eskiye."""
    host = urlsplit(meta.get("final_url") or meta.get("requested_url") or "").hostname
    if not host:
        return []
    return [
        row
        for row in _store.list(500)
        if row["id"] != capture_id and urlsplit(row["final_url"] or row["requested_url"]).hostname == host
    ]


def _diff(older: str, newer: str) -> tuple[dict, Path]:
    dir_a, dir_b = _capture_dir(older), _capture_dir(newer)
    # Kullanıcı hangi sırayla seçerse seçsin "a" eski, "b" yeni olsun.
    if _load_meta(dir_a.name).get("completed_at_utc", "") > _load_meta(dir_b.name).get(
        "completed_at_utc", ""
    ):
        dir_a, dir_b = dir_b, dir_a
    out = diff_dir(DATA_DIR, dir_a.name, dir_b.name)
    return compare_captures(dir_a, dir_b, out), out


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
    timestamp: bool = Form(False),
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
        timestamp=timestamp,
    )
    job = queue.enqueue(_checked_url(url), settings, source="web")
    return RedirectResponse(url=f"/jobs/{job['id']}", status_code=303)


def _monitor_or_404(monitor_id: int) -> dict:
    monitor = _store.get_monitor(monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="monitor not found")
    return monitor


def _public_monitor(monitor: dict) -> dict:
    out = {k: v for k, v in monitor.items() if k != "settings_json"}
    out["enabled"] = bool(monitor["enabled"])
    out["settings"] = json.loads(monitor["settings_json"])
    return out


@app.get("/monitors", response_class=HTMLResponse)
def monitors_page(request: Request, lang: str = Depends(get_lang)) -> HTMLResponse:
    return _render(
        request, "monitors.html", lang, {"monitors": _store.list_monitors(), "routes": _route_names()}
    )


@app.post("/monitors")
def create_monitor_form(
    url: str = Form(...),
    interval: int = Form(60),
    label: str = Form(""),
    route: str = Form(""),
    timestamp: bool = Form(False),
) -> RedirectResponse:
    settings = CaptureSettings(proxy_profile=_checked_route(route), timestamp=timestamp)
    try:
        monitor = add_monitor(_store, _checked_url(url), interval, settings, label=label)
    except MonitorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(url=f"/monitors/{monitor['id']}", status_code=303)


@app.get("/monitors/{monitor_id}", response_class=HTMLResponse)
def monitor_page(request: Request, monitor_id: int, lang: str = Depends(get_lang)) -> HTMLResponse:
    monitor = _monitor_or_404(monitor_id)
    runs = _store.list_jobs(monitor_id=monitor_id, limit=100)
    return _render(request, "monitor.html", lang, {"monitor": monitor, "runs": runs})


@app.post("/monitors/{monitor_id}/{action}")
def monitor_action_form(monitor_id: int, action: str) -> RedirectResponse:
    monitor = _monitor_or_404(monitor_id)
    if action == "run":
        scheduler.run_now(monitor)
    elif action in ("pause", "resume"):
        _store.update_monitor(monitor_id, enabled=int(action == "resume"))
    elif action == "delete":
        _store.delete_monitor(monitor_id)
        return RedirectResponse(url="/monitors", status_code=303)
    else:
        raise HTTPException(status_code=404)
    return RedirectResponse(url=f"/monitors/{monitor_id}", status_code=303)


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
            "timestamps": inspect_timestamps(_capture_dir(capture_id), run_openssl=False),
            "comparable": _same_host_captures(capture_id, _load_meta(capture_id)),
        },
    )


@app.get("/captures/{capture_id}/verify")
def capture_verify(capture_id: str) -> dict:
    return verify_capture(_capture_dir(capture_id))


@app.get("/diff", response_class=HTMLResponse)
def diff_page(request: Request, a: str, b: str, lang: str = Depends(get_lang)) -> HTMLResponse:
    result, _ = _diff(a, b)
    reasons = [{**r, "text": describe_reason(r, lang)} for r in result["reasons"]]
    return _render(request, "diff.html", lang, {"d": result, "reasons": reasons, "id_a": a, "id_b": b})


@app.get("/diff/{older}/{newer}/visual.png")
def diff_image(older: str, newer: str) -> FileResponse:
    _capture_dir(older), _capture_dir(newer)  # kimlikleri doğrula
    path = diff_dir(DATA_DIR, older, newer) / "visual-diff.png"
    if not path.is_file():
        _diff(older, newer)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no screenshots to compare")
    return FileResponse(str(path), media_type="image/png")


@app.get("/api/diff")
def api_diff(a: str, b: str) -> dict:
    return _diff(a, b)[0]


@app.post("/captures/{capture_id}/timestamp")
def capture_timestamp(capture_id: str) -> dict:
    """Mevcut bir yakalamaya zaman damgası ekler; var olanları ezmez."""
    cap_dir = _capture_dir(capture_id)
    if not (cap_dir / MANIFEST_NAME).is_file():
        raise HTTPException(status_code=409, detail="capture has no manifest")
    current = inspect_timestamps(cap_dir, run_openssl=False)
    want_rfc = not current["rfc3161"]["present"]
    want_ots = not current["opentimestamps"]["present"]
    if not (want_rfc or want_ots):
        raise HTTPException(status_code=409, detail="capture is already timestamped")
    result = timestamp_capture(cap_dir, rfc3161=want_rfc, opentimestamps=want_ots)
    return {"requested": result, "timestamps": inspect_timestamps(cap_dir, run_openssl=False)}


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

    # Yakalanan içerik düşman olabilir. Aktif türler (dom.html, page.mhtml, ...)
    # arayüzle aynı origin'de asla çalıştırılmaz: indirme olarak, sandbox CSP ile.
    inline, extra = artifact_headers(name)
    # Aktif olmayanlarda bile tarayıcı text/html'e sniff etmesin diye tipi sabitliyoruz.
    media = {
        ".png": "image/png",
        ".pdf": "application/pdf",
        ".json": "application/json",
        ".sha256": "text/plain; charset=utf-8",
        ".log": "text/plain; charset=utf-8",
        ".minisig": "text/plain; charset=utf-8",
    }.get(path.suffix, "application/octet-stream")
    return FileResponse(
        str(path),
        media_type=media,
        content_disposition_type="inline" if inline else "attachment",
        filename=safe_download_name(name),
        headers=extra,
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
    timestamp: bool = False


@app.get("/api/captures")
def api_list() -> list[dict]:
    return _store.list(500)


@app.get("/api/captures/{capture_id}")
def api_get(capture_id: str) -> dict:
    return _load_meta(capture_id)


class MonitorRequest(BaseModel):
    url: str = Field(..., min_length=1)
    interval_minutes: int = Field(60)
    label: str | None = None
    route: str | None = None
    timestamp: bool = False
    full_page: bool = True


class MonitorPatch(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None
    label: str | None = None


@app.get("/api/monitors")
def api_list_monitors() -> list[dict]:
    return [_public_monitor(m) for m in _store.list_monitors()]


@app.post("/api/monitors", status_code=201)
def api_create_monitor(body: MonitorRequest) -> dict:
    settings = CaptureSettings(
        proxy_profile=_checked_route(body.route), timestamp=body.timestamp, full_page=body.full_page
    )
    try:
        return _public_monitor(
            add_monitor(_store, _checked_url(body.url), body.interval_minutes, settings, label=body.label)
        )
    except MonitorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/monitors/{monitor_id}")
def api_get_monitor(monitor_id: int) -> dict:
    monitor = _public_monitor(_monitor_or_404(monitor_id))
    monitor["runs"] = [_public_job(j) for j in _store.list_jobs(monitor_id=monitor_id, limit=100)]
    return monitor


@app.patch("/api/monitors/{monitor_id}")
def api_update_monitor(monitor_id: int, body: MonitorPatch) -> dict:
    _monitor_or_404(monitor_id)
    fields: dict = {}
    if body.enabled is not None:
        fields["enabled"] = int(body.enabled)
    if body.interval_minutes is not None:
        try:
            fields["interval_minutes"] = validate_interval(body.interval_minutes)
        except MonitorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.label is not None:
        fields["label"] = body.label.strip() or None
    return _public_monitor(_store.update_monitor(monitor_id, **fields) or {})


@app.delete("/api/monitors/{monitor_id}", status_code=204)
def api_delete_monitor(monitor_id: int) -> Response:
    _monitor_or_404(monitor_id)
    _store.delete_monitor(monitor_id)
    return Response(status_code=204)


@app.post("/api/monitors/{monitor_id}/run", status_code=202)
def api_run_monitor(monitor_id: int) -> dict:
    return _public_job(scheduler.run_now(_monitor_or_404(monitor_id)))


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
        timestamp=body.timestamp,
    )
    return _public_job(queue.enqueue(_checked_url(body.url), settings, source="api"))


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
