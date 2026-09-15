# Changelog

All notable changes to webdamga are recorded here. Dates are UTC.
This project follows [Keep a Changelog](https://keepachangelog.com/) loosely
and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- Only `http` and `https` URLs are captured; `file://`, `chrome://`,
  `javascript:` and `data:` are refused before a browser is opened.
- The web interface now checks the `Host` header (against loopback and
  `WEBDAMGA_ALLOWED_HOSTS`) and the `Origin`/`Referer` of state-changing
  requests, closing DNS-rebinding and CSRF holes.
- Captured artefacts (`dom.html`, `page.mhtml`, `.svg`) are served as
  downloads with a sandbox CSP and `nosniff`, so a captured page's own
  JavaScript can no longer run in the interface's origin.

### Added

- Background capture queue with job status, so the interface no longer blocks
  during a capture and survives restarts.
- Capturing through a proxy or Tor, with named profiles (`data/proxies.json`)
  and optional egress-IP recording.
- Replayable WARC/1.1 output (`archive.warc.gz`) with original response bytes.
- Manifest signing (minisign-compatible Ed25519) and `verify` signature checks.
- Trusted timestamps: RFC 3161 (default DigiCert) and OpenTimestamps (Bitcoin).
- Comparing two captures (visual, text, forms, servers, metadata) with a verdict.
- Scheduled monitoring of a URL, comparing each run to the last successful one.
- Device, `Referer` and `Accept-Language` emulation for cloaked pages.
- Reporting intel: registrar, network owner, ASN and abuse contacts (RDAP + Cymru).
- Change notifications by webhook (JSON/Slack/Discord) and email.
- Search and pagination over captures.
- Retention: `webdamga prune` deletes old captures while keeping signed ones
  and monitor baselines; `webdamga upgrade-timestamps` completes pending OTS.
- PDF evidence report and a sendable `.zip` evidence package.
- English and Turkish throughout the CLI and web interface.
- A Dockerfile with Chromium bundled, and GitHub Actions CI across Python
  3.11–3.13.

### Fixed

- `response.html` and the WARC now keep the server's original bytes on non-UTF-8
  pages; both Playwright's `body()` and the HAR re-encode text to UTF-8.
- The unchecked "full page" checkbox is now respected instead of always on.
- The capture detail page and PDF report no longer break when a capture never
  reached a browser.

Note: the project is pre-1.0; capture folders and the JSON API may still change.
