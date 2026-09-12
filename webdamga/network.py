"""Yakalamanın hangi ağ yolundan yapılacağı: doğrudan, proxy ya da Tor.

Phishing sayfaları sık sık ziyaretçinin IP'sine ya da ülkesine göre farklı
içerik gösterir (geo-cloaking). Aynı URL'yi farklı çıkış noktalarından
yakalayabilmek için yakalama bir proxy üzerinden yapılabilir.

"Ülke seçimi" adlandırılmış proxy profilleriyle yapılır: `<data>/proxies.json`
içinde her profil bir proxy adresine eşlenir ({"de": "socks5://...", ...}).
webdamga kendi başına ülke IP'si sağlamaz; hangi ülkeden çıkılacağını
kullanıcının proxy'si belirler. Tor her zaman yerleşik profil olarak vardır.

Proxy adresindeki kullanıcı adı/parola hiçbir zaman metadata'ya, rapora ya
da loglara yazılmaz; oralarda yalnızca `redact_proxy` çıktısı kullanılır.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

TOR_PROFILE = "tor"
TOR_PROXY = "socks5://127.0.0.1:9050"
PROFILES_FILE = "proxies.json"
EGRESS_CHECK_URL = "https://check.torproject.org/api/ip"

_SCHEMES = {"http", "https", "socks4", "socks5"}
_DEFAULT_PORTS = {"http": 80, "https": 443, "socks4": 1080, "socks5": 1080}


class ProxyError(ValueError):
    """Geçersiz ya da desteklenmeyen proxy yapılandırması."""


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def server(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.scheme}://{host}:{self.port}"

    def playwright(self) -> dict:
        """Playwright'in `proxy=` parametresinin beklediği biçim."""
        out: dict = {"server": self.server}
        if self.username is not None:
            out["username"] = self.username
            out["password"] = self.password or ""
        return out


def parse_proxy(url: str) -> ProxyConfig:
    raw = (url or "").strip()
    if not raw:
        raise ProxyError("empty proxy address")
    if "://" not in raw:
        raise ProxyError(f"proxy address needs a scheme, e.g. socks5://{raw}")
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme == "socks5h":
        # Chromium SOCKS5'te DNS'i zaten proxy tarafında çözer.
        scheme = "socks5"
    if scheme not in _SCHEMES:
        raise ProxyError(f"unsupported proxy scheme '{parts.scheme}' ({', '.join(sorted(_SCHEMES))})")
    if not parts.hostname:
        raise ProxyError("proxy address has no host")
    try:
        port = parts.port or _DEFAULT_PORTS[scheme]
    except ValueError as exc:
        raise ProxyError(f"invalid proxy port: {exc}") from exc
    username = unquote(parts.username) if parts.username is not None else None
    password = unquote(parts.password) if parts.password is not None else None
    if username is not None and scheme.startswith("socks"):
        # Chromium SOCKS proxy kimlik doğrulamasını desteklemiyor; sessizce
        # kimliksiz bağlanıp yanlış çıkış noktasından yakalamaktansa reddet.
        raise ProxyError("Chromium does not support authenticated SOCKS proxies; use an http proxy")
    return ProxyConfig(scheme, parts.hostname, port, username, password)


def redact_proxy(url: str | None) -> str | None:
    """Kimlik bilgilerini atılmış, kayda geçirilebilir proxy adresi."""
    if not url:
        return None
    try:
        return parse_proxy(url).server
    except ProxyError:
        return "<invalid proxy>"


def load_profiles(data_dir: Path) -> dict[str, str]:
    """Yerleşik Tor profili + `<data>/proxies.json` içindekiler."""
    profiles: dict[str, str] = {TOR_PROFILE: TOR_PROXY}
    path = Path(data_dir) / PROFILES_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ProxyError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ProxyError(f"{path} must be a JSON object of name -> proxy address")
        for name, address in data.items():
            if not isinstance(name, str) or not isinstance(address, str):
                raise ProxyError(f"{path}: profile names and addresses must be strings")
            parse_proxy(address)  # hatalı profil yakalama anında değil burada patlasın
            profiles[name] = address
    return profiles


@dataclass(frozen=True, slots=True)
class Route:
    """Bir yakalama için çözülmüş ağ yolu."""

    mode: str  # direct | proxy | tor
    proxy: ProxyConfig | None = None
    profile: str | None = None

    def describe(self) -> dict:
        """metadata.json'a yazılan, kimlik bilgisi içermeyen özet."""
        return {
            "mode": self.mode,
            "profile": self.profile,
            "proxy": self.proxy.server if self.proxy else None,
        }


def resolve_route(proxy: str | None, profile: str | None, data_dir: Path) -> Route:
    if proxy and profile:
        raise ProxyError("choose either a proxy address or a proxy profile, not both")
    if profile:
        profiles = load_profiles(data_dir)
        if profile not in profiles:
            known = ", ".join(sorted(profiles))
            raise ProxyError(f"unknown proxy profile '{profile}' (known: {known})")
        config = parse_proxy(profiles[profile])
        mode = "tor" if profile == TOR_PROFILE else "proxy"
        return Route(mode, config, profile)
    if proxy:
        config = parse_proxy(proxy)
        mode = "tor" if config.server == TOR_PROXY else "proxy"
        return Route(mode, config)
    return Route("direct")


def ensure_reachable(config: ProxyConfig, timeout: float = 3.0) -> None:
    """Proxy portu kapalıysa anlaşılır bir hata üretir.

    Aksi hâlde Chromium yalnızca net::ERR_PROXY_CONNECTION_FAILED der ve
    kullanıcı Tor'u başlatmayı unuttuğunu anlamaz.
    """
    try:
        with socket.create_connection((config.host, config.port), timeout=timeout):
            pass
    except OSError as exc:
        hint = " (is tor running?)" if config.server == TOR_PROXY else ""
        raise ProxyError(f"proxy {config.server} is not reachable: {exc}{hint}") from exc


def parse_egress(payload: str) -> dict:
    """check.torproject.org/api/ip yanıtını {ip, is_tor} biçimine çevirir."""
    data = json.loads(payload)
    return {"ip": data.get("IP"), "is_tor": bool(data.get("IsTor")), "source": EGRESS_CHECK_URL}
