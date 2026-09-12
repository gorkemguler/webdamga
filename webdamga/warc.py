"""WARC/1.1 çıktısı: yakalamayı Wayback / pywb / ReplayWeb.page ile yeniden oynatılabilir kılar.

Yanıt gövdeleri ne HAR'dan ne de Playwright'in `response.body()`'sinden alınır:
ikisi de metin kaynaklarını sayfanın charset'iyle çözüp UTF-8'e yeniden
kodlar, yani windows-1254 gibi bir sayfanın özgün baytları kaybolur. Kanıt
değeri olan bir arşiv için gövdeler CDP `Fetch` alanıyla yanıt aşamasında,
charset'e dokunulmamış hâliyle okunur (bkz. ResponseRecorder).

Tarayıcı gövdeyi Content-Encoding'den (gzip/br) çözülmüş verir. Oynatıcılar
başlıklara bakıp tekrar açmaya çalışmasın diye `Content-Encoding` ve
`Transfer-Encoding` kaldırılır, `Content-Length` gerçek uzunlukla yazılır,
özgün değerler `X-Archive-Orig-*` başlıklarında korunur. Browsertrix gibi
tarayıcı tabanlı arşivleyicilerin izlediği yol budur.

Her kayıt ayrı bir gzip üyesidir; oynatıcılar dosyayı kayıt kayıt indeksler.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import gzip
import hashlib
import http
import json
import logging
import uuid
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__

log = logging.getLogger("webdamga.warc")

WARC_NAME = "archive.warc.gz"
WARC_VERSION = b"WARC/1.1"
CONFORMS_TO = "https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/"

MAX_BODY_BYTES = 25 * 1024 * 1024  # tek yanıt için
MAX_TOTAL_BYTES = 400 * 1024 * 1024  # bir yakalamadaki tüm gövdeler için

_HOP_BY_HOP = {"content-encoding", "transfer-encoding", "content-length"}


@dataclass(slots=True)
class Exchange:
    """Tek bir HTTP istek/yanıt çifti, ham gövdesiyle."""

    url: str
    method: str
    request_headers: list[tuple[str, str]]
    request_body: bytes | None
    status: int
    status_text: str
    response_headers: list[tuple[str, str]]
    body: bytes
    started: datetime
    server_ip: str | None = None
    truncated: bool = False
    body_source: str = "raw"  # raw | browser-decoded | har-base64 | har-text
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- toplama


class ResponseRecorder:
    """Bir tarayıcı context'indeki yanıtları ham gövdeleriyle toplar.

    İki kaynak birleştirilir:

    * Playwright'in context `response` olayları: başlıklar, durum, zamanlama,
      sunucu IP'si. Farklı süreçteki iframe'ler dahil her şeyi görür.
    * Sayfa üzerinde CDP `Fetch` alanı, yanıt aşamasında: gövdenin gerçek
      baytları. Playwright'in `response.body()`'si metin kaynaklarını
      sayfanın charset'iyle çözüp UTF-8'e yeniden kodlar; windows-1254 gibi
      bir sayfada bu baytları değiştirir. Fetch ise Content-Encoding'i açılmış
      ama charset'e dokunulmamış gövdeyi verir.

    Fetch'in göremediği yanıtlarda (ör. ayrı süreçteki iframe'ler) gövde
    Playwright'ten alınır ve kayıt `browser-decoded` olarak işaretlenir.
    """

    def __init__(self, *, max_body: int = MAX_BODY_BYTES, max_total: int = MAX_TOTAL_BYTES) -> None:
        self.exchanges: list[Exchange] = []
        self.max_body = max_body
        self.max_total = max_total
        self._responses: list[tuple[Exchange, object]] = []
        self._raw: dict[tuple[str, str], deque[bytes]] = defaultdict(deque)
        self._tasks: set[asyncio.Task] = set()
        self._cdp = None

    # -- bağlama

    def attach(self, context) -> None:
        context.on("response", self._on_response)

    async def attach_raw_bodies(self, cdp_session) -> None:
        """Sayfanın CDP oturumunda yanıt aşaması yakalamayı açar."""
        self._cdp = cdp_session
        cdp_session.on("Fetch.requestPaused", self._on_paused)
        await cdp_session.send(
            "Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Response"}]}
        )

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- CDP Fetch: ham gövde

    def _on_paused(self, event: dict) -> None:
        self._spawn(self._take_raw_body(event))

    async def _take_raw_body(self, event: dict) -> None:
        request_id = event["requestId"]
        try:
            status = event.get("responseStatusCode") or 0
            if 200 <= status and not 300 <= status < 400 and self._worth_reading(event):
                reply = await self._cdp.send("Fetch.getResponseBody", {"requestId": request_id})
                body = (
                    base64.b64decode(reply["body"]) if reply.get("base64Encoded") else reply["body"].encode()
                )
                request = event.get("request", {})
                self._raw[(request.get("method", "GET"), request.get("url", ""))].append(body)
        except Exception as exc:  # noqa: BLE001 - gövde alınamazsa Playwright'e düşülür
            log.debug("raw body unavailable for %s: %s", event.get("request", {}).get("url"), exc)
        finally:
            # Ne olursa olsun yanıtı serbest bırak, yoksa sayfa askıda kalır.
            with contextlib.suppress(Exception):
                await self._cdp.send("Fetch.continueResponse", {"requestId": request_id})

    def _worth_reading(self, event: dict) -> bool:
        # Akış hâlindeki medya gövdesini beklemek sayfayı kilitleyebilir.
        if event.get("resourceType") == "Media":
            return False
        for header in event.get("responseHeaders") or []:
            if header.get("name", "").lower() == "content-length":
                with contextlib.suppress(ValueError):
                    return int(header.get("value", "0")) <= self.max_body
        return True

    # -- Playwright: başlıklar, durum, zamanlama

    def _on_response(self, response) -> None:
        self._spawn(self._describe(response))

    async def _describe(self, response) -> None:
        from playwright.async_api import Error as PlaywrightError

        if urlsplit(response.url).scheme not in ("http", "https"):
            return
        request = response.request
        try:
            req_headers = [(h["name"], h["value"]) for h in await request.headers_array()]
            resp_headers = [(h["name"], h["value"]) for h in await response.headers_array()]
        except PlaywrightError:
            return

        server_ip = None
        with contextlib.suppress(PlaywrightError):
            addr = await response.server_addr()
            server_ip = (addr or {}).get("ipAddress", "").strip("[]") or None

        timing = request.timing or {}
        start_ms = timing.get("startTime")
        started = (
            datetime.fromtimestamp(start_ms / 1000, UTC)
            if isinstance(start_ms, (int, float)) and start_ms > 0
            else datetime.now(UTC)
        )
        exchange = Exchange(
            url=response.url,
            method=request.method,
            request_headers=req_headers,
            request_body=request.post_data_buffer,
            status=response.status,
            status_text=response.status_text,
            response_headers=resp_headers,
            body=b"",
            started=started,
            server_ip=server_ip,
            extra={"resource_type": request.resource_type},
        )
        self._responses.append((exchange, response))

    # -- birleştirme

    async def drain(self) -> None:
        """Bütün okumaların bitmesini bekler ve gövdeleri yanıtlarla eşleştirir.

        Tarayıcı context'i kapanmadan önce çağrılmalı.
        """
        from playwright.async_api import Error as PlaywrightError

        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

        total = 0
        for exchange, response in sorted(self._responses, key=lambda pair: pair[0].started):
            queue = self._raw.get((exchange.method, exchange.url))
            if queue:
                exchange.body, exchange.body_source = queue.popleft(), "raw"
            elif not 300 <= exchange.status < 400:
                with contextlib.suppress(PlaywrightError):
                    exchange.body = await response.body()
                    exchange.body_source = "browser-decoded"
            if len(exchange.body) > self.max_body or total + len(exchange.body) > self.max_total:
                exchange.body = exchange.body[: max(0, min(self.max_body, self.max_total - total))]
                exchange.truncated = True
            total += len(exchange.body)
            self.exchanges.append(exchange)
        self._responses.clear()
        self._raw.clear()

    def main_document(self, url: str) -> Exchange | None:
        """Nihai URL'ye ait ilk belge yanıtı."""
        for exchange in self.exchanges:
            if exchange.url == url and exchange.extra.get("resource_type") == "document":
                return exchange
        return None


# --------------------------------------------------------------------------- yazma


def _warc_date(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _clean(value: str) -> str:
    return str(value).replace("\r", " ").replace("\n", " ")


def _record_id(seed: str) -> str:
    # Aynı yakalamadan aynı kimlikler üretilsin ki WARC tekrar üretilebilir olsun.
    return f"<urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'webdamga:' + seed)}>"


def _record(headers: list[tuple[str, str]], block: bytes) -> bytes:
    lines = [WARC_VERSION]
    lines += [f"{name}: {_clean(value)}".encode() for name, value in headers]
    lines.append(f"Content-Length: {len(block)}".encode())
    raw = b"\r\n".join(lines) + b"\r\n\r\n" + block + b"\r\n\r\n"
    return gzip.compress(raw, mtime=0)


def _reason(status: int, text: str) -> str:
    if text:
        return _clean(text)
    try:
        return http.HTTPStatus(status).phrase
    except ValueError:
        return ""


def _http_response_block(ex: Exchange) -> tuple[bytes, bytes]:
    """(http blok, payload) döner; gövde çözülmüş olduğu için başlıkları uyarlar."""
    lines = [f"HTTP/1.1 {ex.status} {_reason(ex.status, ex.status_text)}".rstrip()]
    for name, value in ex.response_headers:
        if name.startswith(":"):
            continue
        if name.lower() in _HOP_BY_HOP:
            lines.append(f"X-Archive-Orig-{name}: {_clean(value)}")
            continue
        lines.append(f"{name}: {_clean(value)}")
    lines.append(f"Content-Length: {len(ex.body)}")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1", errors="replace")
    return head + ex.body, ex.body


def _http_request_block(ex: Exchange) -> bytes:
    parts = urlsplit(ex.url)
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    lines = [f"{ex.method} {target} HTTP/1.1"]
    names = {name.lower() for name, _ in ex.request_headers}
    if "host" not in names:
        lines.append(f"Host: {parts.netloc}")
    for name, value in ex.request_headers:
        if name.startswith(":"):
            continue
        lines.append(f"{name}: {_clean(value)}")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1", errors="replace")
    return head + (ex.request_body or b"")


def write_warc(
    path: Path,
    exchanges: Iterable[Exchange],
    *,
    meta: dict,
    capture_dir: Path | None = None,
) -> dict:
    """Değişimleri WARC dosyasına yazar, kısa bir özet döner."""
    path = Path(path)
    capture_id = meta.get("capture_id", path.stem)
    started_at = meta.get("requested_at_utc")
    info_date = (
        datetime.strptime(started_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if started_at
        else datetime.now(UTC)
    )
    final_url = meta.get("final_url") or meta.get("requested_url") or ""
    ordered = sorted(exchanges, key=lambda ex: ex.started)

    warcinfo_id = _record_id(f"{capture_id}:warcinfo")
    info_fields = (
        f"software: webdamga/{__version__}\r\n"
        "format: WARC File Format 1.1\r\n"
        f"conformsTo: {CONFORMS_TO}\r\n"
        f"isPartOf: {capture_id}\r\n"
        f"description: Browser capture of {_clean(meta.get('requested_url', ''))}\r\n"
    ).encode()

    counts = {"response": 0, "request": 0, "resource": 0, "truncated": 0}
    main_response_id = None

    with path.open("wb") as out:
        out.write(
            _record(
                [
                    ("WARC-Type", "warcinfo"),
                    ("WARC-Record-ID", warcinfo_id),
                    ("WARC-Date", _warc_date(info_date)),
                    ("WARC-Filename", path.name),
                    ("Content-Type", "application/warc-fields"),
                    ("WARC-Block-Digest", _digest(info_fields)),
                ],
                info_fields,
            )
        )

        for n, ex in enumerate(ordered):
            date = _warc_date(ex.started)
            response_id = _record_id(f"{capture_id}:{n}:response")
            block, payload = _http_response_block(ex)
            headers = [
                ("WARC-Type", "response"),
                ("WARC-Record-ID", response_id),
                ("WARC-Warcinfo-ID", warcinfo_id),
                ("WARC-Date", date),
                ("WARC-Target-URI", ex.url),
            ]
            if ex.server_ip:
                headers.append(("WARC-IP-Address", ex.server_ip))
            headers += [
                ("Content-Type", "application/http; msgtype=response"),
                ("WARC-Payload-Digest", _digest(payload)),
                ("WARC-Block-Digest", _digest(block)),
            ]
            if ex.truncated:
                headers.append(("WARC-Truncated", "length"))
                counts["truncated"] += 1
            if ex.body_source != "raw":
                headers.append(("WebDamga-Body-Source", ex.body_source))
            out.write(_record(headers, block))
            counts["response"] += 1
            if main_response_id is None and ex.url == final_url:
                main_response_id = response_id

            request_block = _http_request_block(ex)
            out.write(
                _record(
                    [
                        ("WARC-Type", "request"),
                        ("WARC-Record-ID", _record_id(f"{capture_id}:{n}:request")),
                        ("WARC-Warcinfo-ID", warcinfo_id),
                        ("WARC-Date", date),
                        ("WARC-Target-URI", ex.url),
                        ("WARC-Concurrent-To", response_id),
                        ("Content-Type", "application/http; msgtype=request"),
                        ("WARC-Block-Digest", _digest(request_block)),
                    ],
                    request_block,
                )
            )
            counts["request"] += 1

        # Ekran görüntüleri Browsertrix'in kullandığı urn:view / urn:fullPage
        # adlarıyla kaynak kaydı olarak eklenir.
        if capture_dir is not None and final_url:
            completed = meta.get("completed_at_utc") or started_at
            shot_date = (
                datetime.strptime(completed, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
                if completed
                else info_date
            )
            for kind, name in (("view", "screenshot-viewport.png"), ("fullPage", "screenshot.png")):
                shot = Path(capture_dir) / name
                if not shot.is_file():
                    continue
                data = shot.read_bytes()
                headers = [
                    ("WARC-Type", "resource"),
                    ("WARC-Record-ID", _record_id(f"{capture_id}:{kind}")),
                    ("WARC-Warcinfo-ID", warcinfo_id),
                    ("WARC-Date", _warc_date(shot_date)),
                    ("WARC-Target-URI", f"urn:{kind}:{final_url}"),
                    ("Content-Type", "image/png"),
                    ("WARC-Block-Digest", _digest(data)),
                ]
                if main_response_id:
                    headers.append(("WARC-Concurrent-To", main_response_id))
                out.write(_record(headers, data))
                counts["resource"] += 1

    return {"file": path.name, "records": 1 + sum(v for k, v in counts.items() if k != "truncated"), **counts}


# --------------------------------------------------------------------- HAR geri dönüşü


def exchanges_from_har(har_path: Path) -> list[Exchange]:
    """Eski yakalamalar için HAR'dan değişim listesi.

    Metin gövdeleri HAR'da UTF-8'e çözülmüş durduğundan UTF-8 olmayan
    kaynaklarda özgün baytlarla birebir aynı olmayabilir; bu kayıtlar
    `WebDamga-Body-Source: har-text` ile işaretlenir.
    """
    data = json.loads(Path(har_path).read_text(encoding="utf-8"))
    out: list[Exchange] = []
    for entry in data.get("log", {}).get("entries", []):
        req, resp = entry.get("request", {}), entry.get("response", {})
        url = req.get("url", "")
        if urlsplit(url).scheme not in ("http", "https"):
            continue
        content = resp.get("content", {})
        text = content.get("text")
        if text is None:
            body, source = b"", "har-base64"
        elif content.get("encoding") == "base64":
            body, source = base64.b64decode(text), "har-base64"
        else:
            body, source = text.encode("utf-8"), "har-text"
        post = (req.get("postData") or {}).get("text")
        try:
            started = datetime.fromisoformat(entry["startedDateTime"])
        except (KeyError, ValueError):
            started = datetime.now(UTC)
        out.append(
            Exchange(
                url=url,
                method=req.get("method", "GET"),
                request_headers=[(h["name"], h["value"]) for h in req.get("headers", [])],
                request_body=post.encode("utf-8") if post else None,
                status=int(resp.get("status") or 0),
                status_text=resp.get("statusText", ""),
                response_headers=[(h["name"], h["value"]) for h in resp.get("headers", [])],
                body=body,
                started=started,
                server_ip=(entry.get("serverIPAddress") or "").strip("[]") or None,
                body_source=source,
            )
        )
    return out
