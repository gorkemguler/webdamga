"""Yerel arayüzü kötü niyetli web sayfalarından koruyan katman.

webdamga localhost'ta çalışsa da, kullanıcının tarayıcısında açık olan
herhangi bir site ona istek göndermeye çalışabilir. Üstelik araç, düşman
içeriği (phishing sayfaları) bilerek indirip saklıyor. Üç risk ele alınır:

1. Şema: yalnızca http/https yakalanır. file://, chrome://, javascript:
   gibi şemalar reddedilir, yoksa kötü bir sayfa webdamga'ya yerel dosya
   yakalatıp içeriğini okuyabilir.
2. CSRF: durum değiştiren istekler (POST/PATCH/DELETE) yalnızca arayüzün
   kendisinden gelebilir; Origin/Referer başlığı beklenen host'a ait olmalı.
3. DNS rebinding: Host başlığı beklenen host'lardan biri olmalı; böylece bir
   saldırganın alan adı 127.0.0.1'e çözülse bile istek reddedilir.

Ayrıca yakalanan artefaktlar (dom.html, page.mhtml, ...) arayüzle aynı
origin'de ÇALIŞTIRILMADAN sunulur (indirme + sandbox CSP); bkz. api.py.
"""

from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

ALLOWED_SCHEMES = ("http", "https")
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Loopback her zaman güvenli sayılır; ek host'lar WEBDAMGA_ALLOWED_HOSTS ile.
_DEFAULT_HOSTS = ("localhost", "127.0.0.1", "[::1]", "::1")

# Yakalanan artefakt olarak sunulduğunda tarayıcıda hâlâ kod çalıştırabilecek
# ya da başka içeriğe gömülebilecek türler: origin'e sokulmadan, indirme olarak.
ACTIVE_SUFFIXES = frozenset({".html", ".htm", ".mhtml", ".svg", ".xml", ".xhtml"})


class UrlNotAllowed(ValueError):
    """Yakalama için kabul edilmeyen URL (yanlış şema, boş host, ...)."""


def validate_capture_url(url: str) -> str:
    """Yakalanacak URL'yi doğrular; sadece http/https ve gerçek bir host."""
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise UrlNotAllowed(f"only http and https can be captured, not '{parts.scheme or url}'")
    if not parts.hostname:
        raise UrlNotAllowed("the URL has no host")
    return url


def allowed_hosts() -> tuple[str, ...]:
    extra = os.environ.get("WEBDAMGA_ALLOWED_HOSTS", "")
    names = [h.strip().lower() for h in extra.split(",") if h.strip()]
    return (*_DEFAULT_HOSTS, *names)


def _host_only(value: str) -> str:
    """'host:port' ya da 'scheme://host:port' değerinden host kısmını alır."""
    value = value.strip().lower()
    if "://" in value:
        value = urlsplit(value).netloc
    # IPv6: [::1]:8000 -> [::1]
    if value.startswith("["):
        return value[: value.index("]") + 1] if "]" in value else value
    return value.rsplit(":", 1)[0] if ":" in value else value


def _is_loopback(host: str) -> bool:
    bare = host.strip("[]")
    try:
        return ipaddress.ip_address(bare).is_loopback
    except ValueError:
        return bare == "localhost"


def host_is_allowed(host_header: str | None, allowed: tuple[str, ...]) -> bool:
    if not host_header:
        return False
    host = _host_only(host_header)
    return host in allowed or _is_loopback(host)


def origin_is_allowed(origin: str | None, referer: str | None, allowed: tuple[str, ...]) -> bool:
    """CSRF kontrolü: Origin (yoksa Referer) beklenen host'a ait olmalı.

    İkisi de yoksa istek bir tarayıcı formundan gelmemiştir (curl, betik);
    bunlar reddedilmez, çünkü CSRF yalnızca tarayıcı kaynaklı isteklerde olur.
    """
    source = origin or referer
    if source is None:
        return True
    if source == "null":
        return False  # sandboxed iframe, data: sayfa vb.
    host = _host_only(source)
    return host in allowed or _is_loopback(host)


class GuardMiddleware(BaseHTTPMiddleware):
    """Host ve CSRF kontrolünü tüm isteklere uygular."""

    async def dispatch(self, request: Request, call_next):
        allowed = allowed_hosts()
        if not host_is_allowed(request.headers.get("host"), allowed):
            return JSONResponse({"detail": "host not allowed"}, status_code=421)
        if request.method in _UNSAFE_METHODS and not origin_is_allowed(
            request.headers.get("origin"), request.headers.get("referer"), allowed
        ):
            return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        return await call_next(request)


def artifact_headers(filename: str) -> tuple[bool, dict[str, str]]:
    """Yakalanan bir dosya nasıl sunulmalı: (inline_mi, ek başlıklar).

    Aktif türler (html, mhtml, svg, ...) hiçbir zaman inline sunulmaz ve
    sandbox CSP ile gelir; tarayıcıda açılsalar bile script çalıştıramaz,
    form gönderemez, başka origin'e istek atamazlar.
    """
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    headers = {"X-Content-Type-Options": "nosniff"}
    if suffix in ACTIVE_SUFFIXES:
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
        return False, headers
    # png/pdf/json/log gibi türler origin'de zararsız; yine de sniff kapalı.
    return True, headers


_SLUG = re.compile(r"[^a-zA-Z0-9._-]")


def safe_download_name(name: str) -> str:
    """Content-Disposition'a konacak dosya adını başlık enjeksiyonuna karşı temizler."""
    return _SLUG.sub("_", name) or "file"
