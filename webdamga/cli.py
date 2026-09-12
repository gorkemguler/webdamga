"""webdamga komut satırı arayüzü.

Yardım metinleri süreç başlarken tespit edilen dile göre kurulur
(`WEBDAMGA_LANG` ya da sistem locale). Çalışma zamanı çıktılarının dili
ayrıca `webdamga --lang tr ...` ile değiştirilebilir.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .capture import capture as run_capture
from .capture import normalize_url
from .config import CaptureSettings, default_data_dir
from .hashing import verify_capture
from .i18n import SUPPORTED_LANGS, detect_lang, normalize_lang, t, tn
from .network import TOR_PROFILE, ProxyError, load_profiles, redact_proxy
from .report import default_package_name, export_package
from .seal import SIGNATURE_NAME, trusted_comment
from .signing import (
    SigningError,
    default_key_dir,
    generate_keypair,
    load_public_key,
    load_secret_key,
    sign_file,
)
from .storage import JOB_ACTIVE, Store
from .timestamp import timestamp_capture, tsa_url
from .warc import WARC_NAME, exchanges_from_har, write_warc

# Yardım metinleri decorator zamanında kurulduğu için ortamdan gelen dile bağlı.
_HELP_LANG = detect_lang()
_runtime_lang = _HELP_LANG


def _h(key: str) -> str:
    return t(key, _HELP_LANG)


def _lang() -> str:
    return _runtime_lang


app = typer.Typer(add_completion=False, help=_h("cli.app.help"))
console = Console()

_DataDir = typer.Option(None, "--data-dir", "-d", help=_h("cli.opt.data_dir"))
_ExportOutput = typer.Option(None, "--output", "-o", help=_h("cli.export.opt.output"))
_PubKey = typer.Option(None, "--pubkey", "-P", help=_h("cli.verify.opt.pubkey"))
_TsaUrl = typer.Option(None, "--tsa", help=_h("cli.ts.opt.tsa"))
_WarcOutput = typer.Option(None, "--output", "-o", help=_h("cli.warc.opt.output"))


def _resolve_data_dir(value: Path | None) -> Path:
    return Path(value) if value else default_data_dir()


@app.callback()
def _root(
    lang: str | None = typer.Option(None, "--lang", "-L", help=_h("cli.opt.lang")),
) -> None:
    """webdamga."""
    global _runtime_lang
    if lang:
        resolved = normalize_lang(lang)
        if not resolved:
            console.print(f"[red]?[/] --lang: {lang} ({', '.join(SUPPORTED_LANGS)})")
            raise typer.Exit(2)
        _runtime_lang = resolved


@app.command(help=_h("cli.capture.help"))
def capture(
    url: str = typer.Argument(..., help=_h("cli.capture.arg.url")),
    data_dir: Path | None = _DataDir,
    full_page: bool = typer.Option(True, "--full-page/--no-full-page", help=_h("cli.capture.opt.full_page")),
    timeout: int = typer.Option(30, "--timeout", "-t", help=_h("cli.capture.opt.timeout")),
    wait_until: str = typer.Option("load", "--wait-until", help=_h("cli.capture.opt.wait_until")),
    wait: float = typer.Option(1.5, "--wait", help=_h("cli.capture.opt.wait")),
    width: int = typer.Option(1280, "--width", help=_h("cli.capture.opt.width")),
    height: int = typer.Option(800, "--height", help=_h("cli.capture.opt.height")),
    user_agent: str | None = typer.Option(None, "--user-agent", "-A", help=_h("cli.capture.opt.user_agent")),
    headful: bool = typer.Option(False, "--headful", help=_h("cli.capture.opt.headful")),
    proxy: str | None = typer.Option(None, "--proxy", help=_h("cli.capture.opt.proxy")),
    tor: bool = typer.Option(False, "--tor", help=_h("cli.capture.opt.tor")),
    via: str | None = typer.Option(None, "--via", help=_h("cli.capture.opt.via")),
    record_egress: bool = typer.Option(False, "--record-egress", help=_h("cli.capture.opt.record_egress")),
    warc: bool = typer.Option(True, "--warc/--no-warc", help=_h("cli.capture.opt.warc")),
    sign: bool = typer.Option(True, "--sign/--no-sign", help=_h("cli.capture.opt.sign")),
    timestamp: bool = typer.Option(False, "--timestamp", help=_h("cli.capture.opt.timestamp")),
) -> None:
    """Capture a URL and seal the evidence folder."""
    lang = _lang()
    ddir = _resolve_data_dir(data_dir)
    if sum(bool(x) for x in (proxy, tor, via)) > 1:
        console.print(f"[red]{t('cli.capture.route_conflict', lang)}[/]")
        raise typer.Exit(2)
    settings = CaptureSettings(
        wait_until=wait_until,
        timeout_ms=int(timeout * 1000),
        extra_wait_ms=int(wait * 1000),
        full_page=full_page,
        viewport_width=width,
        viewport_height=height,
        headless=not headful,
        pdf=not headful,
        proxy=proxy,
        proxy_profile=TOR_PROFILE if tor else via,
        record_egress=record_egress,
        warc=warc,
        sign=sign,
        timestamp=timestamp,
    )
    if user_agent:
        settings.user_agent = user_agent

    store = Store(ddir)
    console.print(f"[bold]webdamga[/] {t('cli.capture.capturing', lang)} → [cyan]{normalize_url(url)}[/]")
    meta = asyncio.run(run_capture(url, ddir, settings))
    store.record(
        meta,
        manifest_sha256=meta.get("manifest_sha256"),
        ok=bool(meta.get("ok")),
        error=meta.get("error"),
    )

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column(overflow="fold")
    table.add_row(t("cli.field.id", lang), meta["capture_id"])
    table.add_row(t("cli.field.final_url", lang), str(meta.get("final_url")))
    table.add_row(
        t("cli.field.http", lang),
        f"{meta.get('http_status')} {meta.get('http_status_text', '')}".strip(),
    )
    table.add_row(t("cli.field.title", lang), str(meta.get("page_title")))
    addr = meta.get("remote_address") or {}
    if addr:
        table.add_row(t("cli.field.server_ip", lang), f"{addr.get('ipAddress')}:{addr.get('port')}")
    tls = meta.get("tls") or {}
    if tls:
        table.add_row(t("cli.field.tls", lang), f"{tls.get('protocol')} · {tls.get('issuer')}")
    rs = meta.get("resource_summary") or {}
    if rs:
        table.add_row(
            t("cli.field.resources", lang),
            tn(
                "cli.resources.value",
                rs.get("request_count", 0),
                lang,
                kb=f"{rs.get('transfer_bytes', 0) / 1024:.1f}",
            ),
        )
    network = meta.get("network") or {}
    if network.get("mode") not in (None, "direct"):
        route = network.get("proxy") or "-"
        if network.get("profile"):
            route = f"{network['profile']} ({route})"
        table.add_row(t("cli.field.route", lang), route)
    egress = network.get("egress") or {}
    if egress.get("ip"):
        tor_note = f" · {t('cli.field.via_tor', lang)}" if egress.get("is_tor") else ""
        table.add_row(t("cli.field.egress", lang), f"{egress['ip']}{tor_note}")
    table.add_row(t("cli.field.folder", lang), meta["dir"])
    table.add_row(t("cli.field.manifest", lang), meta.get("manifest_sha256", "-"))
    signing = meta.get("signing") or {}
    if meta.get("signature_file"):
        table.add_row(t("cli.field.signed_by", lang), signing.get("key_id", "-"))
    elif signing.get("error"):
        table.add_row(t("cli.field.signed_by", lang), f"[red]{signing['error']}[/]")
    console.print(table)
    if meta.get("timestamps"):
        _print_timestamp_result(meta["timestamps"], lang)
    if meta.get("error"):
        console.print(f"[yellow]{t('cli.warning', lang)}[/] {meta['error']}")


def _print_timestamp_result(result: dict, lang: str) -> None:
    rfc = result.get("rfc3161")
    if rfc:
        if rfc.get("ok"):
            console.print(f"[green]{t('cli.ts.rfc_ok', lang, time=rfc['gen_time'], tsa=rfc['tsa'])}[/]")
        else:
            console.print(f"[yellow]{t('cli.ts.rfc_failed', lang)}[/] {rfc.get('error')}")
    ots = result.get("opentimestamps")
    if ots:
        if ots.get("ok"):
            console.print(f"[green]{t('cli.ts.ots_ok', lang, count=ots['calendars'])}[/]")
        else:
            console.print(f"[yellow]{t('cli.ts.ots_failed', lang)}[/] {ots.get('error')}")


@app.command("list", help=_h("cli.list.help"))
def list_captures(
    data_dir: Path | None = _DataDir,
    limit: int = typer.Option(20, "--limit", "-n", help=_h("cli.list.opt.limit")),
) -> None:
    """List recent captures."""
    lang = _lang()
    store = Store(_resolve_data_dir(data_dir))
    rows = store.list(limit)
    if not rows:
        console.print(f"[dim]{t('cli.list.empty', lang)}[/]")
        raise typer.Exit()
    table = Table()
    table.add_column(t("cli.col.id", lang), style="cyan", no_wrap=True)
    table.add_column(t("cli.col.url", lang), overflow="fold")
    table.add_column(t("cli.col.http", lang), justify="right")
    table.add_column(t("cli.col.date_utc", lang), no_wrap=True)
    for row in rows:
        mark = "" if row["ok"] else " [red]✗[/]"
        table.add_row(
            row["id"] + mark,
            row["final_url"] or row["requested_url"],
            str(row["http_status"] or "-"),
            row["created_utc"],
        )
    console.print(table)


@app.command(help=_h("cli.verify.help"))
def verify(
    capture_id: str = typer.Argument(..., help=_h("cli.verify.arg.id")),
    data_dir: Path | None = _DataDir,
    pubkey: str | None = _PubKey,
) -> None:
    """Verify a capture folder against its manifest."""
    lang = _lang()
    cap_dir = _resolve_data_dir(data_dir) / "captures" / capture_id
    if not cap_dir.is_dir():
        console.print(f"[red]{t('cli.verify.not_found', lang)}[/] {cap_dir}")
        raise typer.Exit(1)

    try:
        key = load_public_key(pubkey) if pubkey else None
    except SigningError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    result = verify_capture(cap_dir, key)
    table = Table(title=f"{t('cli.verify.title', lang)} · {capture_id}")
    table.add_column(t("cli.col.file", lang), style="cyan")
    table.add_column(t("cli.col.status", lang))
    palette = {"ok": "green", "modified": "red", "missing": "red", "unlisted": "yellow"}
    for item in result["files"]:
        status = item["status"]
        color = palette.get(status, "white")
        table.add_row(item["name"], f"[{color}]{t(f'web.status.{status}', lang)}[/]")
    signature = result.get("signature") or {}
    if signature.get("present"):
        if signature.get("ok") is True:
            status = f"[green]{t('cli.verify.sig_ok', lang)}[/]"
        elif signature.get("ok") is False:
            status = f"[red]{t('cli.verify.sig_bad', lang)}[/] ({signature.get('error')})"
        else:
            status = f"[yellow]{t('cli.verify.sig_unchecked', lang)}[/]"
        table.add_row(SIGNATURE_NAME, status)
    timestamps = result.get("timestamps") or {}
    rfc = timestamps.get("rfc3161") or {}
    if rfc.get("present"):
        if rfc.get("ok"):
            tsa_sig = (rfc.get("tsa_signature") or {}).get("verified")
            note = {True: t("cli.ts.tsa_sig_ok", lang), False: t("cli.ts.tsa_sig_bad", lang)}.get(
                tsa_sig, t("cli.ts.tsa_sig_unchecked", lang)
            )
            table.add_row("manifest.json.tsr", f"[green]{rfc['gen_time']}[/] ({note})")
        else:
            table.add_row("manifest.json.tsr", f"[red]{rfc.get('error')}[/]")
    ots = timestamps.get("opentimestamps") or {}
    if ots.get("present"):
        if ots.get("ok"):
            label = (
                t("cli.ts.ots_confirmed", lang)
                if ots.get("state") == "confirmed"
                else t("cli.ts.ots_pending", lang)
            )
            table.add_row("manifest.json.ots", f"[green]{label}[/]")
        else:
            table.add_row("manifest.json.ots", f"[red]{ots.get('error')}[/]")
    console.print(table)
    if signature.get("trusted_comment"):
        console.print(f"[dim]{t('cli.verify.sig_comment', lang)}: {signature['trusted_comment']}[/]")
    if result["ok"]:
        console.print(f"\n[green]{t('cli.verify.intact', lang)}[/]")
        raise typer.Exit(0)
    console.print(f"\n[red]{t('cli.verify.broken', lang)}[/]")
    raise typer.Exit(2)


@app.command(help=_h("cli.export.help"))
def export(
    capture_id: str = typer.Argument(..., help=_h("cli.export.arg.id")),
    data_dir: Path | None = _DataDir,
    output: Path | None = _ExportOutput,
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help=_h("cli.export.opt.pdf")),
) -> None:
    """Export a capture as a single sendable evidence package."""
    lang = _lang()
    cap_dir = _resolve_data_dir(data_dir) / "captures" / capture_id
    if not cap_dir.is_dir():
        console.print(f"[red]{t('cli.verify.not_found', lang)}[/] {cap_dir}")
        raise typer.Exit(1)

    meta = json.loads((cap_dir / "metadata.json").read_text(encoding="utf-8"))
    manifest_path = cap_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    target = Path(output) if output else Path.cwd() / default_package_name(capture_id)

    if pdf:
        console.print(f"[dim]{t('cli.export.building_pdf', lang)}[/]")
    package, digest = asyncio.run(export_package(cap_dir, meta, manifest, target, lang, pdf))

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column(overflow="fold")
    table.add_row(t("cli.export.written", lang), str(package))
    table.add_row(t("cli.export.size", lang), f"{package.stat().st_size / 1024:.1f} KB")
    table.add_row(t("cli.export.sha", lang), digest)
    sidecar = cap_dir / "manifest.sha256"
    if sidecar.is_file():
        table.add_row(t("cli.export.manifest_sha", lang), sidecar.read_text(encoding="utf-8").split()[0])
    console.print(table)
    console.print(f"\n[green]{t('cli.export.done', lang)}[/]")


@app.command(help=_h("cli.jobs.help"))
def jobs(
    data_dir: Path | None = _DataDir,
    show_all: bool = typer.Option(False, "--all", "-a", help=_h("cli.jobs.opt.all")),
    limit: int = typer.Option(20, "--limit", "-n", help=_h("cli.list.opt.limit")),
) -> None:
    """Show the capture queue."""
    lang = _lang()
    store = Store(_resolve_data_dir(data_dir))
    rows = store.list_jobs(statuses=None if show_all else JOB_ACTIVE, limit=limit)
    if not rows:
        console.print(f"[dim]{t('cli.jobs.empty', lang)}[/]")
        raise typer.Exit()
    palette = {"queued": "dim", "running": "cyan", "done": "green", "failed": "red", "cancelled": "dim"}
    table = Table()
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column(t("cli.col.url", lang), overflow="fold")
    table.add_column(t("cli.col.status", lang), no_wrap=True)
    table.add_column(t("cli.col.source", lang), no_wrap=True)
    table.add_column(t("cli.col.capture", lang), overflow="fold")
    for row in rows:
        color = palette.get(row["status"], "white")
        table.add_row(
            row["id"],
            row["url"],
            f"[{color}]{t('web.job.status.' + row['status'], lang)}[/]",
            row["source"],
            row["capture_id"] or "-",
        )
    console.print(table)


@app.command(help=_h("cli.keygen.help"))
def keygen(force: bool = typer.Option(False, "--force", help=_h("cli.keygen.opt.force"))) -> None:
    """Create a signing key."""
    lang = _lang()
    try:
        secret = generate_keypair(force=force)
    except SigningError as exc:
        console.print(f"[yellow]{exc}[/]")
        console.print(t("cli.keygen.force_hint", lang))
        raise typer.Exit(1) from exc
    public = secret.public_key()
    key_dir = default_key_dir()
    console.print(f"[green]{t('cli.keygen.done', lang)}[/]\n")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column(overflow="fold")
    table.add_row(t("cli.keygen.key_id", lang), public.id)
    table.add_row(t("cli.keygen.public", lang), public.base64)
    table.add_row(t("cli.keygen.secret_file", lang), str(key_dir / "webdamga.key"))
    console.print(table)
    console.print(f"\n{t('cli.keygen.share', lang)}")
    console.print(f"[yellow]{t('cli.keygen.protect', lang)}[/]")


@app.command(help=_h("cli.pubkey.help"))
def pubkey() -> None:
    """Print the public key."""
    lang = _lang()
    public = load_public_key()
    if public is None:
        console.print(f"[yellow]{t('cli.pubkey.missing', lang)}[/]")
        raise typer.Exit(1)
    console.print(public.to_minisign(), end="")


@app.command(help=_h("cli.sign.help"))
def sign(
    capture_id: str = typer.Argument(..., help=_h("cli.export.arg.id")),
    data_dir: Path | None = _DataDir,
    force: bool = typer.Option(False, "--force", help=_h("cli.sign.opt.force")),
) -> None:
    """Sign an existing capture's manifest."""
    lang = _lang()
    cap_dir = _resolve_data_dir(data_dir) / "captures" / capture_id
    manifest = cap_dir / "manifest.json"
    if not manifest.is_file():
        console.print(f"[red]{t('cli.verify.not_found', lang)}[/] {manifest}")
        raise typer.Exit(1)
    if (cap_dir / SIGNATURE_NAME).exists() and not force:
        console.print(f"[yellow]{t('cli.sign.exists', lang)}[/]")
        raise typer.Exit(1)
    secret = load_secret_key()
    if secret is None:
        console.print(f"[red]{t('cli.pubkey.missing', lang)}[/]")
        raise typer.Exit(1)
    # Mühürlenmiş manifestoya dokunulmaz; imza yanına ayrı dosya olarak yazılır.
    sig = sign_file(manifest, secret, trusted_comment(capture_id))
    console.print(f"[green]{t('cli.sign.done', lang)}[/] {sig} ({secret.id})")


@app.command("timestamp", help=_h("cli.ts.help"))
def timestamp_command(
    capture_id: str = typer.Argument(..., help=_h("cli.export.arg.id")),
    data_dir: Path | None = _DataDir,
    rfc3161: bool = typer.Option(True, "--rfc3161/--no-rfc3161", help=_h("cli.ts.opt.rfc3161")),
    ots: bool = typer.Option(True, "--ots/--no-ots", help=_h("cli.ts.opt.ots")),
    tsa: str | None = _TsaUrl,
    force: bool = typer.Option(False, "--force", help=_h("cli.ts.opt.force")),
) -> None:
    """Get trusted timestamps for an existing capture's manifest."""
    lang = _lang()
    cap_dir = _resolve_data_dir(data_dir) / "captures" / capture_id
    if not (cap_dir / "manifest.json").is_file():
        console.print(f"[red]{t('cli.verify.not_found', lang)}[/] {cap_dir}")
        raise typer.Exit(1)
    if not force:
        # Var olan damgaları ezme: eski tarihli bir damga yenisinden daha değerli.
        rfc3161 = rfc3161 and not (cap_dir / "manifest.json.tsr").exists()
        ots = ots and not (cap_dir / "manifest.json.ots").exists()
        if not (rfc3161 or ots):
            console.print(f"[yellow]{t('cli.ts.exists', lang)}[/]")
            raise typer.Exit(1)
    console.print(f"[dim]{t('cli.ts.requesting', lang, tsa=tsa or tsa_url())}[/]")
    result = timestamp_capture(cap_dir, rfc3161=rfc3161, opentimestamps=ots, tsa=tsa)
    _print_timestamp_result(result, lang)
    if not any(entry.get("ok") for entry in result.values()):
        raise typer.Exit(1)


@app.command("warc", help=_h("cli.warc.help"))
def warc_command(
    capture_id: str = typer.Argument(..., help=_h("cli.export.arg.id")),
    data_dir: Path | None = _DataDir,
    output: Path | None = _WarcOutput,
) -> None:
    """Build a WARC file for a capture that does not have one."""
    lang = _lang()
    cap_dir = _resolve_data_dir(data_dir) / "captures" / capture_id
    if not cap_dir.is_dir():
        console.print(f"[red]{t('cli.verify.not_found', lang)}[/] {cap_dir}")
        raise typer.Exit(1)
    existing = cap_dir / WARC_NAME
    if existing.is_file() and output is None:
        console.print(t("cli.warc.exists", lang, path=existing))
        raise typer.Exit()
    har = cap_dir / "network.har"
    if not har.is_file():
        console.print(f"[red]{t('cli.warc.no_har', lang)}[/]")
        raise typer.Exit(1)

    meta = json.loads((cap_dir / "metadata.json").read_text(encoding="utf-8"))
    exchanges = exchanges_from_har(har)
    # Mühürlü klasöre yazmıyoruz: yeni bir dosya manifestoyu bozardı.
    target = Path(output) if output else Path.cwd() / f"webdamga-{capture_id}.warc.gz"
    summary = write_warc(target, exchanges, meta=meta, capture_dir=cap_dir)
    lossy = sum(1 for ex in exchanges if ex.body_source == "har-text")

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column(overflow="fold")
    table.add_row(t("cli.warc.written", lang), str(target))
    table.add_row(t("cli.warc.records", lang), str(summary["records"]))
    console.print(table)
    if lossy:
        console.print(f"[yellow]{t('cli.warning', lang)}[/] {t('cli.warc.lossy', lang, count=lossy)}")


@app.command(help=_h("cli.proxies.help"))
def proxies(data_dir: Path | None = _DataDir) -> None:
    """List proxy profiles."""
    lang = _lang()
    ddir = _resolve_data_dir(data_dir)
    try:
        profiles = load_profiles(ddir)
    except ProxyError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    table = Table()
    table.add_column(t("cli.col.profile", lang), style="cyan", no_wrap=True)
    table.add_column(t("cli.col.proxy", lang), overflow="fold")
    for name, address in sorted(profiles.items()):
        table.add_row(name, redact_proxy(address) or "-")
    console.print(table)
    console.print(f"[dim]{t('cli.proxies.file', lang, path=ddir / 'proxies.json')}[/]")


@app.command(help=_h("cli.serve.help"))
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help=_h("cli.serve.opt.host")),
    port: int = typer.Option(8000, "--port", "-p", help=_h("cli.serve.opt.port")),
    data_dir: Path | None = _DataDir,
) -> None:
    """Start the local web interface."""
    import os

    import uvicorn

    lang = _lang()
    ddir = _resolve_data_dir(data_dir).resolve()
    os.environ["WEBDAMGA_DATA_DIR"] = str(ddir)
    console.print(
        f"[bold]webdamga[/] {t('cli.serve.starting', lang)} → http://{host}:{port}"
        f"  ({t('cli.serve.data', lang)}: {ddir})"
    )
    uvicorn.run("webdamga.api:app", host=host, port=port, reload=False)


@app.command(help=_h("cli.version.help"))
def version() -> None:
    """Print the version."""
    console.print(f"webdamga {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
