"""Yakalama ayarları ve varsayılan yollar."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def default_data_dir() -> Path:
    """Veri klasörü: WEBDAMGA_DATA_DIR ortam değişkeni ya da ./data."""
    return Path(os.environ.get("WEBDAMGA_DATA_DIR", Path.cwd() / "data"))


# Gerçekçi, sabit bir masaüstü Chrome kimliği. None bırakılırsa Playwright'in
# kendi (headless) User-Agent'ı kullanılır.
DEFAULT_USER_AGENT: str | None = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class CaptureSettings:
    """Tek bir yakalamanın davranışını belirleyen ayarlar."""

    wait_until: str = "load"  # load | domcontentloaded | networkidle | commit
    timeout_ms: int = 30_000
    extra_wait_ms: int = 1_500  # yükleme sonrası, sayfa otursun diye ek bekleme
    full_page: bool = True
    viewport_width: int = 1280
    viewport_height: int = 800
    user_agent: str | None = DEFAULT_USER_AGENT
    color_scheme: str = "light"  # light | dark | no-preference
    headless: bool = True
    pdf: bool = True
    har_content: str = "embed"  # embed | attach | omit
    proxy: str | None = None  # ör. socks5://127.0.0.1:9050, http://user:pass@host:3128
    proxy_profile: str | None = None  # <data>/proxies.json içindeki ad ya da "tor"
    record_egress: bool = False  # çıkış IP'sini check.torproject.org ile kaydet
    warc: bool = True  # yeniden oynatılabilir archive.warc.gz üret

    def as_dict(self) -> dict:
        """metadata.json'a yazılan, okunur biçim. Proxy kimlik bilgisi içermez."""
        from .network import redact_proxy

        return {
            "wait_until": self.wait_until,
            "timeout_ms": self.timeout_ms,
            "extra_wait_ms": self.extra_wait_ms,
            "full_page": self.full_page,
            "viewport": {"width": self.viewport_width, "height": self.viewport_height},
            "user_agent": self.user_agent,
            "color_scheme": self.color_scheme,
            "headless": self.headless,
            "pdf": self.pdf,
            "har_content": self.har_content,
            "proxy": redact_proxy(self.proxy),
            "proxy_profile": self.proxy_profile,
            "record_egress": self.record_egress,
            "warc": self.warc,
        }

    def to_storage(self) -> dict:
        """Kuyrukta/izleyicide saklamak için düz, geri okunabilir biçim."""
        return asdict(self)

    @classmethod
    def from_storage(cls, data: dict | None) -> CaptureSettings:
        """`to_storage` çıktısını geri okur; bilinmeyen alanları yok sayar."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})
