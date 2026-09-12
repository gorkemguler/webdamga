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
    "web.index.submitting": "Adding to the queue…",
    "web.index.hint": "Captures run in the background, so you can keep working while they finish.",
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
    # --- WARC ---
    "cli.capture.opt.warc": "Also write a replayable archive.warc.gz",
    "cli.warc.help": "Build a WARC file from the HAR of an older capture that does not have one.",
    "cli.warc.opt.output": "Output path (default: ./webdamga-<id>.warc.gz)",
    "cli.warc.exists": "This capture already has a WARC sealed in its manifest: {path}",
    "cli.warc.no_har": "This capture has no network.har to build from.",
    "cli.warc.records": "records",
    "cli.warc.written": "file",
    "cli.warc.lossy": "{count} text responses came from the HAR, where the browser had already "
    "decoded them to UTF-8. Their bytes may differ from what the server sent; those records are "
    "marked WebDamga-Body-Source: har-text. New captures do not have this problem.",
    "web.detail.warc_hint": "archive.warc.gz replays in ReplayWeb.page (replayweb.page) or pywb.",
    # --- Network route ---
    "cli.capture.opt.proxy": "Capture through a proxy, e.g. socks5://127.0.0.1:9050 or http://user:pass@host:3128",
    "cli.capture.opt.tor": "Capture through Tor (socks5://127.0.0.1:9050)",
    "cli.capture.opt.via": "Capture through a named proxy profile from proxies.json",
    "cli.capture.opt.record_egress": "Record the egress IP (asks check.torproject.org)",
    "cli.capture.route_conflict": "Use only one of --proxy, --tor and --via.",
    "cli.field.route": "route",
    "cli.field.egress": "egress IP",
    "cli.field.via_tor": "Tor",
    "cli.proxies.help": "List proxy profiles usable with --via.",
    "cli.col.profile": "profile",
    "cli.col.proxy": "proxy",
    "cli.proxies.file": "Profiles are read from {path}",
    "web.index.route": "network route",
    "web.index.route.direct": "direct",
    "web.index.record_egress": "record egress IP",
    "web.detail.route": "network route",
    "web.detail.route.direct": "direct",
    "web.detail.egress": "egress IP",
    "web.detail.egress.tor": "confirmed Tor exit",
    "web.detail.egress.not_tor": "not a Tor exit",
    "report.field.route": "Network route",
    "report.field.egress": "Egress IP",
    "report.route.direct": "Direct connection from the capturing machine",
    # --- Queue ---
    "web.queue.title": "In progress",
    "web.queue.status": "status",
    "web.queue.created": "queued (UTC)",
    "web.job.title": "Capture job",
    "web.job.status.queued": "queued",
    "web.job.status.running": "capturing",
    "web.job.status.done": "done",
    "web.job.status.failed": "failed",
    "web.job.status.cancelled": "cancelled",
    "web.job.hint": "This page refreshes on its own and opens the capture once it is ready.",
    "web.job.open_capture": "Open the capture",
    "web.job.cancel": "Cancel",
    "web.job.id": "job id",
    "web.job.created": "queued",
    "cli.jobs.help": "Show the capture queue.",
    "cli.jobs.opt.all": "Include finished jobs",
    "cli.jobs.empty": "The queue is empty.",
    "cli.col.source": "source",
    "cli.col.capture": "capture",
    # --- Sharing / export ---
    "web.detail.share": "Send as evidence",
    "web.detail.share.hint": (
        "Download the whole capture as one package you can attach to an abuse report, "
        "or just the PDF summary."
    ),
    "web.detail.download_zip": "Evidence package (.zip)",
    "web.detail.download_pdf": "Report (PDF)",
    "web.detail.package_note": (
        "The package contains every artefact, the SHA-256 manifest and the PDF report. "
        "Keep the package checksum shown after download alongside your report."
    ),
    # --- CLI export ---
    "cli.export.help": "Export a capture as a single evidence package you can send.",
    "cli.export.arg.id": "Capture id",
    "cli.export.opt.output": "Output path (default: ./webdamga-<id>.zip)",
    "cli.export.opt.pdf": "Include the PDF evidence report",
    "cli.export.building_pdf": "rendering the PDF report…",
    "cli.export.packaging": "packaging…",
    "cli.export.written": "package",
    "cli.export.size": "size",
    "cli.export.sha": "package sha256",
    "cli.export.manifest_sha": "manifest sha256",
    "cli.export.done": "Attach this file to your report. The recipient can verify it "
    "without webdamga, see README.txt inside the package.",
    # --- PDF report ---
    "report.title": "Web capture evidence report",
    "report.generated": "Produced by webdamga v{version} on {date}",
    "report.section.capture": "Capture",
    "report.section.network": "Network and TLS",
    "report.section.screenshot": "Screenshot",
    "report.section.redirects": "Redirect chain",
    "report.section.files": "Artefacts and SHA-256 checksums",
    "report.section.verify": "How to verify this evidence",
    "report.field.capture_id": "Capture id",
    "report.field.requested_url": "Requested URL",
    "report.field.final_url": "Final URL",
    "report.field.http": "HTTP status",
    "report.field.page_title": "Page title",
    "report.field.requested_at": "Requested at (UTC)",
    "report.field.completed_at": "Completed at (UTC)",
    "report.field.server_ip": "Server IP",
    "report.field.tls": "TLS",
    "report.field.tls_valid": "Certificate validity",
    "report.field.browser": "Browser",
    "report.field.user_agent": "User-Agent",
    "report.field.captured_by": "Captured on",
    "report.field.resources": "Resources loaded",
    "report.field.manifest_sha": "Manifest SHA-256",
    "report.screenshot.caption": "Above the fold, as the page rendered at capture time. "
    "The full page screenshot is included in the package as screenshot.png.",
    "report.screenshot.missing": "No screenshot was produced for this capture.",
    "report.verify.intro": "Every artefact in this package is listed in manifest.json "
    "together with its SHA-256 checksum. To confirm nothing has been altered:",
    "report.verify.step1": "Recompute the checksums and compare them with manifest.json.",
    "report.verify.step2": "Confirm manifest.json itself still matches manifest.sha256.",
    "report.verify.step3": "With webdamga installed, both steps run at once:",
    "report.verify.note": "README.txt and evidence-report.pdf were added when the package "
    "was built, so they are deliberately not listed in manifest.json.",
    "report.footer": "This report describes what the named URL served at the stated time. "
    "It is a technical record, not a legal opinion.",
    "report.col.file": "File",
    "report.col.size": "Size",
    "report.col.sha256": "SHA-256",
    "report.error": "This capture ended with an error",
    # --- Package README.txt ---
    "pkg.readme": """webdamga evidence package
=========================

Capture id : {capture_id}
URL        : {url}
Captured   : {captured} (UTC)
Packaged   : {packaged} (UTC)

WHAT IS IN HERE
---------------
This is a record of what {url} served at the time above. It was captured
automatically with a real Chromium browser.

  evidence-report.pdf     short human readable summary
  screenshot.png          full page screenshot
  screenshot-viewport.png what was visible without scrolling
  response.html           the raw HTTP response body, before JavaScript
  dom.html                the page after JavaScript had run
  page.mhtml              self contained archive, opens in Chrome
  page.pdf                the page printed to PDF
  network.har             every request and response, bodies included
  archive.warc.gz         replayable web archive (ReplayWeb.page, pywb), original bytes
  console.log             browser console output and page errors
  metadata.json           URLs, redirects, headers, server IP, TLS, timing
  manifest.json           SHA-256 of every file above
  manifest.sha256         checksum of manifest.json itself

HOW TO VERIFY IT
----------------
1. Recompute the checksums and compare against manifest.json:

     shasum -a 256 screenshot.png dom.html response.html

2. Confirm manifest.json has not been edited either:

     shasum -a 256 -c manifest.sha256

3. If you have webdamga installed, both checks run together:

     webdamga verify {capture_id}

README.txt and evidence-report.pdf were created while packaging, so they are
not listed in manifest.json. Every other file is.

Produced by webdamga v{version}. https://github.com/gorkemguler/webdamga
""",
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
    "web.index.submitting": "Kuyruğa ekleniyor…",
    "web.index.hint": "Yakalamalar arka planda çalışır, bitmelerini beklemeden devam edebilirsin.",
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
    # --- WARC ---
    "cli.capture.opt.warc": "Yeniden oynatılabilir archive.warc.gz de üret",
    "cli.warc.help": "WARC'ı olmayan eski bir yakalama için HAR'dan WARC dosyası üret.",
    "cli.warc.opt.output": "Çıktı yolu (varsayılan: ./webdamga-<id>.warc.gz)",
    "cli.warc.exists": "Bu yakalamanın manifestosunda mühürlü bir WARC zaten var: {path}",
    "cli.warc.no_har": "Bu yakalamada WARC üretilecek network.har yok.",
    "cli.warc.records": "kayıt",
    "cli.warc.written": "dosya",
    "cli.warc.lossy": "{count} metin yanıtı, tarayıcının zaten UTF-8'e çözdüğü HAR'dan geldi. "
    "Baytları sunucunun gönderdiğinden farklı olabilir; bu kayıtlar WebDamga-Body-Source: "
    "har-text ile işaretlendi. Yeni yakalamalarda bu sorun yok.",
    "web.detail.warc_hint": "archive.warc.gz, ReplayWeb.page (replayweb.page) ya da pywb ile yeniden oynatılabilir.",
    # --- Ağ yolu ---
    "cli.capture.opt.proxy": "Proxy üzerinden yakala, ör. socks5://127.0.0.1:9050 ya da http://kullanici:parola@sunucu:3128",
    "cli.capture.opt.tor": "Tor üzerinden yakala (socks5://127.0.0.1:9050)",
    "cli.capture.opt.via": "proxies.json içindeki adlandırılmış bir proxy profilinden yakala",
    "cli.capture.opt.record_egress": "Çıkış IP'sini kaydet (check.torproject.org'a sorar)",
    "cli.capture.route_conflict": "--proxy, --tor ve --via seçeneklerinden yalnızca birini kullan.",
    "cli.field.route": "ağ yolu",
    "cli.field.egress": "çıkış IP",
    "cli.field.via_tor": "Tor",
    "cli.proxies.help": "--via ile kullanılabilecek proxy profillerini listele.",
    "cli.col.profile": "profil",
    "cli.col.proxy": "proxy",
    "cli.proxies.file": "Profiller {path} dosyasından okunur",
    "web.index.route": "ağ yolu",
    "web.index.route.direct": "doğrudan",
    "web.index.record_egress": "çıkış IP'sini kaydet",
    "web.detail.route": "ağ yolu",
    "web.detail.route.direct": "doğrudan",
    "web.detail.egress": "çıkış IP",
    "web.detail.egress.tor": "Tor çıkışı doğrulandı",
    "web.detail.egress.not_tor": "Tor çıkışı değil",
    "report.field.route": "Ağ yolu",
    "report.field.egress": "Çıkış IP",
    "report.route.direct": "Yakalayan makineden doğrudan bağlantı",
    # --- Kuyruk ---
    "web.queue.title": "Sürenler",
    "web.queue.status": "durum",
    "web.queue.created": "eklenme (UTC)",
    "web.job.title": "Yakalama işi",
    "web.job.status.queued": "sırada",
    "web.job.status.running": "yakalanıyor",
    "web.job.status.done": "tamamlandı",
    "web.job.status.failed": "başarısız",
    "web.job.status.cancelled": "iptal edildi",
    "web.job.hint": "Bu sayfa kendini yeniler, yakalama hazır olunca açılır.",
    "web.job.open_capture": "Yakalamayı aç",
    "web.job.cancel": "İptal et",
    "web.job.id": "iş id",
    "web.job.created": "eklenme",
    "cli.jobs.help": "Yakalama kuyruğunu göster.",
    "cli.jobs.opt.all": "Bitmiş işleri de göster",
    "cli.jobs.empty": "Kuyruk boş.",
    "cli.col.source": "kaynak",
    "cli.col.capture": "yakalama",
    # --- Paylaşım / dışa aktarma ---
    "web.detail.share": "Kanıt olarak gönder",
    "web.detail.share.hint": (
        "Yakalamanın tamamını ihbara ekleyebileceğin tek bir paket olarak indir, ya da sadece PDF özeti al."
    ),
    "web.detail.download_zip": "Kanıt paketi (.zip)",
    "web.detail.download_pdf": "Rapor (PDF)",
    "web.detail.package_note": (
        "Paket bütün delilleri, SHA-256 manifestosunu ve PDF raporu içerir. "
        "İndirdikten sonra görünen paket özetini ihbarınla birlikte sakla."
    ),
    # --- CLI dışa aktarma ---
    "cli.export.help": "Bir yakalamayı gönderilebilir tek bir kanıt paketi olarak dışa aktar.",
    "cli.export.arg.id": "Yakalama id'si",
    "cli.export.opt.output": "Çıktı yolu (varsayılan: ./webdamga-<id>.zip)",
    "cli.export.opt.pdf": "PDF kanıt raporunu da ekle",
    "cli.export.building_pdf": "PDF rapor hazırlanıyor…",
    "cli.export.packaging": "paketleniyor…",
    "cli.export.written": "paket",
    "cli.export.size": "boyut",
    "cli.export.sha": "paket sha256",
    "cli.export.manifest_sha": "manifest sha256",
    "cli.export.done": "Bu dosyayı ihbarına ekleyebilirsin. Karşı taraf webdamga "
    "olmadan da doğrulayabilir, paketin içindeki README.txt'e bak.",
    # --- PDF rapor ---
    "report.title": "Web yakalama kanıt raporu",
    "report.generated": "webdamga v{version} tarafından {date} tarihinde üretildi",
    "report.section.capture": "Yakalama",
    "report.section.network": "Ağ ve TLS",
    "report.section.screenshot": "Ekran görüntüsü",
    "report.section.redirects": "Yönlendirme zinciri",
    "report.section.files": "Deliller ve SHA-256 özetleri",
    "report.section.verify": "Bu kanıt nasıl doğrulanır",
    "report.field.capture_id": "Yakalama id'si",
    "report.field.requested_url": "İstenen URL",
    "report.field.final_url": "Nihai URL",
    "report.field.http": "HTTP durumu",
    "report.field.page_title": "Sayfa başlığı",
    "report.field.requested_at": "İstek zamanı (UTC)",
    "report.field.completed_at": "Tamamlanma (UTC)",
    "report.field.server_ip": "Sunucu IP",
    "report.field.tls": "TLS",
    "report.field.tls_valid": "Sertifika geçerliliği",
    "report.field.browser": "Tarayıcı",
    "report.field.user_agent": "User-Agent",
    "report.field.captured_by": "Yakalayan makine",
    "report.field.resources": "Yüklenen kaynaklar",
    "report.field.manifest_sha": "Manifest SHA-256",
    "report.screenshot.caption": "Yakalama anında sayfanın ekran üstünde göründüğü hâli. "
    "Tam sayfa görüntü pakette screenshot.png olarak yer alıyor.",
    "report.screenshot.missing": "Bu yakalamada ekran görüntüsü üretilemedi.",
    "report.verify.intro": "Paketteki her delil, SHA-256 özetiyle birlikte manifest.json "
    "içinde listelidir. Hiçbir şeyin değişmediğini doğrulamak için:",
    "report.verify.step1": "Özetleri yeniden hesaplayıp manifest.json ile karşılaştırın.",
    "report.verify.step2": "manifest.json'un kendisinin de manifest.sha256 ile eşleştiğini kontrol edin.",
    "report.verify.step3": "webdamga kuruluysa iki adım tek komutla çalışır:",
    "report.verify.note": "README.txt ve evidence-report.pdf paketleme sırasında eklendiği "
    "için manifest.json'da bilinçli olarak yer almaz.",
    "report.footer": "Bu rapor, adı geçen URL'nin belirtilen zamanda ne sunduğunu belgeler. "
    "Teknik bir kayıttır, hukuki görüş değildir.",
    "report.col.file": "Dosya",
    "report.col.size": "Boyut",
    "report.col.sha256": "SHA-256",
    "report.error": "Bu yakalama hatayla sonuçlandı",
    # --- Paket içi README.txt ---
    "pkg.readme": """webdamga kanıt paketi
=====================

Yakalama id : {capture_id}
URL         : {url}
Yakalanma   : {captured} (UTC)
Paketlenme  : {packaged} (UTC)

PAKETTE NE VAR
--------------
Bu paket, {url} adresinin yukarıdaki zamanda ne sunduğunun kaydıdır.
Gerçek bir Chromium tarayıcısıyla otomatik olarak alınmıştır.

  evidence-report.pdf     kısa, insan okur özet
  screenshot.png          tam sayfa ekran görüntüsü
  screenshot-viewport.png kaydırmadan görünen kısım
  response.html           ham HTTP yanıt gövdesi, JavaScript öncesi
  dom.html                JavaScript çalıştıktan sonraki sayfa
  page.mhtml              kendi kendine yeten arşiv, Chrome'da açılır
  page.pdf                sayfanın PDF çıktısı
  network.har             tüm istek ve yanıtlar, gövdeler dahil
  archive.warc.gz         yeniden oynatılabilir web arşivi (ReplayWeb.page, pywb), özgün baytlar
  console.log             tarayıcı konsolu ve sayfa hataları
  metadata.json           URL'ler, yönlendirmeler, başlıklar, sunucu IP, TLS
  manifest.json           yukarıdaki her dosyanın SHA-256 özeti
  manifest.sha256         manifest.json'un kendi özeti

NASIL DOĞRULANIR
----------------
1. Özetleri yeniden hesaplayıp manifest.json ile karşılaştırın:

     shasum -a 256 screenshot.png dom.html response.html

2. manifest.json'un da değişmediğini kontrol edin:

     shasum -a 256 -c manifest.sha256

3. webdamga kuruluysa iki kontrol tek komutta çalışır:

     webdamga verify {capture_id}

README.txt ve evidence-report.pdf paketleme sırasında oluşturulduğu için
manifest.json'da listelenmez. Diğer tüm dosyalar listelidir.

webdamga v{version} ile üretildi. https://github.com/gorkemguler/webdamga
""",
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
