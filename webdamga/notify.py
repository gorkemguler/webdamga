"""İzlenen bir sayfa değiştiğinde bildirim.

İzleyici bir değişiklik bulduğunda kullanıcının arayüze bakması gerekmesin;
haber gitsin. İki kanal, ikisi de isteğe bağlı ve yapılandırmayla açılır:

  webhook   Bir URL'ye JSON POST (Slack/Discord/kendi uç noktan). Slack ve
            Discord'un "incoming webhook" biçimi de desteklenir.
  e-posta   Standart smtplib ile bir SMTP sunucusu üzerinden.

Yapılandırma ortam değişkenleriyle (sırlar koda girmesin):

  WEBDAMGA_WEBHOOK_URL          POST edilecek adres
  WEBDAMGA_WEBHOOK_FORMAT       json | slack | discord   (varsayılan json)
  WEBDAMGA_NOTIFY_LEVEL         minor | major            (varsayılan major)
  WEBDAMGA_SMTP_HOST/PORT       SMTP sunucusu
  WEBDAMGA_SMTP_USER/PASSWORD   kimlik (varsa)
  WEBDAMGA_SMTP_FROM/TO         gönderen ve alıcı(lar), virgülle
  WEBDAMGA_SMTP_TLS             starttls için 1/0     (varsayılan 1)
  WEBDAMGA_BASE_URL             linkleri mutlak yapmak için (ör. http://pi:8000)

Bildirim gönderimi yakalamayı ya da izlemeyi bloklamaz; hata loglanır.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage

from . import __version__

log = logging.getLogger("webdamga.notify")

_LEVEL_ORDER = {"identical": 0, "minor": 1, "major": 2}
_TIMEOUT = 15.0


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    """İzleyici bir değişiklik bulduğunda üretilen bildirim gövdesi."""

    monitor_id: int
    label: str | None
    url: str
    level: str  # minor | major
    previous_id: str
    capture_id: str
    reasons: list[str]
    detected_utc: str

    def as_dict(self) -> dict:
        base = os.environ.get("WEBDAMGA_BASE_URL", "").rstrip("/")
        return {
            "tool": "webdamga",
            "version": __version__,
            "event": "capture_changed",
            "monitor_id": self.monitor_id,
            "label": self.label,
            "url": self.url,
            "level": self.level,
            "previous_capture": self.previous_id,
            "capture": self.capture_id,
            "reasons": self.reasons,
            "detected_utc": self.detected_utc,
            "diff_url": f"{base}/diff?a={self.previous_id}&b={self.capture_id}" if base else None,
            "capture_url": f"{base}/captures/{self.capture_id}" if base else None,
        }

    def headline(self) -> str:
        who = self.label or self.url
        word = "significant" if self.level == "major" else "minor"
        return f"webdamga: {word} change on {who}"

    def text(self) -> str:
        lines = [self.headline(), "", f"URL: {self.url}", f"Change: {self.level}", ""]
        lines += [f"- {r}" for r in self.reasons]
        payload = self.as_dict()
        if payload["diff_url"]:
            lines += ["", f"Comparison: {payload['diff_url']}"]
        return "\n".join(lines)


# ------------------------------------------------------------------- eşik


def notify_level() -> str:
    level = os.environ.get("WEBDAMGA_NOTIFY_LEVEL", "major").strip().lower()
    return level if level in ("minor", "major") else "major"


def should_notify(level: str) -> bool:
    return _LEVEL_ORDER.get(level, 0) >= _LEVEL_ORDER[notify_level()]


# ------------------------------------------------------------------- webhook


def _webhook_payload(event: ChangeEvent, fmt: str) -> tuple[bytes, dict]:
    if fmt == "slack":
        body = {"text": event.text()}
    elif fmt == "discord":
        body = {"content": event.text()}
    else:
        body = event.as_dict()
    return json.dumps(body).encode(), {"Content-Type": "application/json"}


def send_webhook(event: ChangeEvent, *, url: str | None = None, fmt: str | None = None) -> bool:
    url = url or os.environ.get("WEBDAMGA_WEBHOOK_URL")
    if not url:
        return False
    fmt = (fmt or os.environ.get("WEBDAMGA_WEBHOOK_FORMAT", "json")).strip().lower()
    data, headers = _webhook_payload(event, fmt)
    headers["User-Agent"] = f"webdamga/{__version__}"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        log.warning("webhook rejected: HTTP %s", exc.code)
        return False
    except OSError as exc:
        log.warning("webhook failed: %s", exc)
        return False


# ------------------------------------------------------------------- e-posta


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str
    port: int
    sender: str
    recipients: list[str]
    username: str | None = None
    password: str | None = None
    use_tls: bool = True

    @classmethod
    def from_env(cls) -> SmtpConfig | None:
        host = os.environ.get("WEBDAMGA_SMTP_HOST")
        sender = os.environ.get("WEBDAMGA_SMTP_FROM")
        recipients = [r.strip() for r in os.environ.get("WEBDAMGA_SMTP_TO", "").split(",") if r.strip()]
        if not (host and sender and recipients):
            return None
        return cls(
            host=host,
            port=int(os.environ.get("WEBDAMGA_SMTP_PORT", "587")),
            sender=sender,
            recipients=recipients,
            username=os.environ.get("WEBDAMGA_SMTP_USER"),
            password=os.environ.get("WEBDAMGA_SMTP_PASSWORD"),
            use_tls=os.environ.get("WEBDAMGA_SMTP_TLS", "1") not in ("0", "false", "no"),
        )


def build_email(event: ChangeEvent, config: SmtpConfig) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = event.headline()
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message.set_content(event.text())
    return message


def send_email(event: ChangeEvent, config: SmtpConfig | None = None) -> bool:
    config = config or SmtpConfig.from_env()
    if config is None:
        return False
    message = build_email(event, config)
    try:
        with smtplib.SMTP(config.host, config.port, timeout=_TIMEOUT) as server:
            if config.use_tls:
                server.starttls(context=ssl.create_default_context())
            if config.username:
                server.login(config.username, config.password or "")
            server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("email failed: %s", exc)
        return False


# ------------------------------------------------------------------- dağıtım


def dispatch(event: ChangeEvent) -> dict:
    """Yapılandırılmış tüm kanallara gönderir; hangisi denendi/başardı döner."""
    result: dict = {}
    if os.environ.get("WEBDAMGA_WEBHOOK_URL"):
        result["webhook"] = send_webhook(event)
    if SmtpConfig.from_env() is not None:
        result["email"] = send_email(event)
    return result


def configured_channels() -> list[str]:
    channels = []
    if os.environ.get("WEBDAMGA_WEBHOOK_URL"):
        channels.append("webhook")
    if SmtpConfig.from_env() is not None:
        channels.append("email")
    return channels
