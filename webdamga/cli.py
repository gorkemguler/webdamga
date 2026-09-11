"""webdamga komut satırı arayüzü."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .capture import capture as run_capture
from .capture import normalize_url
from .config import CaptureSettings, default_data_dir
from .hashing import verify_capture
from .storage import Store

app = typer.Typer(add_completion=False, help="webdamga — yerel web kanıt/arşiv aracı")
console = Console()

_DataDir = typer.Option(None, "--data-dir", "-d", help="Veri klasörü (varsayılan: ./data)")


def _resolve_data_dir(value: Path | None) -> Path:
    return Path(value) if value else default_data_dir()


@app.command()
def capture(
    url: str = typer.Argument(..., help="Yakalanacak URL"),
    data_dir: Path | None = _DataDir,
    full_page: bool = typer.Option(True, "--full-page/--no-full-page", help="Tam sayfa ekran görüntüsü"),
    timeout: int = typer.Option(30, "--timeout", "-t", help="Gezinme zaman aşımı (sn)"),
    wait_until: str = typer.Option("load", "--wait-until", help="load|domcontentloaded|networkidle|commit"),
    wait: float = typer.Option(1.5, "--wait", help="Yükleme sonrası ek bekleme (sn)"),
    width: int = typer.Option(1280, "--width", help="Görünüm genişliği"),
    height: int = typer.Option(800, "--height", help="Görünüm yüksekliği"),
    user_agent: str | None = typer.Option(None, "--user-agent", "-A", help="User-Agent'ı geçersiz kıl"),
    headful: bool = typer.Option(False, "--headful", help="Tarayıcıyı görünür çalıştır (PDF üretilmez)"),
) -> None:
    """Bir URL'yi yakala ve kanıt klasörünü mühürle."""
    ddir = _resolve_data_dir(data_dir)
    settings = CaptureSettings(
        wait_until=wait_until,
        timeout_ms=int(timeout * 1000),
        extra_wait_ms=int(wait * 1000),
        full_page=full_page,
        viewport_width=width,
        viewport_height=height,
        headless=not headful,
        pdf=not headful,
    )
    if user_agent:
        settings.user_agent = user_agent

    store = Store(ddir)
    console.print(f"[bold]webdamga[/] yakalıyor → [cyan]{normalize_url(url)}[/]")
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
    table.add_row("id", meta["capture_id"])
    table.add_row("nihai URL", str(meta.get("final_url")))
    table.add_row("HTTP", f"{meta.get('http_status')} {meta.get('http_status_text', '')}".strip())
    table.add_row("başlık", str(meta.get("page_title")))
    addr = meta.get("remote_address") or {}
    if addr:
        table.add_row("sunucu IP", f"{addr.get('ipAddress')}:{addr.get('port')}")
    tls = meta.get("tls") or {}
    if tls:
        table.add_row("TLS", f"{tls.get('protocol')} · {tls.get('issuer')}")
    rs = meta.get("resource_summary") or {}
    if rs:
        table.add_row(
            "kaynaklar", f"{rs.get('request_count')} istek · {rs.get('transfer_bytes', 0) / 1024:.1f} KB"
        )
    table.add_row("klasör", meta["dir"])
    table.add_row("manifest sha256", meta.get("manifest_sha256", "-"))
    console.print(table)
    if meta.get("error"):
        console.print(f"[yellow]uyarı:[/] {meta['error']}")


@app.command("list")
def list_captures(
    data_dir: Path | None = _DataDir,
    limit: int = typer.Option(20, "--limit", "-n", help="Gösterilecek kayıt sayısı"),
) -> None:
    """Son yakalamaları listele."""
    store = Store(_resolve_data_dir(data_dir))
    rows = store.list(limit)
    if not rows:
        console.print("[dim]Kayıt yok.[/]")
        raise typer.Exit()
    table = Table()
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column("URL", overflow="fold")
    table.add_column("HTTP", justify="right")
    table.add_column("tarih (UTC)", no_wrap=True)
    for row in rows:
        mark = "" if row["ok"] else " [red]✗[/]"
        table.add_row(
            row["id"] + mark,
            row["final_url"] or row["requested_url"],
            str(row["http_status"] or "—"),
            row["created_utc"],
        )
    console.print(table)


@app.command()
def verify(
    capture_id: str = typer.Argument(..., help="Yakalama id'si"),
    data_dir: Path | None = _DataDir,
) -> None:
    """Bir yakalama klasörünü manifestoya göre doğrula (bütünlük kontrolü)."""
    cap_dir = _resolve_data_dir(data_dir) / "captures" / capture_id
    if not cap_dir.is_dir():
        console.print(f"[red]Bulunamadı:[/] {cap_dir}")
        raise typer.Exit(1)

    result = verify_capture(cap_dir)
    table = Table(title=f"doğrulama · {capture_id}")
    table.add_column("dosya", style="cyan")
    table.add_column("durum")
    palette = {"ok": "green", "modified": "red", "missing": "red", "unlisted": "yellow"}
    for item in result["files"]:
        color = palette.get(item["status"], "white")
        table.add_row(item["name"], f"[{color}]{item['status']}[/]")
    console.print(table)
    if result["ok"]:
        console.print("\n[green]BÜTÜN[/] — hiçbir dosya değiştirilmemiş.")
        raise typer.Exit(0)
    console.print("\n[red]BOZULMUŞ[/] — yakalama klasöründe değişiklik var.")
    raise typer.Exit(2)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Dinlenecek arayüz"),
    port: int = typer.Option(8000, "--port", "-p"),
    data_dir: Path | None = _DataDir,
) -> None:
    """Yerel web arayüzünü başlat."""
    import os

    import uvicorn

    ddir = _resolve_data_dir(data_dir).resolve()
    os.environ["WEBDAMGA_DATA_DIR"] = str(ddir)
    console.print(f"[bold]webdamga[/] arayüz → http://{host}:{port}  (veri: {ddir})")
    uvicorn.run("webdamga.api:app", host=host, port=port, reload=False)


@app.command()
def version() -> None:
    """Sürümü yazdır."""
    console.print(f"webdamga {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
