"""Playwright ile tek bir URL'yi kanıt olarak kayıt altına alan çekirdek.

Her yakalama `data/captures/<id>/` altında şu dosyaları üretir:

    screenshot.png            tam sayfa ekran görüntüsü
    screenshot-viewport.png   görünür alan (ekran üstü)
    response.html             ana belgenin ham HTTP yanıt gövdesi (JS öncesi)
    dom.html                  JS çalıştıktan sonra render edilmiş DOM
    page.mhtml                tek dosyalık, kendi kendine yeten arşiv (CDP)
    page.pdf                  yazdır -> PDF
    network.har               tüm istek/yanıtlar (gövdeler gömülü)
    console.log               konsol mesajları + sayfa hataları
    metadata.json             URL, yönlendirme zinciri, başlıklar, IP, TLS, ...
    manifest.json             yukarıdaki her dosyanın SHA-256 özeti
    manifest.sha256           manifesto özetinin sidecar'ı
"""

from __future__ import annotations

import asyncio
import json
import platform
import re
import secrets
import socket
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Response, async_playwright

from . import __version__
from .config import CaptureSettings
from .network import EGRESS_CHECK_URL, ProxyError, Route, ensure_reachable, parse_egress, resolve_route

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_FAVICON_JS = (
    "() => { const l = document.querySelector(\"link[rel~='icon']\"); "
    "const h = l && l.href; "
    "return (h && /^https?:/.test(h)) ? h "
    ": (location.origin && location.origin !== 'null' ? location.origin + '/favicon.ico' : null); }"
)
_NAV_TIMING_JS = (
    "() => { const n = performance.getEntriesByType('navigation')[0]; "
    "return n ? JSON.parse(JSON.stringify(n)) : null; }"
)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_url(url: str) -> str:
    url = url.strip()
    if not _SCHEME_RE.match(url):
        url = "https://" + url
    return url


def _capture_id(url: str) -> str:
    host = (urlparse(url).hostname or "unknown").lower()
    slug = _SLUG_RE.sub("-", host).strip("-")[:40] or "unknown"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{slug}-{secrets.token_hex(3)}"


def _readable_tls(tls: dict | None) -> dict | None:
    """security_details() içindeki unix zaman damgalarına ISO karşılıklarını ekler."""
    if not tls:
        return tls
    out = dict(tls)
    for key in ("validFrom", "validTo"):
        ts = tls.get(key)
        if isinstance(ts, (int, float)):
            out[f"{key}_iso"] = datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


async def _redirect_chain(response: Response) -> list[dict]:
    chain: list[dict] = []
    request = response.request.redirected_from
    while request is not None:
        resp = await request.response()
        chain.append(
            {
                "url": request.url,
                "status": resp.status if resp else None,
                "location": resp.headers.get("location") if resp else None,
            }
        )
        request = request.redirected_from
    chain.reverse()
    return chain


async def _check_egress(browser) -> dict:
    """Yakalamanın gerçekten hangi IP'den çıktığını kaydeder.

    Ayrı, HAR kaydı olmayan bir context kullanılır ki bu istek delillere
    karışmasın; proxy tarayıcı seviyesinde verildiği için aynı yoldan gider.
    """
    context = await browser.new_context()
    try:
        response = await context.request.get(EGRESS_CHECK_URL, timeout=15_000)
        if not response.ok:
            return {"error": f"HTTP {response.status}", "source": EGRESS_CHECK_URL}
        return parse_egress(await response.text())
    except (PlaywrightError, ValueError) as exc:
        return {"error": str(exc).splitlines()[0], "source": EGRESS_CHECK_URL}
    finally:
        await context.close()


def _summarize_har(har_path: Path) -> dict:
    try:
        data = json.loads(har_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = data.get("log", {}).get("entries", [])
    by_type: dict[str, dict] = {}
    total = 0
    for entry in entries:
        rtype = entry.get("_resourceType") or "other"
        resp = entry.get("response", {})
        size = resp.get("_transferSize")
        if size is None or size < 0:
            size = max(resp.get("bodySize", 0), 0) + max(resp.get("headersSize", 0), 0)
        size = max(size, 0)
        total += size
        slot = by_type.setdefault(rtype, {"count": 0, "bytes": 0})
        slot["count"] += 1
        slot["bytes"] += size
    return {"request_count": len(entries), "transfer_bytes": total, "by_type": by_type}


class _Run:
    """Tek bir yakalamanın ara durumu; tarayıcı adımları bunu doldurur."""

    def __init__(self, url: str, out_dir: Path, settings: CaptureSettings) -> None:
        self.url = url
        self.out_dir = out_dir
        self.settings = settings
        self.har_path = out_dir / "network.har"
        self.meta: dict = {}
        self.errors: list[str] = []
        self.console_lines: list[str] = []
        self.page_errors: list[str] = []


def _resolve_network(run: _Run, data_dir: Path) -> Route | None:
    """Ağ yolunu çözer; kullanılamıyorsa hatayı kaydedip None döner."""
    settings = run.settings
    try:
        route = resolve_route(settings.proxy, settings.proxy_profile, data_dir)
    except ProxyError as exc:
        run.errors.append(f"network: {exc}")
        run.meta["network"] = {"mode": "unavailable", "profile": settings.proxy_profile}
        return None
    run.meta["network"] = route.describe()
    if route.proxy is not None:
        try:
            ensure_reachable(route.proxy)
        except ProxyError as exc:
            run.errors.append(f"network: {exc}")
            return None
    return route


async def _browse(run: _Run, route: Route) -> None:
    settings, meta, out_dir = run.settings, run.meta, run.out_dir

    async with async_playwright() as pw:
        launch: dict = {"headless": settings.headless}
        if route.proxy is not None:
            # Proxy tarayıcı seviyesinde veriliyor; böylece sayfa, alt
            # kaynaklar ve çıkış IP kontrolü aynı yoldan geçiyor.
            launch["proxy"] = route.proxy.playwright()
        browser = await pw.chromium.launch(**launch)
        meta["browser"] = {"name": "chromium", "version": browser.version}

        if settings.record_egress:
            egress = await _check_egress(browser)
            meta["network"]["egress"] = egress
            if egress.get("is_tor"):
                meta["network"]["mode"] = "tor"

        context = await browser.new_context(
            user_agent=settings.user_agent,
            viewport={"width": settings.viewport_width, "height": settings.viewport_height},
            color_scheme=settings.color_scheme,
            ignore_https_errors=True,
            record_har_path=str(run.har_path),
            record_har_mode="full",
            record_har_content=settings.har_content,
        )

        page = await context.new_page()
        page.on(
            "console",
            lambda msg: run.console_lines.append(f"[{_now_iso()}] {msg.type.upper():8} {msg.text}"),
        )
        page.on(
            "pageerror",
            lambda exc: run.page_errors.append(f"[{_now_iso()}] {getattr(exc, 'message', exc)}"),
        )

        main_response: Response | None = None
        try:
            main_response = await page.goto(
                run.url, wait_until=settings.wait_until, timeout=settings.timeout_ms
            )
            if settings.extra_wait_ms:
                await page.wait_for_timeout(settings.extra_wait_ms)
        except PlaywrightError as exc:
            run.errors.append(f"navigation: {str(exc).splitlines()[0]}")

        # --- sayfa üstü meta (best-effort) ---
        for key, coro in (
            ("page_title", page.title()),
            ("user_agent", page.evaluate("() => navigator.userAgent")),
            ("favicon_url", page.evaluate(_FAVICON_JS)),
            ("navigation_timing", page.evaluate(_NAV_TIMING_JS)),
        ):
            try:
                meta[key] = await coro
            except PlaywrightError:
                meta.setdefault(key, None)

        # --- render edilmiş DOM ---
        try:
            (out_dir / "dom.html").write_text(await page.content(), encoding="utf-8")
        except PlaywrightError:
            pass

        # --- ekran görüntüleri ---
        try:
            await page.screenshot(path=str(out_dir / "screenshot.png"), full_page=settings.full_page)
        except PlaywrightError as exc:
            run.errors.append(f"screenshot: {str(exc).splitlines()[0]}")
        try:
            await page.screenshot(path=str(out_dir / "screenshot-viewport.png"), full_page=False)
        except PlaywrightError:
            pass

        # --- PDF (yalnızca headless chromium) ---
        if settings.pdf and settings.headless:
            try:
                await page.pdf(path=str(out_dir / "page.pdf"), print_background=True)
            except PlaywrightError:
                pass

        # --- ana yanıtın ham gövdesi + ağ/aktarım meta ---
        if main_response is not None:
            try:
                (out_dir / "response.html").write_bytes(await main_response.body())
            except PlaywrightError:
                pass
            try:
                meta["http_status"] = main_response.status
                meta["http_status_text"] = main_response.status_text
                meta["final_url"] = main_response.url
                meta["response_headers"] = dict(await main_response.all_headers())
                meta["request_headers"] = dict(await main_response.request.all_headers())
                meta["remote_address"] = await main_response.server_addr()
                meta["tls"] = _readable_tls(await main_response.security_details())
                meta["redirect_chain"] = await _redirect_chain(main_response)
            except PlaywrightError as exc:
                run.errors.append(f"response-meta: {str(exc).splitlines()[0]}")
        else:
            meta["final_url"] = page.url or run.url

        # --- MHTML anlık görüntüsü (CDP) ---
        try:
            cdp = await context.new_cdp_session(page)
            snapshot = await cdp.send("Page.captureSnapshot", {"format": "mhtml"})
            (out_dir / "page.mhtml").write_text(snapshot["data"], encoding="utf-8")
            await cdp.detach()
        except PlaywrightError:
            pass

        meta["console_message_count"] = len(run.console_lines)
        meta["page_error_count"] = len(run.page_errors)

        await context.close()  # HAR bu noktada diske yazılır
        await browser.close()


async def capture(url: str, data_dir: Path, settings: CaptureSettings | None = None) -> dict:
    """`url`'yi yakalar, klasöre yazar ve metadata sözlüğünü döner."""
    settings = settings or CaptureSettings()
    data_dir = Path(data_dir)
    url = normalize_url(url)

    capture_id = _capture_id(url)
    out_dir = data_dir / "captures" / capture_id
    out_dir.mkdir(parents=True, exist_ok=True)

    run = _Run(url, out_dir, settings)
    meta = run.meta
    meta.update(
        {
            "capture_id": capture_id,
            "dir": str(out_dir),
            "tool": "webdamga",
            "tool_version": __version__,
            "requested_url": url,
            "requested_at_utc": _now_iso(),
            "capture_settings": settings.as_dict(),
            "capture_host": {
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
        }
    )

    route = await asyncio.to_thread(_resolve_network, run, data_dir)
    if route is not None:
        try:
            await _browse(run, route)
        except Exception as exc:  # noqa: BLE001 - kanıt aracı her koşulda sonlanmalı
            run.errors.append(f"fatal: {type(exc).__name__}: {exc}")
    else:
        meta.setdefault("final_url", url)

    # --- konsol kaydı ---
    log_lines = list(run.console_lines)
    if run.page_errors:
        log_lines += ["", "=== PAGE ERRORS ===", *run.page_errors]
    (out_dir / "console.log").write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")

    # --- sonlandırma ---
    meta["resource_summary"] = _summarize_har(run.har_path)
    meta["completed_at_utc"] = _now_iso()
    meta["ok"] = not run.errors
    if run.errors:
        meta["error"] = "; ".join(run.errors)

    (out_dir / "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )

    from .hashing import build_manifest, write_manifest

    manifest = build_manifest(out_dir, tool="webdamga", tool_version=__version__, meta=meta)
    meta["manifest_sha256"] = write_manifest(out_dir, manifest)
    return meta
