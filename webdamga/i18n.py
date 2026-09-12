"""Basit iki dilli (EN/TR) metin katmanı.

Dil seçimi:
  CLI  : `--lang` seçeneği > `WEBDAMGA_LANG` > sistem locale (LC_ALL/LANG) > en
  Web  : `?lang=` > `webdamga_lang` çerezi > `Accept-Language` > en

Anahtarlar İngilizce katalogda tanımlıdır; bir anahtar çeviride yoksa
İngilizcesine, o da yoksa anahtarın kendisine düşer.
"""

from __future__ import annotations

import os

DEFAULT_LANG = "en"
SUPPORTED_LANGS: tuple[str, ...] = ("en", "tr")
LANG_COOKIE = "webdamga_lang"

_EN: dict[str, str] = {
    # --- CLI ---
    "cli.app.help": "webdamga: local web evidence and archiving tool",
    "cli.opt.data_dir": "Data directory (default: ./data)",
    "cli.opt.lang": "Interface language: en or tr",
    "cli.capture.help": "Capture a URL and seal the evidence folder.",
    "cli.capture.arg.url": "URL to capture",
    "cli.capture.opt.full_page": "Full page screenshot",
    "cli.capture.opt.timeout": "Navigation timeout (s)",
    "cli.capture.opt.wait_until": "load|domcontentloaded|networkidle|commit",
    "cli.capture.opt.wait": "Extra wait after load (s)",
    "cli.capture.opt.width": "Viewport width",
    "cli.capture.opt.height": "Viewport height",
    "cli.capture.opt.user_agent": "Override the User-Agent",
    "cli.capture.opt.headful": "Run the browser visibly (no PDF)",
    "cli.capture.capturing": "capturing",
    "cli.field.id": "id",
    "cli.field.final_url": "final URL",
    "cli.field.http": "HTTP",
    "cli.field.title": "title",
    "cli.field.server_ip": "server IP",
    "cli.field.tls": "TLS",
    "cli.field.resources": "resources",
    "cli.field.folder": "folder",
    "cli.field.manifest": "manifest sha256",
    "cli.resources.value.one": "{count} request, {kb} KB",
    "cli.resources.value.other": "{count} requests, {kb} KB",
    "cli.warning": "warning:",
    "cli.list.help": "List recent captures.",
    "cli.list.opt.limit": "How many records to show",
    "cli.list.empty": "No captures yet.",
    "cli.col.id": "id",
    "cli.col.url": "URL",
    "cli.col.http": "HTTP",
    "cli.col.date_utc": "date (UTC)",
    "cli.verify.help": "Verify a capture folder against its manifest (integrity check).",
    "cli.verify.arg.id": "Capture id",
    "cli.verify.not_found": "Not found:",
    "cli.verify.title": "verification",
    "cli.col.file": "file",
    "cli.col.status": "status",
    "cli.verify.intact": "INTACT: no file has been altered.",
    "cli.verify.broken": "BROKEN: the capture folder has been changed.",
    "cli.serve.help": "Start the local web interface.",
    "cli.serve.opt.host": "Interface to bind",
    "cli.serve.opt.port": "Port to listen on",
    "cli.serve.starting": "interface",
    "cli.serve.data": "data",
    "cli.version.help": "Print the version.",
    # --- Web, shared ---
    "web.tagline": "local web evidence tool",
    "web.nav.all_captures": "all captures",
    "web.col.id": "id",
    "web.col.url": "URL",
    "web.col.http": "HTTP",
    "web.col.date_utc": "date (UTC)",
    "web.col.file": "file",
    "web.col.size": "size",
    "web.col.sha256": "SHA-256",
    "web.status.ok": "ok",
    "web.status.modified": "modified",
    "web.status.missing": "missing",
    "web.status.unlisted": "unlisted",
    # --- Web, index ---
    "web.index.new_capture": "New capture",
    "web.index.url_placeholder": "https://example.com/login",
    "web.index.wait_until": "wait-until",
    "web.index.timeout": "timeout (s)",
    "web.index.extra_wait": "extra wait (s)",
    "web.index.width": "width",
    "web.index.height": "height",
    "web.index.full_page": "full page",
    "web.index.submit": "Capture",
    "web.index.submitting": "Capturing…",
    "web.index.hint": "A capture takes 5 to 30 seconds; the page will not respond meanwhile.",
    "web.index.captures": "Captures",
    "web.index.empty": "No captures yet.",
    "web.badge.error": "error",
    # --- Web, detail ---
    "web.detail.summary": "Summary",
    "web.detail.requested_url": "requested URL",
    "web.detail.final_url": "final URL",
    "web.detail.http": "HTTP",
    "web.detail.title": "title",
    "web.detail.requested_at": "requested",
    "web.detail.completed_at": "completed",
    "web.detail.server_ip": "server IP",
    "web.detail.tls": "TLS",
    "web.detail.resources": "resources",
    "web.detail.browser": "browser",
    "web.detail.user_agent": "User-Agent",
    "web.detail.captured_by": "captured by",
    "web.detail.screenshot": "Screenshot",
    "web.detail.screenshot_alt": "screenshot",
    "web.detail.redirect_chain": "Redirect chain",
    "web.detail.final_marker": "(final)",
    "web.detail.evidence": "Evidence & SHA-256",
    "web.detail.verify_btn": "Verify integrity",
    "web.detail.verifying": "Verifying…",
    "web.detail.intact": "INTACT: no file has been altered.",
    "web.detail.broken": "BROKEN: changes detected in the folder.",
    "web.detail.verify_failed": "Verification failed:",
    "web.detail.requests.one": "{count} request",
    "web.detail.requests.other": "{count} requests",
    "web.detail.metadata_json": "metadata (JSON)",
}

_TR: dict[str, str] = {
    # --- CLI ---
    "cli.app.help": "webdamga: yerel web kanıt/arşiv aracı",
    "cli.opt.data_dir": "Veri klasörü (varsayılan: ./data)",
    "cli.opt.lang": "Arayüz dili: en ya da tr",
    "cli.capture.help": "Bir URL'yi yakala ve kanıt klasörünü mühürle.",
    "cli.capture.arg.url": "Yakalanacak URL",
    "cli.capture.opt.full_page": "Tam sayfa ekran görüntüsü",
    "cli.capture.opt.timeout": "Gezinme zaman aşımı (sn)",
    "cli.capture.opt.wait_until": "load|domcontentloaded|networkidle|commit",
    "cli.capture.opt.wait": "Yükleme sonrası ek bekleme (sn)",
    "cli.capture.opt.width": "Görünüm genişliği",
    "cli.capture.opt.height": "Görünüm yüksekliği",
    "cli.capture.opt.user_agent": "User-Agent'ı geçersiz kıl",
    "cli.capture.opt.headful": "Tarayıcıyı görünür çalıştır (PDF üretilmez)",
    "cli.capture.capturing": "yakalıyor",
    "cli.field.id": "id",
    "cli.field.final_url": "nihai URL",
    "cli.field.http": "HTTP",
    "cli.field.title": "başlık",
    "cli.field.server_ip": "sunucu IP",
    "cli.field.tls": "TLS",
    "cli.field.resources": "kaynaklar",
    "cli.field.folder": "klasör",
    "cli.field.manifest": "manifest sha256",
    "cli.resources.value.one": "{count} istek, {kb} KB",
    "cli.resources.value.other": "{count} istek, {kb} KB",
    "cli.warning": "uyarı:",
    "cli.list.help": "Son yakalamaları listele.",
    "cli.list.opt.limit": "Gösterilecek kayıt sayısı",
    "cli.list.empty": "Kayıt yok.",
    "cli.col.id": "id",
    "cli.col.url": "URL",
    "cli.col.http": "HTTP",
    "cli.col.date_utc": "tarih (UTC)",
    "cli.verify.help": "Bir yakalama klasörünü manifestoya göre doğrula (bütünlük kontrolü).",
    "cli.verify.arg.id": "Yakalama id'si",
    "cli.verify.not_found": "Bulunamadı:",
    "cli.verify.title": "doğrulama",
    "cli.col.file": "dosya",
    "cli.col.status": "durum",
    "cli.verify.intact": "BÜTÜN: hiçbir dosya değiştirilmemiş.",
    "cli.verify.broken": "BOZULMUŞ: yakalama klasöründe değişiklik var.",
    "cli.serve.help": "Yerel web arayüzünü başlat.",
    "cli.serve.opt.host": "Dinlenecek arayüz",
    "cli.serve.opt.port": "Dinlenecek port",
    "cli.serve.starting": "arayüz",
    "cli.serve.data": "veri",
    "cli.version.help": "Sürümü yazdır.",
    # --- Web, ortak ---
    "web.tagline": "yerel web kanıt aracı",
    "web.nav.all_captures": "tüm yakalamalar",
    "web.col.id": "id",
    "web.col.url": "URL",
    "web.col.http": "HTTP",
    "web.col.date_utc": "tarih (UTC)",
    "web.col.file": "dosya",
    "web.col.size": "boyut",
    "web.col.sha256": "SHA-256",
    "web.status.ok": "tamam",
    "web.status.modified": "değiştirilmiş",
    "web.status.missing": "eksik",
    "web.status.unlisted": "listede yok",
    # --- Web, ana sayfa ---
    "web.index.new_capture": "Yeni yakalama",
    "web.index.url_placeholder": "https://ornek.com/giris",
    "web.index.wait_until": "wait-until",
    "web.index.timeout": "zaman aşımı (sn)",
    "web.index.extra_wait": "ek bekleme (sn)",
    "web.index.width": "genişlik",
    "web.index.height": "yükseklik",
    "web.index.full_page": "tam sayfa",
    "web.index.submit": "Yakala",
    "web.index.submitting": "Yakalanıyor…",
    "web.index.hint": "Yakalama 5 ila 30 sn sürebilir; bu sürede sayfa yanıt vermez.",
    "web.index.captures": "Yakalamalar",
    "web.index.empty": "Henüz yakalama yok.",
    "web.badge.error": "hata",
    # --- Web, detay ---
    "web.detail.summary": "Özet",
    "web.detail.requested_url": "istenen URL",
    "web.detail.final_url": "nihai URL",
    "web.detail.http": "HTTP",
    "web.detail.title": "başlık",
    "web.detail.requested_at": "istek",
    "web.detail.completed_at": "tamamlanma",
    "web.detail.server_ip": "sunucu IP",
    "web.detail.tls": "TLS",
    "web.detail.resources": "kaynaklar",
    "web.detail.browser": "tarayıcı",
    "web.detail.user_agent": "User-Agent",
    "web.detail.captured_by": "yakalayan",
    "web.detail.screenshot": "Ekran görüntüsü",
    "web.detail.screenshot_alt": "ekran görüntüsü",
    "web.detail.redirect_chain": "Yönlendirme zinciri",
    "web.detail.final_marker": "(nihai)",
    "web.detail.evidence": "Deliller & SHA-256",
    "web.detail.verify_btn": "Bütünlüğü doğrula",
    "web.detail.verifying": "Doğrulanıyor…",
    "web.detail.intact": "BÜTÜN: hiçbir dosya değiştirilmemiş.",
    "web.detail.broken": "BOZULMUŞ: klasörde değişiklik tespit edildi.",
    "web.detail.verify_failed": "Doğrulama başarısız:",
    "web.detail.requests.one": "{count} istek",
    "web.detail.requests.other": "{count} istek",
    "web.detail.metadata_json": "metadata (JSON)",
}

_CATALOG: dict[str, dict[str, str]] = {"en": _EN, "tr": _TR}


def normalize_lang(value: str | None) -> str | None:
    """'tr-TR', 'TR', 'tr_TR.UTF-8' gibi değerleri 'tr'ye indirger."""
    if not value:
        return None
    code = value.strip().lower().replace("_", "-").split(".")[0].split("-")[0]
    return code if code in SUPPORTED_LANGS else None


def detect_lang() -> str:
    """Ortam değişkenlerinden dili tespit eder."""
    for var in ("WEBDAMGA_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        lang = normalize_lang(os.environ.get(var))
        if lang:
            return lang
    return DEFAULT_LANG


def parse_accept_language(header: str | None) -> str | None:
    """Accept-Language başlığından desteklenen en yüksek q'lu dili seçer."""
    if not header:
        return None
    ranked: list[tuple[float, int, str]] = []
    for order, part in enumerate(header.split(",")):
        piece = part.strip()
        if not piece:
            continue
        code, _, params = piece.partition(";")
        quality = 1.0
        for param in params.split(";"):
            key, _, val = param.partition("=")
            if key.strip() == "q":
                try:
                    quality = float(val)
                except ValueError:
                    quality = 0.0
        ranked.append((quality, -order, code.strip()))
    for quality, _, code in sorted(ranked, reverse=True):
        if quality <= 0:
            continue
        lang = normalize_lang(code)
        if lang:
            return lang
    return None


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    """`key` için `lang` dilindeki metni döner, yoksa İngilizcesine düşer."""
    catalog = _CATALOG.get(lang or "", _EN)
    text = catalog.get(key) or _EN.get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def tn(key: str, count: int, lang: str | None = None, **kwargs: object) -> str:
    """Sayıya göre `key.one` / `key.other` anahtarını seçer.

    Türkçe sayıdan sonra çoğul eki almadığı için iki varyant da aynı olabilir;
    ayrım İngilizce için gerekli ("1 request" / "2 requests").
    """
    suffix = "one" if abs(count) == 1 else "other"
    return t(f"{key}.{suffix}", lang, count=count, **kwargs)


def translator(lang: str):
    """Tek bir dile bağlanmış `t` ve `tn` üretir (şablonlarda kullanışlı)."""

    def _translate(key: str, count: int | None = None, **kwargs: object) -> str:
        if count is not None:
            return tn(key, count, lang, **kwargs)
        return t(key, lang, **kwargs)

    return _translate
