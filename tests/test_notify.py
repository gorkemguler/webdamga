"""Değişiklik bildirimleri: eşik, webhook biçimleri, e-posta, dağıtım."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from webdamga import notify
from webdamga.notify import (
    ChangeEvent,
    SmtpConfig,
    build_email,
    configured_channels,
    dispatch,
    send_webhook,
    should_notify,
)


def _event(level: str = "major") -> ChangeEvent:
    return ChangeEvent(
        monitor_id=7,
        label="Örnek Banka",
        url="https://bank.example/login",
        level=level,
        previous_id="cap-old",
        capture_id="cap-new",
        reasons=["A password field appeared", "A form now submits to another host: collect.evil"],
        detected_utc="2026-01-01T00:00:00Z",
    )


class _Collector:
    def __init__(self, status: int = 200) -> None:
        self.status, self.received = status, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                outer.received.append((self.headers.get("Content-Type"), self.rfile.read(n)))
                self.send_response(outer.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/hook"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()


# --------------------------------------------------------------------- eşik


def test_should_notify_respects_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBDAMGA_NOTIFY_LEVEL", "major")
    assert should_notify("major") is True
    assert should_notify("minor") is False

    monkeypatch.setenv("WEBDAMGA_NOTIFY_LEVEL", "minor")
    assert should_notify("minor") is True
    assert should_notify("major") is True
    assert should_notify("identical") is False


def test_default_threshold_is_major(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBDAMGA_NOTIFY_LEVEL", raising=False)
    assert should_notify("minor") is False
    assert should_notify("major") is True


# ------------------------------------------------------------------- event


def test_event_payload_includes_urls_when_base_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBDAMGA_BASE_URL", "http://pi.local:8000/")
    payload = _event().as_dict()
    assert payload["event"] == "capture_changed"
    assert payload["level"] == "major"
    assert payload["diff_url"] == "http://pi.local:8000/diff?a=cap-old&b=cap-new"
    assert payload["capture_url"] == "http://pi.local:8000/captures/cap-new"


def test_event_payload_without_base_has_no_links(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBDAMGA_BASE_URL", raising=False)
    payload = _event().as_dict()
    assert payload["diff_url"] is None
    assert payload["capture_url"] is None


def test_event_text_lists_reasons() -> None:
    text = _event().text()
    assert "significant change" in text
    assert "A password field appeared" in text


# ----------------------------------------------------------------- webhook


def test_webhook_json_format() -> None:
    with _Collector() as c:
        assert send_webhook(_event(), url=c.url, fmt="json") is True
    content_type, body = c.received[0]
    assert content_type == "application/json"
    payload = json.loads(body)
    assert payload["monitor_id"] == 7
    assert payload["reasons"][0] == "A password field appeared"


def test_webhook_slack_format() -> None:
    with _Collector() as c:
        send_webhook(_event(), url=c.url, fmt="slack")
    payload = json.loads(c.received[0][1])
    assert "text" in payload and "bank.example" in payload["text"]


def test_webhook_discord_format() -> None:
    with _Collector() as c:
        send_webhook(_event(), url=c.url, fmt="discord")
    assert "content" in json.loads(c.received[0][1])


def test_webhook_reports_failure_on_5xx() -> None:
    with _Collector(status=500) as c:
        assert send_webhook(_event(), url=c.url) is False


def test_webhook_unreachable_is_false() -> None:
    assert send_webhook(_event(), url="http://127.0.0.1:1/hook") is False


def test_webhook_without_url_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBDAMGA_WEBHOOK_URL", raising=False)
    assert send_webhook(_event()) is False


# ------------------------------------------------------------------- e-posta


def test_smtp_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBDAMGA_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("WEBDAMGA_SMTP_FROM", "bot@example")
    monkeypatch.setenv("WEBDAMGA_SMTP_TO", "a@example, b@example")
    config = SmtpConfig.from_env()
    assert config.host == "smtp.example"
    assert config.recipients == ["a@example", "b@example"]
    assert config.port == 587 and config.use_tls is True


def test_smtp_config_none_without_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("WEBDAMGA_SMTP_HOST", "WEBDAMGA_SMTP_FROM", "WEBDAMGA_SMTP_TO"):
        monkeypatch.delenv(var, raising=False)
    assert SmtpConfig.from_env() is None


def test_build_email_headers() -> None:
    config = SmtpConfig("smtp.example", 587, "bot@example", ["abuse@bank.example"])
    message = build_email(_event(), config)
    assert message["To"] == "abuse@bank.example"
    assert "Örnek Banka" in message["Subject"]  # etiket varsa başlık onu kullanır
    assert "bank.example" in message.get_content()  # URL gövdede
    assert "A password field appeared" in message.get_content()


def test_send_email_uses_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = {}

    class _SMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"], sent["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def starttls(self, context=None):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = user

        def send_message(self, message):
            sent["to"] = message["To"]

    monkeypatch.setattr(notify.smtplib, "SMTP", _SMTP)
    config = SmtpConfig(
        "smtp.example", 587, "bot@example", ["abuse@bank.example"], username="u", password="p"
    )
    assert notify.send_email(_event(), config) is True
    assert sent["host"] == "smtp.example" and sent["tls"] is True and sent["login"] == "u"
    assert sent["to"] == "abuse@bank.example"


# ------------------------------------------------------------------ dağıtım


def test_configured_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("WEBDAMGA_WEBHOOK_URL", "WEBDAMGA_SMTP_HOST", "WEBDAMGA_SMTP_FROM", "WEBDAMGA_SMTP_TO"):
        monkeypatch.delenv(var, raising=False)
    assert configured_channels() == []
    monkeypatch.setenv("WEBDAMGA_WEBHOOK_URL", "http://x/hook")
    assert configured_channels() == ["webhook"]


def test_dispatch_calls_configured_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    with _Collector() as c:
        monkeypatch.setenv("WEBDAMGA_WEBHOOK_URL", c.url)
        for var in ("WEBDAMGA_SMTP_HOST", "WEBDAMGA_SMTP_FROM", "WEBDAMGA_SMTP_TO"):
            monkeypatch.delenv(var, raising=False)
        result = dispatch(_event())
    assert result == {"webhook": True}
    assert c.received  # gerçekten POST edildi


# ---------------------------------------------------- izleyiciyle bütünleşme


def test_monitor_change_triggers_webhook(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from test_diff import PHISH
    from test_monitor import _Site  # aynı sahte yakalama altyapısı

    from webdamga.jobs import CaptureQueue
    from webdamga.monitor import Scheduler, add_monitor
    from webdamga.storage import Store

    with _Collector() as c:
        monkeypatch.setenv("WEBDAMGA_WEBHOOK_URL", c.url)
        monkeypatch.setenv("WEBDAMGA_NOTIFY_LEVEL", "major")
        store = Store(tmp_path)
        site = _Site(tmp_path)
        queue = CaptureQueue(store, tmp_path, capture_fn=site.capture)
        scheduler = Scheduler(store, queue)
        monitor = add_monitor(store, "https://bank.example/login", 5)

        async def drain():
            while await queue.run_once():
                pass

        scheduler.run_now(monitor)
        asyncio.run(drain())  # ilk tur: taban
        assert not c.received  # değişiklik yok, bildirim yok

        site.html = PHISH
        scheduler.run_now(store.get_monitor(monitor["id"]))
        asyncio.run(drain())  # ikinci tur: önemli değişiklik

    assert c.received, "önemli değişiklikte webhook gitmeli"
    payload = json.loads(c.received[0][1])
    assert payload["level"] == "major"
    assert payload["monitor_id"] == monitor["id"]
    assert any("password" in r.lower() for r in payload["reasons"])
