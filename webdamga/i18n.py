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
    "web.index.search": "Search",
    "web.index.search_placeholder": "URL, title or id",
    "web.index.clear": "clear",
    "web.index.no_match": "No capture matches your search.",
    "web.index.prev": "Newer",
    "web.index.next": "Older",
    "web.index.page_of": "page {page} of {total}",
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
    # --- Intel (abuse contacts) ---
    "cli.capture.opt.intel": "Look up registrar, network owner, ASN and abuse contacts",
    "cli.field.abuse": "abuse contacts",
    "cli.intel.help": "Look up who to report a domain or IP to (registrar, network, ASN, abuse).",
    "cli.intel.arg.target": "A URL, domain or IP address",
    "cli.intel.registrar": "registrar",
    "cli.intel.registered": "registered",
    "cli.intel.network": "network",
    "cli.intel.asn": "ASN",
    "cli.intel.no_abuse": "No abuse contact found in the registration data.",
    "web.index.intel": "look up abuse contacts",
    "web.detail.intel": "Who to report to",
    "web.detail.intel_btn": "Look up abuse contacts",
    "web.detail.intel_looking": "Looking up…",
    "web.detail.intel_hint": "Queries RDAP and Team Cymru (not the site itself) for the registrar, network owner, ASN and abuse contacts.",
    "web.detail.intel.registrar": "Registrar",
    "web.detail.intel.registered": "Registered",
    "web.detail.intel.expires": "Expires",
    "web.detail.intel.network": "Network owner",
    "web.detail.intel.asn": "ASN",
    "web.detail.intel.abuse": "Abuse contacts",
    "web.detail.intel.none": "No abuse contact found.",
    "report.section.intel": "Who to report to",
    "report.field.registrar": "Registrar",
    "report.field.registered": "Domain registered",
    "report.field.network_owner": "Network owner",
    "report.field.asn": "ASN",
    "report.field.abuse": "Abuse contacts",
    # --- Device / referer / language ---
    "cli.capture.opt.device": 'Emulate a device, e.g. "iPhone 15" (see webdamga devices)',
    "cli.capture.opt.referer": "Send this Referer header with the request",
    "cli.capture.opt.accept_language": "Accept-Language header, e.g. tr-TR,tr;q=0.9",
    "cli.field.device": "device",
    "cli.devices.help": "List device profiles usable with --device.",
    "cli.devices.opt.all": "Show every known device, not just the common ones",
    "cli.devices.more": "This is a shortlist; --all shows every device Playwright knows.",
    "web.index.device": "device",
    "web.index.device.desktop": "desktop (default)",
    "web.index.referer": "Referer",
    "web.index.accept_language": "Accept-Language",
    "web.detail.device": "emulated device",
    "report.field.device": "Emulated device",
    # --- Monitoring ---
    "web.nav.captures": "Captures",
    "web.nav.monitors": "Monitors",
    "web.monitors.title": "Monitors",
    "web.monitors.monitor": "Monitor",
    "web.monitors.new": "Watch a URL",
    "web.monitors.intro": "The URL is captured on a schedule and every capture is compared with the last "
    "successful one, so you can see when a page turns malicious, moves or goes down.",
    "web.monitors.label": "label (optional)",
    "web.monitors.every": "every",
    "web.monitors.interval.15": "15 minutes",
    "web.monitors.interval.30": "30 minutes",
    "web.monitors.interval.60": "hour",
    "web.monitors.interval.180": "3 hours",
    "web.monitors.interval.360": "6 hours",
    "web.monitors.interval.720": "12 hours",
    "web.monitors.interval.1440": "day",
    "web.monitors.minutes.one": "{count} minute",
    "web.monitors.minutes.other": "{count} minutes",
    "web.monitors.add": "Start watching",
    "web.monitors.last_change": "last change",
    "web.monitors.no_change": "none yet",
    "web.monitors.next_run": "next run (UTC)",
    "web.monitors.last_run": "last run (UTC)",
    "web.monitors.paused": "paused",
    "web.monitors.active": "active",
    "web.monitors.state": "state",
    "web.monitors.baseline": "compared against",
    "web.monitors.run_now": "Run now",
    "web.monitors.pause": "Pause",
    "web.monitors.resume": "Resume",
    "web.monitors.delete": "Delete",
    "web.monitors.delete_confirm": "Stop watching this URL? Its captures are kept.",
    "web.monitors.delete_hint": "Deleting a monitor stops future runs; the captures it made stay as evidence.",
    "web.monitors.empty": "Nothing is being watched yet.",
    "web.monitors.runs": "Runs",
    "web.monitors.change": "change",
    "web.monitors.first_run": "first capture, nothing to compare",
    "web.monitors.no_runs": "No runs yet; the first one starts within a minute.",
    "cli.monitor.help": "Watch URLs on a schedule and flag changes.",
    "cli.monitor.add.help": "Start watching a URL.",
    "cli.monitor.opt.every": "Minutes between captures (at least 5)",
    "cli.monitor.opt.label": "A name to recognise it by",
    "cli.monitor.added": "Watching #{id}: {url} every {minutes} minutes. Runs while webdamga serve or webdamga monitor run is up.",
    "cli.monitor.list.help": "List monitors.",
    "cli.monitor.empty": "Nothing is being watched.",
    "cli.monitor.pause.help": "Pause a monitor.",
    "cli.monitor.resume.help": "Resume a paused monitor.",
    "cli.monitor.remove.help": "Delete a monitor (its captures are kept).",
    "cli.monitor.arg.id": "Monitor id",
    "cli.monitor.not_found": "No monitor with id {id}.",
    "cli.monitor.done": "ok",
    "cli.monitor.run.help": "Run the scheduler and capture queue in the foreground, without the web interface.",
    "cli.monitor.running": "Scheduler running with {count} monitors. Ctrl+C to stop.",
    "cli.col.every": "every",
    "cli.col.last_change": "last change",
    "cli.col.next_run": "next run",
    # --- Diff ---
    "diff.verdict.identical": "No changes",
    "diff.verdict.minor": "Minor changes",
    "diff.verdict.major": "Significant changes",
    "diff.reason.final_host": "The page now ends up on a different host: {a} → {b}",
    "diff.reason.final_url": "Final URL changed: {a} → {b}",
    "diff.reason.http_status": "HTTP status changed: {a} → {b}",
    "diff.reason.page_title": "Page title changed: {a} → {b}",
    "diff.reason.server_ip": "Server IP changed: {a} → {b}",
    "diff.reason.tls_certificate": "TLS certificate changed (issuer {a} → {b})",
    "diff.reason.visual.major": "{percent}% of the screenshot changed",
    "diff.reason.visual.minor": "{percent}% of the screenshot changed",
    "diff.reason.text.major": "Visible text is only {percent}% similar",
    "diff.reason.text.minor": "Visible text: {added} lines added, {removed} removed",
    "diff.reason.password_field_added": "A password field appeared",
    "diff.reason.password_field_removed": "The password field is gone",
    "diff.reason.form_target_host": "A form now submits to another host: {hosts}",
    "diff.reason.forms_changed": "Forms changed: {added} added, {removed} removed",
    "diff.reason.hosts": "Contacted servers: {added} new, {removed} no longer used",
    "cli.diff.help": "Compare two captures: screenshot, visible text, forms, servers and metadata.",
    "cli.diff.arg.a": "Older capture id",
    "cli.diff.arg.b": "Newer capture id",
    "cli.diff.opt.json": "Print the full result as JSON",
    "cli.diff.visual": "screenshot changed",
    "cli.diff.text": "text similarity",
    "cli.diff.forms": "forms",
    "cli.diff.hosts_added": "new servers",
    "cli.diff.image": "visual diff",
    "cli.diff.reasons": "why",
    "web.diff.title": "Comparison",
    "web.diff.older": "older",
    "web.diff.newer": "newer",
    "web.diff.overlay": "Changes highlighted on the newer capture",
    "web.diff.reasons": "What changed",
    "web.diff.metadata": "Metadata",
    "web.diff.field": "field",
    "web.diff.forms": "Forms",
    "web.diff.forms_added": "added",
    "web.diff.forms_removed": "removed",
    "web.diff.password": "password field",
    "web.diff.resources": "Servers and scripts",
    "web.diff.hosts_added": "new servers",
    "web.diff.hosts_removed": "servers no longer used",
    "web.diff.scripts_added": "new scripts",
    "web.diff.text": "Visible text",
    "web.diff.text_summary": "{similarity}% similar, {added} lines added, {removed} removed",
    "web.diff.text_truncated": "Showing the first changes only.",
    "web.diff.none": "none",
    "web.detail.compare": "Compare with",
    "web.detail.compare_btn": "Compare",
    # --- Timestamps ---
    "cli.capture.opt.timestamp": "Get trusted timestamps (RFC 3161 and OpenTimestamps); sends only the manifest hash",
    "cli.ts.help": "Get trusted timestamps for an existing capture's manifest.",
    "cli.ts.opt.rfc3161": "Ask an RFC 3161 time stamp authority",
    "cli.ts.opt.ots": "Anchor in Bitcoin via OpenTimestamps calendars",
    "cli.ts.opt.tsa": "RFC 3161 TSA URL (default: WEBDAMGA_TSA_URL or DigiCert)",
    "cli.ts.opt.force": "Replace existing timestamps (an older timestamp is usually worth more)",
    "cli.ts.exists": "This capture already has timestamps. Use --force to replace them.",
    "cli.ts.requesting": "requesting timestamps (TSA: {tsa})…",
    "cli.ts.rfc_ok": "RFC 3161: {time} from {tsa}",
    "cli.ts.rfc_failed": "RFC 3161 failed:",
    "cli.ts.ots_ok": "OpenTimestamps: submitted to {count} calendars, Bitcoin confirmation takes a few hours",
    "cli.ts.ots_failed": "OpenTimestamps failed:",
    "cli.ts.tsa_sig_ok": "TSA signature verified",
    "cli.ts.tsa_sig_bad": "TSA SIGNATURE NOT VERIFIED",
    "cli.ts.tsa_sig_unchecked": "TSA signature not checked, openssl unavailable",
    "cli.ts.ots_pending": "pending Bitcoin confirmation",
    "cli.ts.ots_confirmed": "confirmed in Bitcoin",
    "web.index.timestamp": "trusted timestamp",
    "web.detail.timestamp": "trusted time",
    "web.detail.timestamp.none": "no trusted timestamp",
    "web.detail.timestamp.ots_pending": "OpenTimestamps pending",
    "web.detail.timestamp.ots_confirmed": "confirmed in Bitcoin",
    "web.detail.timestamp_btn": "Timestamp now",
    "web.detail.timestamping": "Requesting timestamps…",
    "web.detail.timestamp_hint": "Sends only the manifest's SHA-256 to a time stamp authority and to OpenTimestamps calendars.",
    "report.field.rfc3161": "RFC 3161 timestamp",
    "report.field.ots": "OpenTimestamps",
    "report.ots.pending": "submitted, pending Bitcoin confirmation",
    "report.ots.confirmed": "confirmed in Bitcoin block {height}",
    "report.verify.rfc3161": "Check the RFC 3161 timestamp against the system's trusted roots:",
    "report.verify.ots": "Upgrade and check the OpenTimestamps proof (after a few hours):",
    "pkg.readme.timestamps": """
WHEN IT EXISTED
---------------
A third party vouched for the moment manifest.json existed, so the capture
time does not rest on the capturing machine's clock alone.
{rfc3161}{ots}""",
    "pkg.readme.rfc3161": """
manifest.json.tsr is an RFC 3161 timestamp ({time}). Check it with OpenSSL
against your system's trusted root certificates:

     openssl ts -verify -data manifest.json -in manifest.json.tsr -CAfile /etc/ssl/cert.pem
""",
    "pkg.readme.ots": """
manifest.json.ots anchors the manifest's hash in the Bitcoin blockchain via
OpenTimestamps. With the official client (pip install opentimestamps-client):

     ots upgrade manifest.json.ots
     ots verify manifest.json.ots -f manifest.json

or drop both files on https://opentimestamps.org.
""",
    # --- Signing ---
    "cli.capture.opt.sign": "Sign the manifest if a signing key exists (webdamga keygen)",
    "cli.field.signed_by": "signed by key",
    "cli.verify.opt.pubkey": "Public key to check the signature against: a .pub file or the base64 key",
    "cli.verify.sig_ok": "signature valid",
    "cli.verify.sig_bad": "SIGNATURE INVALID",
    "cli.verify.sig_unchecked": "signed, but no public key to check it against (use --pubkey)",
    "cli.verify.sig_comment": "trusted comment",
    "cli.keygen.help": "Create the key used to sign capture manifests.",
    "cli.keygen.opt.force": "Replace an existing key (old signatures stay valid against the old public key only)",
    "cli.keygen.force_hint": "Use --force to replace it.",
    "cli.keygen.done": "Signing key created. New captures will be signed automatically.",
    "cli.keygen.key_id": "key id",
    "cli.keygen.public": "public key",
    "cli.keygen.secret_file": "secret key",
    "cli.keygen.share": "Publish the public key somewhere others can find it (your site, a GitHub "
    "profile, the report itself). Anyone can then check a signature with: "
    "minisign -Vm manifest.json -P <public key>",
    "cli.keygen.protect": "The secret key is stored unencrypted so queued and scheduled captures "
    "can sign unattended. Anyone who can read that file can sign as you.",
    "cli.pubkey.help": "Print the public key in minisign format.",
    "cli.pubkey.missing": "No signing key yet. Create one with: webdamga keygen",
    "cli.sign.help": "Sign the manifest of an existing capture.",
    "cli.sign.opt.force": "Replace an existing signature",
    "cli.sign.exists": "This capture is already signed. Use --force to replace the signature.",
    "cli.sign.done": "signed:",
    "web.detail.signed_by": "signed by key",
    "web.detail.unsigned": "not signed",
    "web.detail.sig_ok": "signature valid",
    "web.detail.sig_bad": "SIGNATURE INVALID",
    "web.detail.sig_unchecked": "signed, but no local public key to check it against",
    "report.field.signature": "Signature",
    "report.signature.value": "minisign Ed25519, key {key_id}",
    "report.verify.signature": "Check who sealed it, using the signer's public key:",
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
    "pkg.readme.signature": """
WHO SEALED IT
-------------
manifest.json is signed with an Ed25519 key (id {key_id}). The signature
catches something the checksums alone cannot: someone editing a file and then
regenerating manifest.json to match. Check it with minisign
(https://jedisct1.github.io/minisign/):

     minisign -Vm manifest.json -p signer.pub

signer.pub is included for convenience, but a key shipped inside the package
cannot vouch for itself. Compare it with the public key the sender published
somewhere you already trust.
""",
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
{signature_section}{timestamp_section}
{packaging_files} were created while packaging, so they are not listed in
manifest.json. Every other file is.

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
    "web.index.search": "Ara",
    "web.index.search_placeholder": "URL, başlık ya da id",
    "web.index.clear": "temizle",
    "web.index.no_match": "Aramanla eşleşen yakalama yok.",
    "web.index.prev": "Daha yeni",
    "web.index.next": "Daha eski",
    "web.index.page_of": "sayfa {page} / {total}",
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
    # --- İstihbarat (abuse iletişimi) ---
    "cli.capture.opt.intel": "Registrar, ağ sahibi, ASN ve abuse iletişimini araştır",
    "cli.field.abuse": "abuse iletişimi",
    "cli.intel.help": "Bir alan adı ya da IP'yi kime ihbar edeceğini araştır (registrar, ağ, ASN, abuse).",
    "cli.intel.arg.target": "Bir URL, alan adı ya da IP adresi",
    "cli.intel.registrar": "registrar",
    "cli.intel.registered": "kayıt",
    "cli.intel.network": "ağ",
    "cli.intel.asn": "ASN",
    "cli.intel.no_abuse": "Kayıt verisinde abuse iletişimi bulunamadı.",
    "web.index.intel": "abuse iletişimini araştır",
    "web.detail.intel": "Kime ihbar edilir",
    "web.detail.intel_btn": "Abuse iletişimini araştır",
    "web.detail.intel_looking": "Araştırılıyor…",
    "web.detail.intel_hint": "Registrar, ağ sahibi, ASN ve abuse iletişimi için RDAP ve Team Cymru'ya sorar (sitenin kendisine değil).",
    "web.detail.intel.registrar": "Registrar",
    "web.detail.intel.registered": "Kayıt",
    "web.detail.intel.expires": "Bitiş",
    "web.detail.intel.network": "Ağ sahibi",
    "web.detail.intel.asn": "ASN",
    "web.detail.intel.abuse": "Abuse iletişimi",
    "web.detail.intel.none": "Abuse iletişimi bulunamadı.",
    "report.section.intel": "Kime ihbar edilir",
    "report.field.registrar": "Registrar",
    "report.field.registered": "Alan adı kaydı",
    "report.field.network_owner": "Ağ sahibi",
    "report.field.asn": "ASN",
    "report.field.abuse": "Abuse iletişimi",
    # --- Cihaz / referer / dil ---
    "cli.capture.opt.device": 'Bir cihazı taklit et, ör. "iPhone 15" (bkz. webdamga devices)',
    "cli.capture.opt.referer": "İstekle birlikte bu Referer başlığını gönder",
    "cli.capture.opt.accept_language": "Accept-Language başlığı, ör. tr-TR,tr;q=0.9",
    "cli.field.device": "cihaz",
    "cli.devices.help": "--device ile kullanılabilecek cihaz profillerini listele.",
    "cli.devices.opt.all": "Yalnızca yaygın olanları değil, bilinen tüm cihazları göster",
    "cli.devices.more": "Bu kısa bir liste; --all Playwright'in tanıdığı tüm cihazları gösterir.",
    "web.index.device": "cihaz",
    "web.index.device.desktop": "masaüstü (varsayılan)",
    "web.index.referer": "Referer",
    "web.index.accept_language": "Accept-Language",
    "web.detail.device": "taklit edilen cihaz",
    "report.field.device": "Taklit edilen cihaz",
    # --- İzleme ---
    "web.nav.captures": "Yakalamalar",
    "web.nav.monitors": "İzleme",
    "web.monitors.title": "İzlenenler",
    "web.monitors.monitor": "İzleyici",
    "web.monitors.new": "Bir URL'yi izle",
    "web.monitors.intro": "URL belirli aralıklarla yakalanır ve her yakalama son başarılı yakalamayla "
    "karşılaştırılır; böylece bir sayfanın ne zaman zararlıya dönüştüğünü, taşındığını ya da kapandığını görürsün.",
    "web.monitors.label": "etiket (isteğe bağlı)",
    "web.monitors.every": "sıklık",
    "web.monitors.interval.15": "15 dakika",
    "web.monitors.interval.30": "30 dakika",
    "web.monitors.interval.60": "saatte bir",
    "web.monitors.interval.180": "3 saat",
    "web.monitors.interval.360": "6 saat",
    "web.monitors.interval.720": "12 saat",
    "web.monitors.interval.1440": "günde bir",
    "web.monitors.minutes.one": "{count} dakika",
    "web.monitors.minutes.other": "{count} dakika",
    "web.monitors.add": "İzlemeye başla",
    "web.monitors.last_change": "son değişiklik",
    "web.monitors.no_change": "henüz yok",
    "web.monitors.next_run": "sonraki tur (UTC)",
    "web.monitors.last_run": "son tur (UTC)",
    "web.monitors.paused": "duraklatıldı",
    "web.monitors.active": "etkin",
    "web.monitors.state": "durum",
    "web.monitors.baseline": "karşılaştırma tabanı",
    "web.monitors.run_now": "Şimdi çalıştır",
    "web.monitors.pause": "Duraklat",
    "web.monitors.resume": "Devam ettir",
    "web.monitors.delete": "Sil",
    "web.monitors.delete_confirm": "Bu URL'nin izlenmesi durdurulsun mu? Yakalamaları silinmez.",
    "web.monitors.delete_hint": "İzleyiciyi silmek sonraki turları durdurur; ürettiği yakalamalar delil olarak kalır.",
    "web.monitors.empty": "Henüz izlenen bir şey yok.",
    "web.monitors.runs": "Turlar",
    "web.monitors.change": "değişiklik",
    "web.monitors.first_run": "ilk yakalama, karşılaştırılacak bir şey yok",
    "web.monitors.no_runs": "Henüz tur yok; ilki bir dakika içinde başlar.",
    "cli.monitor.help": "URL'leri zamanlanmış olarak izle ve değişiklikleri işaretle.",
    "cli.monitor.add.help": "Bir URL'yi izlemeye başla.",
    "cli.monitor.opt.every": "Yakalamalar arası dakika (en az 5)",
    "cli.monitor.opt.label": "Tanımak için bir ad",
    "cli.monitor.added": "#{id} izleniyor: {url}, her {minutes} dakikada. webdamga serve ya da webdamga monitor run açıkken çalışır.",
    "cli.monitor.list.help": "İzleyicileri listele.",
    "cli.monitor.empty": "İzlenen bir şey yok.",
    "cli.monitor.pause.help": "Bir izleyiciyi duraklat.",
    "cli.monitor.resume.help": "Duraklatılmış bir izleyiciyi devam ettir.",
    "cli.monitor.remove.help": "Bir izleyiciyi sil (yakalamaları kalır).",
    "cli.monitor.arg.id": "İzleyici id'si",
    "cli.monitor.not_found": "{id} id'li izleyici yok.",
    "cli.monitor.done": "tamam",
    "cli.monitor.run.help": "Zamanlayıcıyı ve yakalama kuyruğunu web arayüzü olmadan ön planda çalıştır.",
    "cli.monitor.running": "Zamanlayıcı {count} izleyiciyle çalışıyor. Durdurmak için Ctrl+C.",
    "cli.col.every": "sıklık",
    "cli.col.last_change": "son değişiklik",
    "cli.col.next_run": "sonraki tur",
    # --- Karşılaştırma ---
    "diff.verdict.identical": "Değişiklik yok",
    "diff.verdict.minor": "Küçük değişiklikler",
    "diff.verdict.major": "Önemli değişiklikler",
    "diff.reason.final_host": "Sayfa artık başka bir sunucuda son buluyor: {a} → {b}",
    "diff.reason.final_url": "Nihai URL değişti: {a} → {b}",
    "diff.reason.http_status": "HTTP durumu değişti: {a} → {b}",
    "diff.reason.page_title": "Sayfa başlığı değişti: {a} → {b}",
    "diff.reason.server_ip": "Sunucu IP'si değişti: {a} → {b}",
    "diff.reason.tls_certificate": "TLS sertifikası değişti (yayıncı {a} → {b})",
    "diff.reason.visual.major": "Ekran görüntüsünün %{percent}'i değişti",
    "diff.reason.visual.minor": "Ekran görüntüsünün %{percent}'i değişti",
    "diff.reason.text.major": "Görünür metin yalnızca %{percent} benzer",
    "diff.reason.text.minor": "Görünür metin: {added} satır eklendi, {removed} silindi",
    "diff.reason.password_field_added": "Bir parola alanı belirdi",
    "diff.reason.password_field_removed": "Parola alanı kalktı",
    "diff.reason.form_target_host": "Bir form artık başka bir sunucuya gönderiyor: {hosts}",
    "diff.reason.forms_changed": "Formlar değişti: {added} eklendi, {removed} kaldırıldı",
    "diff.reason.hosts": "Bağlanılan sunucular: {added} yeni, {removed} artık kullanılmıyor",
    "cli.diff.help": "İki yakalamayı karşılaştır: ekran görüntüsü, görünür metin, formlar, sunucular ve metadata.",
    "cli.diff.arg.a": "Eski yakalamanın id'si",
    "cli.diff.arg.b": "Yeni yakalamanın id'si",
    "cli.diff.opt.json": "Sonucun tamamını JSON olarak yazdır",
    "cli.diff.visual": "değişen ekran",
    "cli.diff.text": "metin benzerliği",
    "cli.diff.forms": "formlar",
    "cli.diff.hosts_added": "yeni sunucular",
    "cli.diff.image": "görsel fark",
    "cli.diff.reasons": "neden",
    "web.diff.title": "Karşılaştırma",
    "web.diff.older": "eski",
    "web.diff.newer": "yeni",
    "web.diff.overlay": "Değişiklikler yeni yakalamanın üstünde işaretli",
    "web.diff.reasons": "Neler değişti",
    "web.diff.metadata": "Metadata",
    "web.diff.field": "alan",
    "web.diff.forms": "Formlar",
    "web.diff.forms_added": "eklenen",
    "web.diff.forms_removed": "kaldırılan",
    "web.diff.password": "parola alanı",
    "web.diff.resources": "Sunucular ve scriptler",
    "web.diff.hosts_added": "yeni sunucular",
    "web.diff.hosts_removed": "artık kullanılmayan sunucular",
    "web.diff.scripts_added": "yeni scriptler",
    "web.diff.text": "Görünür metin",
    "web.diff.text_summary": "%{similarity} benzer, {added} satır eklendi, {removed} silindi",
    "web.diff.text_truncated": "Yalnızca ilk değişiklikler gösteriliyor.",
    "web.diff.none": "yok",
    "web.detail.compare": "Karşılaştır",
    "web.detail.compare_btn": "Karşılaştır",
    # --- Zaman damgası ---
    "cli.capture.opt.timestamp": "Güvenilir zaman damgası al (RFC 3161 ve OpenTimestamps); yalnızca manifest özeti gönderilir",
    "cli.ts.help": "Mevcut bir yakalamanın manifestosu için güvenilir zaman damgası al.",
    "cli.ts.opt.rfc3161": "Bir RFC 3161 zaman damgası otoritesine sor",
    "cli.ts.opt.ots": "OpenTimestamps takvimleriyle Bitcoin'e bağla",
    "cli.ts.opt.tsa": "RFC 3161 TSA adresi (varsayılan: WEBDAMGA_TSA_URL ya da DigiCert)",
    "cli.ts.opt.force": "Mevcut zaman damgalarını değiştir (eski tarihli damga genelde daha değerlidir)",
    "cli.ts.exists": "Bu yakalamanın zaten zaman damgası var. Değiştirmek için --force kullan.",
    "cli.ts.requesting": "zaman damgaları isteniyor (TSA: {tsa})…",
    "cli.ts.rfc_ok": "RFC 3161: {time}, {tsa}",
    "cli.ts.rfc_failed": "RFC 3161 başarısız:",
    "cli.ts.ots_ok": "OpenTimestamps: {count} takvime gönderildi, Bitcoin onayı birkaç saat sürer",
    "cli.ts.ots_failed": "OpenTimestamps başarısız:",
    "cli.ts.tsa_sig_ok": "TSA imzası doğrulandı",
    "cli.ts.tsa_sig_bad": "TSA İMZASI DOĞRULANAMADI",
    "cli.ts.tsa_sig_unchecked": "TSA imzası kontrol edilmedi, openssl yok",
    "cli.ts.ots_pending": "Bitcoin onayı bekleniyor",
    "cli.ts.ots_confirmed": "Bitcoin'de onaylandı",
    "web.index.timestamp": "güvenilir zaman damgası",
    "web.detail.timestamp": "güvenilir zaman",
    "web.detail.timestamp.none": "güvenilir zaman damgası yok",
    "web.detail.timestamp.ots_pending": "OpenTimestamps bekliyor",
    "web.detail.timestamp.ots_confirmed": "Bitcoin'de onaylandı",
    "web.detail.timestamp_btn": "Şimdi damgala",
    "web.detail.timestamping": "Zaman damgaları isteniyor…",
    "web.detail.timestamp_hint": "Yalnızca manifestonun SHA-256 özeti bir zaman damgası otoritesine ve OpenTimestamps takvimlerine gönderilir.",
    "report.field.rfc3161": "RFC 3161 zaman damgası",
    "report.field.ots": "OpenTimestamps",
    "report.ots.pending": "gönderildi, Bitcoin onayı bekleniyor",
    "report.ots.confirmed": "{height} numaralı Bitcoin bloğunda onaylandı",
    "report.verify.rfc3161": "RFC 3161 zaman damgasını sistemin güvenilir kök sertifikalarıyla doğrulayın:",
    "report.verify.ots": "OpenTimestamps kanıtını yükseltip doğrulayın (birkaç saat sonra):",
    "pkg.readme.timestamps": """
NE ZAMAN VARDI
--------------
manifest.json'un hangi anda var olduğuna üçüncü bir taraf kefil oldu; yani
yakalama zamanı yalnızca yakalayan makinenin saatine dayanmıyor.
{rfc3161}{ots}""",
    "pkg.readme.rfc3161": """
manifest.json.tsr bir RFC 3161 zaman damgasıdır ({time}). OpenSSL ile
sisteminizin güvenilir kök sertifikalarına karşı doğrulayın:

     openssl ts -verify -data manifest.json -in manifest.json.tsr -CAfile /etc/ssl/cert.pem
""",
    "pkg.readme.ots": """
manifest.json.ots, manifestonun özetini OpenTimestamps aracılığıyla Bitcoin
blok zincirine bağlar. Resmi istemciyle (pip install opentimestamps-client):

     ots upgrade manifest.json.ots
     ots verify manifest.json.ots -f manifest.json

ya da iki dosyayı https://opentimestamps.org sayfasına bırakın.
""",
    # --- İmzalama ---
    "cli.capture.opt.sign": "İmza anahtarı varsa manifestoyu imzala (webdamga keygen)",
    "cli.field.signed_by": "imzalayan anahtar",
    "cli.verify.opt.pubkey": "İmzanın doğrulanacağı public key: .pub dosyası ya da base64 anahtar",
    "cli.verify.sig_ok": "imza geçerli",
    "cli.verify.sig_bad": "İMZA GEÇERSİZ",
    "cli.verify.sig_unchecked": "imzalı ama doğrulanacak public key yok (--pubkey kullan)",
    "cli.verify.sig_comment": "güvenilir yorum",
    "cli.keygen.help": "Yakalama manifestolarını imzalayacak anahtarı oluştur.",
    "cli.keygen.opt.force": "Mevcut anahtarı değiştir (eski imzalar yalnızca eski public key ile doğrulanır)",
    "cli.keygen.force_hint": "Değiştirmek için --force kullan.",
    "cli.keygen.done": "İmza anahtarı oluşturuldu. Yeni yakalamalar otomatik imzalanacak.",
    "cli.keygen.key_id": "anahtar id",
    "cli.keygen.public": "public key",
    "cli.keygen.secret_file": "gizli anahtar",
    "cli.keygen.share": "Public key'i başkalarının bulabileceği bir yerde yayınla (siten, GitHub "
    "profilin, raporun kendisi). Herkes imzayı şöyle doğrulayabilir: "
    "minisign -Vm manifest.json -P <public key>",
    "cli.keygen.protect": "Gizli anahtar, kuyruktaki ve zamanlanmış yakalamalar gözetimsiz "
    "imzalayabilsin diye şifrelenmeden saklanıyor. O dosyayı okuyabilen herkes senin adına imzalayabilir.",
    "cli.pubkey.help": "Public key'i minisign biçiminde yazdır.",
    "cli.pubkey.missing": "Henüz imza anahtarı yok. Oluşturmak için: webdamga keygen",
    "cli.sign.help": "Mevcut bir yakalamanın manifestosunu imzala.",
    "cli.sign.opt.force": "Mevcut imzayı değiştir",
    "cli.sign.exists": "Bu yakalama zaten imzalı. İmzayı değiştirmek için --force kullan.",
    "cli.sign.done": "imzalandı:",
    "web.detail.signed_by": "imzalayan anahtar",
    "web.detail.unsigned": "imzasız",
    "web.detail.sig_ok": "imza geçerli",
    "web.detail.sig_bad": "İMZA GEÇERSİZ",
    "web.detail.sig_unchecked": "imzalı ama doğrulanacak yerel public key yok",
    "report.field.signature": "İmza",
    "report.signature.value": "minisign Ed25519, anahtar {key_id}",
    "report.verify.signature": "Kimin mühürlediğini imzalayanın public key'iyle doğrulayın:",
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
    "pkg.readme.signature": """
KİM MÜHÜRLEDİ
-------------
manifest.json bir Ed25519 anahtarıyla (id {key_id}) imzalıdır. İmza, tek
başına özetlerin yakalayamayacağı bir şeyi yakalar: birinin bir dosyayı
değiştirip manifest.json'u da ona göre yeniden üretmesini. minisign ile
doğrulayın (https://jedisct1.github.io/minisign/):

     minisign -Vm manifest.json -p signer.pub

signer.pub kolaylık olsun diye pakete eklendi, ama paketin içinden gelen bir
anahtar kendi kendine kefil olamaz. Gönderenin önceden güvendiğiniz bir yerde
yayınladığı public key ile karşılaştırın.
""",
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
{signature_section}{timestamp_section}
{packaging_files} paketleme sırasında oluşturulduğu için manifest.json'da
listelenmez. Diğer tüm dosyalar listelidir.

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
