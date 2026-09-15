# webdamga

**A local web evidence and archiving tool.** ("damga" is Turkish for
"stamp".) It captures a URL exactly as it looked at a given moment and turns
that into evidence you can hand to someone else: screenshots, the page's
original bytes, a replayable WARC archive and network traffic, sealed with a
SHA-256 manifest, optionally signed and anchored to a trusted time. It can also
watch a URL over time and tell you when the page changes. Same idea as
urlscan.io / archive.today, but everything runs on your own machine.

Typical use: recording a phishing page exactly as it appeared before you
report it (to the registrar, the host, a CERT, a bank), in a form the
recipient can verify without trusting you or installing anything.

*[Türkçe README için buraya bakabilirsin](README.tr.md).*

---

## Screenshots

| Start a capture / history | Evidence + SHA-256 verification |
| --- | --- |
| ![Home page: new capture form and capture history](docs/screenshots/index.png) | ![Capture detail: summary, screenshot, file list, and integrity check result](docs/screenshots/capture-detail.png) |

---

## What a capture produces

Every capture writes a folder under `data/captures/<id>/`:

| File | Contents |
| --- | --- |
| `screenshot.png` | Full page screenshot |
| `screenshot-viewport.png` | What was visible without scrolling |
| `response.html` | The main document **exactly as the server sent it**, before JavaScript |
| `dom.html` | The **rendered DOM**, after JavaScript has run |
| `archive.warc.gz` | WARC/1.1 archive with original response bytes, replays in ReplayWeb.page or pywb |
| `page.mhtml` | Single-file, self-contained archive (opens in Chrome) |
| `page.pdf` | The page printed to PDF |
| `network.har` | Every request and response, with bodies |
| `console.log` | Browser console output and page errors |
| `metadata.json` | Requested/final URL, redirect chain, HTTP status and headers, server IP, TLS certificate, network route and egress IP, page title, favicon, UTC timestamps, User-Agent, timing, resource summary, capturing machine, signing key id |
| `manifest.json` | **SHA-256 of every file above** |
| `manifest.sha256` | Checksum of `manifest.json` itself |
| `manifest.json.minisig` | Ed25519 signature over the manifest, if you created a signing key |
| `manifest.json.tsr` | RFC 3161 timestamp, if requested |
| `manifest.json.ots` | OpenTimestamps (Bitcoin) proof, if requested |

`webdamga verify <id>` recomputes every checksum and checks the signature and
timestamps.

**About original bytes.** Playwright's `response.body()` and the HAR it writes
both decode text resources with the page's charset and re-encode them as UTF-8.
On a page that is not UTF-8 (windows-1254, for example) that silently changes
the bytes. webdamga reads bodies through Chrome's DevTools `Fetch` domain
instead, so `response.html` and the WARC keep the bytes the server actually
sent. `network.har` is Playwright's own output and keeps its limitation.

---

## Installation

Requires Python **3.11+**.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

> `playwright install chromium` downloads Chromium (~150 MB) once.

### Docker

A prebuilt image bundles Chromium, so there is nothing else to install:

```bash
docker build -t webdamga .
docker run -p 8000:8000 -v webdamga-data:/data webdamga
```

Captures, the database and signing keys live in the `/data` volume. Set
configuration with `-e`, for example `-e WEBDAMGA_WEBHOOK_URL=...`. If you
expose the container beyond localhost, read the security note below.

---

## Usage

### Capturing

```bash
webdamga capture https://example.com/login
webdamga capture https://example.com --wait-until networkidle --wait 3 --width 1440
webdamga list
webdamga verify 20260910T142530Z-example-com-ab12cd
webdamga prune --older-than 30 --dry-run   # tidy up old captures
```

### Web interface

```bash
webdamga serve            # http://127.0.0.1:8000
```

Captures run in a background queue, so the page stays usable while they finish
and survives restarts. The interface covers capturing, browsing, verifying,
comparing, exporting and monitoring. `WEBDAMGA_CONCURRENCY` sets how many
captures run at once (default 1).

The capture list is searchable (URL, title or id) and paginated.

### Sending a capture as evidence

```bash
webdamga export 20260910T142530Z-example-com-ab12cd
```

produces one `.zip` you can attach to an abuse report:

```
webdamga-<id>.zip
└── <id>/
    ├── README.txt            what this is, and how to verify it without webdamga
    ├── evidence-report.pdf   readable summary: URLs, TLS, screenshot, checksums
    ├── signer.pub            the signing public key, if the capture is signed
    └── …                     every artefact from the capture, plus the manifest
```

The command prints the package's own SHA-256; keep it with your report. The
recipient does not need this tool: `README.txt` walks them through `shasum`,
`minisign`, `openssl ts` and `ots` commands for whatever the package contains.
In the web interface this is the **Send as evidence** section of a capture.

---

## Signing: who sealed it

The manifest proves a folder was not modified, but not who produced it:
someone could edit a file and regenerate the manifest to match. A signature
closes that gap.

```bash
webdamga keygen           # once; new captures are signed automatically
webdamga pubkey           # print the public key to publish
webdamga sign <id>        # sign an older capture
```

Signatures are **minisign compatible** (Ed25519, BLAKE2b prehashed), so anyone
can check them with the standard tool:

```bash
minisign -Vm manifest.json -P RWS...your-public-key...
```

The trusted comment inside the signature carries the capture id and signing
time and cannot be altered without breaking it. The secret key is stored
unencrypted (mode 0600) in `~/.config/webdamga/keys` so queued and scheduled
captures can sign unattended; set `WEBDAMGA_KEY_DIR` to keep it elsewhere.
Publish your public key somewhere recipients already trust; a key shipped
inside the package cannot vouch for itself.

---

## Trusted timestamps: when it existed

A signature says who sealed a capture, but the time comes from your own clock.
A trusted timestamp ties it to a third party. Only the manifest's SHA-256 is
sent out, never the URL or content, which is why it is opt in:

```bash
webdamga capture https://example.com --timestamp
webdamga timestamp <id>   # add to an existing capture
```

Two independent methods are used together:

- **RFC 3161**: a time stamp authority signs the hash and the current time.
  The default is DigiCert's public TSA, whose tokens verify against the
  operating system's standard root certificates:
  `openssl ts -verify -data manifest.json -in manifest.json.tsr -CAfile /etc/ssl/cert.pem`.
  Override with `WEBDAMGA_TSA_URL` or `--tsa`.
- **OpenTimestamps**: the hash is submitted to several calendar servers and
  anchored in the Bitcoin blockchain. No single organisation to trust, but
  confirmation takes a few hours; upgrade and check the proof later with the
  official client (`ots upgrade`, `ots verify`).

`webdamga verify` checks both against the current manifest and, when `openssl`
is available, verifies the TSA's signature and certificate chain. If it cannot,
it says so rather than implying success.

---

## Capturing through a proxy or Tor

Phishing pages often show different content depending on the visitor's IP or
country. A capture can go through a proxy:

```bash
webdamga capture https://example.com --tor
webdamga capture https://example.com --proxy socks5://127.0.0.1:1080
webdamga capture https://example.com --via de --record-egress
webdamga proxies
```

Named profiles live in `data/proxies.json`:

```json
{ "de": "socks5://10.0.0.2:1080", "us": "http://user:pass@proxy.example:3128" }
```

Choosing a country means choosing a profile; the exit country is whatever your
proxy provides, webdamga does not supply one. A `tor` profile always exists.
`--record-egress` records the IP the capture actually left from (via
check.torproject.org, in a separate context so it does not end up in the
evidence). Proxy credentials are never written to metadata, reports or logs.
Chromium does not support authenticated SOCKS proxies, so those are refused
rather than silently used without credentials. The web interface only offers
named profiles, never free-form proxy addresses.

---


## Emulating a device

Smishing pages often serve content only to a phone. Capture as one:

```bash
webdamga capture https://example.com --device "iPhone 15"
webdamga capture https://example.com --referer https://t.co/abc --accept-language tr-TR,tr
webdamga devices          # list device profiles
```

`--device` sets the User-Agent, viewport, scale and touch to match a real
device; `--referer` and `--accept-language` help with pages that only reveal
themselves to a particular source or language. The web form offers the same.

---

## Who to report to

```bash
webdamga capture https://example.com --intel   # collect during the capture
webdamga intel example.com                      # or look up on its own
```

Collects the registrar and registration dates, the network owner, the origin
ASN and the **abuse contact emails**, over RDAP and Team Cymru (no extra
dependencies, queries go to the registries, not the target). With `--intel` the
result is sealed into the manifest as `intel.json`; on a capture's page the
**Who to report to** section fetches it on demand. It also lands in the PDF
report so the evidence package tells the recipient where to send it.

---

## Comparing two captures

```bash
webdamga diff <older-id> <newer-id>
webdamga diff <older-id> <newer-id> --json
```

The comparison works in layers and ends with a verdict (no changes, minor,
significant) and plain-language reasons:

- **screenshot**: share of changed pixels, changed regions, and a highlighted
  diff image
- **visible text**: line-level diff and similarity
- **forms**: the strongest phishing signals are flagged on their own, such as
  a password field appearing, or a form that now submits to a different site
- **servers and scripts** contacted, from the HAR
- **metadata**: final URL (moving to another host is significant), HTTP
  status, title, server IP, TLS certificate

In the web interface, a capture's page lists other captures of the same host
to compare against. Results go to `data/diffs/`; sealed capture folders are
never touched.

---

## Watching a URL over time

```bash
webdamga monitor add https://example.com/login --every 60 --label "Bank lookalike"
webdamga monitor list
webdamga monitor pause 1
webdamga monitor run      # scheduler without the web interface
```

Each run is a normal capture (with the monitor's route and timestamp settings)
compared to the last successful one. A failed run, for instance because the
domain no longer resolves, is recorded but does not replace the baseline, so
the next successful capture is still compared against the last good one. The
scheduler runs inside `webdamga serve`, or on its own with `webdamga monitor run`.
The **Monitors** page shows each monitor's runs with change badges linking to
the comparison. Deleting a monitor keeps its captures.

When a change is found, webdamga can notify you by webhook (JSON, or Slack /
Discord format) or email. Set `WEBDAMGA_WEBHOOK_URL` or the `WEBDAMGA_SMTP_*`
variables, choose the threshold with `WEBDAMGA_NOTIFY_LEVEL` (`minor`/`major`,
default `major`), and test it with `webdamga monitor notify-test`.

---

## Language

The CLI and web interface speak **English and Turkish**. English is the
default; Turkish is picked up when your environment or browser asks for it.

| Surface | How the language is chosen (first match wins) |
| --- | --- |
| CLI | `--lang` → `WEBDAMGA_LANG` → system locale (`LC_ALL` / `LANG`) → English |
| Web | `?lang=` → `webdamga_lang` cookie → `Accept-Language` → English |

---


## Security

The interface is meant for `localhost`. It refuses to capture anything but
`http`/`https` (no `file://`, `chrome://`, `javascript:`), serves captured
pages as sandboxed downloads so their scripts cannot reach the API, and rejects
cross-origin state-changing requests and unexpected `Host` headers (CSRF and
DNS-rebinding). To reach it from another machine, put it behind a reverse proxy
with TLS and set `WEBDAMGA_ALLOWED_HOSTS` to the hostname you use; there is no
built-in authentication yet, so restrict access at the proxy.


## JSON API

| Endpoint | Description |
| --- | --- |
| `GET /api/captures`, `GET /api/captures/{id}` | Capture index, one capture's metadata |
| `POST /api/jobs`, `GET /api/jobs`, `GET/DELETE /api/jobs/{id}` | Queue a capture, list, inspect, cancel |
| `GET /captures/{id}/verify` | Integrity, signature and timestamp check |
| `POST /captures/{id}/timestamp` | Timestamp an existing capture |
| `GET /captures/{id}/export.zip` | Evidence package; its SHA-256 is in `x-webdamga-package-sha256` |
| `GET /captures/{id}/report.pdf` | PDF evidence report |
| `GET /captures/{id}/files/{name}` | One artefact (manifest-listed names only) |
| `GET /api/diff?a=&b=` | Compare two captures |
| `GET/POST /api/monitors`, `GET/PATCH/DELETE /api/monitors/{id}`, `POST /api/monitors/{id}/run` | Monitors |
| `POST /captures/{id}/intel` | Look up abuse contacts for a capture |
| `GET /api/routes`, `GET /api/devices` | Proxy profiles, device profiles |

---

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `WEBDAMGA_DATA_DIR` | `./data` | Captures, diffs, database, `proxies.json` |
| `WEBDAMGA_LANG` | system locale | Interface language |
| `WEBDAMGA_CONCURRENCY` | `1` | Captures running at once |
| `WEBDAMGA_KEY_DIR` | `~/.config/webdamga/keys` | Signing key location |
| `WEBDAMGA_TSA_URL` | DigiCert | RFC 3161 time stamp authority |
| `WEBDAMGA_TSA_CA` | system bundle | CA file for checking TSA tokens |
| `WEBDAMGA_OTS_CALENDARS` | public pools | Comma-separated OpenTimestamps calendars |
| `WEBDAMGA_ALLOWED_HOSTS` | loopback | Extra `Host` values the interface accepts |
| `WEBDAMGA_WEBHOOK_URL` / `_FORMAT` | none | Change-notification webhook |
| `WEBDAMGA_SMTP_*`, `WEBDAMGA_NOTIFY_LEVEL` | none | Email notifications and threshold |
| `WEBDAMGA_BASE_URL` | none | Absolute links in notifications |

---

## Tests

```bash
pip install -e ".[dev]"
pytest
WEBDAMGA_INTEGRATION=1 pytest   # also runs tests needing Chromium and network access
```

Formats are checked against independent implementations rather than only
against webdamga itself: WARC files through warcio's digest checker, signatures
against real minisign output, timestamp tokens against real DigiCert and FreeTSA
responses, and OpenTimestamps proofs against the official client.

---

## Roadmap

Done:

- [x] Background queue with capture status
- [x] Capturing through a proxy or Tor, with named profiles
- [x] WARC output with original bytes (Wayback / pywb / ReplayWeb.page)
- [x] Manifest signing (minisign compatible)
- [x] RFC 3161 and OpenTimestamps trusted timestamps
- [x] Comparing two captures (visual, text, forms, servers, metadata)
- [x] Monitoring a URL on a schedule
- [x] PDF evidence report and a sendable `.zip` package
- [x] Device / Referer / Accept-Language emulation for cloaked pages
- [x] Registrar, network owner, ASN and abuse contacts
- [x] Change notifications (webhook, email)
- [x] Search, pagination, retention and CSRF/host hardening

Next:

- [ ] WACZ packaging for one-file replay
- [ ] Built-in authentication for running beyond localhost
- [ ] Capturing with Firefox and WebKit as well as Chromium

---

## Legal / ethical note

`webdamga` is meant for **authorized, lawful** use only: monitoring your own
assets, reporting phishing or brand abuse, incident response, academic
research. Complying with applicable law and the target site's terms of
service, when accessing sites you capture and when storing or sharing the
data you collect, is the user's responsibility.

## License

MIT, see [LICENSE](LICENSE).
