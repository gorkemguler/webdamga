"""FastAPI uygulaması — yakalama başlatma ve gezinme için yerel web arayüzü."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__
from .capture import capture as run_capture
from .config import CaptureSettings, default_data_dir
from .hashing import MANIFEST_NAME, MANIFEST_SIDECAR, verify_capture
from .storage import Store

DATA_DIR = default_data_dir().resolve()
_BASE = Path(__file__).parent
_templates = Jinja2Templates(directory=str(_BASE / "web" / "templates"))

app = FastAPI(title="webdamga", version=__version__)
app.mount("/static", StaticFiles(directory=str(_BASE / "web" / "static")), name="static")

_store = Store(DATA_DIR)


def _capture_dir(capture_id: str) -> Path:
    cap_dir = (DATA_DIR / "captures" / capture_id).resolve()
    if cap_dir.parent != (DATA_DIR / "captures").resolve() or not cap_dir.is_dir():
        raise HTTPException(status_code=404, detail="yakalama bulunamadı")
    return cap_dir


def _load_meta(capture_id: str) -> dict:
    meta_path = _capture_dir(capture_id) / "metadata.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail="metadata.json yok")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _load_manifest(capture_id: str) -> dict:
    manifest_path = _capture_dir(capture_id) / MANIFEST_NAME
    if not manifest_path.is_file():
        return {"files": []}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(
        request,
        "index.html",
        {"captures": _store.list(200), "version": __version__},
    )


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
def capture_detail(request: Request, capture_id: str) -> HTMLResponse:
    return _templates.TemplateResponse(
        request,
        "capture.html",
        {
            "m": _load_meta(capture_id),
            "manifest": _load_manifest(capture_id),
            "capture_id": capture_id,
            "version": __version__,
        },
    )


@app.get("/captures/{capture_id}/verify")
def capture_verify(capture_id: str) -> dict:
    return verify_capture(_capture_dir(capture_id))


@app.get("/captures/{capture_id}/files/{name}")
def capture_file(capture_id: str, name: str) -> FileResponse:
    cap_dir = _capture_dir(capture_id)
    allowed = {MANIFEST_NAME, MANIFEST_SIDECAR}
    allowed |= {entry["name"] for entry in _load_manifest(capture_id).get("files", [])}
    if name not in allowed:
        raise HTTPException(status_code=404, detail="dosya bu yakalamada yok")
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
