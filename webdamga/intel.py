"""İhbar için kayıt bilgisi: alan adı, IP sahibi, ASN ve abuse iletişimi.

Bir phishing sayfasını ihbar ederken ilk iş "kime yazacağım" sorusudur:
alan adının registrar'ı, sayfayı barındıran ağın sahibi ve o ağın abuse
e-postası. Bu modül bunları toplayıp raporun ve arayüzün gösterebileceği
tek bir sözlük üretir. Yalnızca standart kütüphane kullanılır:

  alan adı   RDAP üzerinden (rdap.org yönlendirmesi): kayıt/bitiş tarihi,
             registrar ve registrar'ın abuse iletişimi
  IP         RDAP üzerinden: ağ adı, ülke, aralık ve abuse e-postası
  ASN        Team Cymru'nun toplu whois'i (port 43): AS numarası ve org adı

Ağ çağrıları yakalamanın parçası değildir; ayrı, en iyi çaba temelli
çalışır ve hata verse bile yakalamayı etkilemez. Sorgular hedef sunucuya
değil, kayıt otoritelerine (RDAP, Cymru) gider.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from datetime import UTC, datetime

from . import __version__

RDAP_BASE = "https://rdap.org"
CYMRU_SERVER = "whois.cymru.com"
_UA = f"webdamga/{__version__}"
_TIMEOUT = 15.0


class IntelError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rdap(path: str) -> dict:
    url = f"{RDAP_BASE}/{path}"
    request = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/rdap+json, application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise IntelError(f"RDAP {path}: HTTP {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise IntelError(f"RDAP {path}: {exc}") from exc


# ------------------------------------------------------------------ vCard ayrıştırma


def _vcard_fields(entity: dict) -> dict:
    """vcardArray'den okunur alanları (ad, e-posta, telefon) çıkarır."""
    out: dict = {"emails": [], "phones": []}
    vcard = entity.get("vcardArray")
    if not (isinstance(vcard, list) and len(vcard) > 1):
        return out
    for item in vcard[1]:
        if not (isinstance(item, list) and len(item) >= 4):
            continue
        kind, value = item[0], item[3]
        if kind == "fn" and value:
            out["name"] = value
        elif kind == "email" and value:
            out["emails"].append(value)
        elif kind == "tel" and value:
            out["phones"].append(value)
    return out


def _iter_entities(entities: list | None):
    """İç içe entity ağacını (registrar altındaki abuse gibi) düz gezer."""
    for entity in entities or []:
        yield entity
        yield from _iter_entities(entity.get("entities"))


def _abuse_contact(entities: list | None) -> dict | None:
    for entity in _iter_entities(entities):
        if "abuse" in (entity.get("roles") or []):
            fields = _vcard_fields(entity)
            if fields["emails"] or fields.get("name"):
                return {
                    "handle": entity.get("handle"),
                    "name": fields.get("name"),
                    "emails": fields["emails"],
                    "phones": fields["phones"],
                }
    return None


def _entity_with_role(entities: list | None, role: str) -> dict | None:
    for entity in _iter_entities(entities):
        if role in (entity.get("roles") or []):
            fields = _vcard_fields(entity)
            return {"handle": entity.get("handle"), "name": fields.get("name") or entity.get("handle")}
    return None


def _events(data: dict) -> dict:
    return {e.get("eventAction"): e.get("eventDate") for e in data.get("events", []) if e.get("eventAction")}


# --------------------------------------------------------------------- alan adı


def domain_intel(domain: str) -> dict:
    """Alan adı için registrar ve kayıt tarihleri (RDAP)."""
    data = _rdap(f"domain/{domain.lower().strip('.')}")
    events = _events(data)
    registrar = _entity_with_role(data.get("entities"), "registrar")
    return {
        "domain": data.get("ldhName", domain).lower(),
        "registrar": registrar["name"] if registrar else None,
        "registered": events.get("registration"),
        "expires": events.get("expiration"),
        "last_changed": events.get("last changed"),
        "statuses": data.get("status", []),
        "nameservers": [ns.get("ldhName") for ns in data.get("nameservers", []) if ns.get("ldhName")],
        "abuse": _abuse_contact(data.get("entities")),
    }


# --------------------------------------------------------------------------- IP


def ip_intel(ip: str) -> dict:
    """IP için ağ sahibi, ülke ve abuse iletişimi (RDAP)."""
    data = _rdap(f"ip/{ip}")
    cidr = None
    if data.get("startAddress") and data.get("cidr0_cidrs"):
        first = data["cidr0_cidrs"][0]
        prefix = first.get("v4prefix") or first.get("v6prefix")
        length = first.get("length")
        if prefix and length is not None:
            cidr = f"{prefix}/{length}"
    return {
        "ip": ip,
        "network_name": data.get("name"),
        "handle": data.get("handle"),
        "country": data.get("country"),
        "range": f"{data.get('startAddress')} - {data.get('endAddress')}"
        if data.get("startAddress")
        else None,
        "cidr": cidr,
        "abuse": _abuse_contact(data.get("entities")),
    }


# -------------------------------------------------------------------------- ASN


def asn_intel(ip: str) -> dict:
    """IP'nin origin AS numarası ve org adı (Team Cymru, port 43 whois)."""
    query = f"begin\nverbose\n{ip}\nend\n"
    try:
        with socket.create_connection((CYMRU_SERVER, 43), timeout=_TIMEOUT) as sock:
            sock.sendall(query.encode())
            raw = bytearray()
            while chunk := sock.recv(4096):
                raw.extend(chunk)
    except OSError as exc:
        raise IntelError(f"Cymru whois: {exc}") from exc

    for line in raw.decode("utf-8", "replace").splitlines():
        if line.lower().startswith(("bulk mode", "as ")) or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 7 and parts[0].isdigit():
            return {"asn": parts[0], "cidr": parts[2], "country": parts[3], "org": parts[6]}
    raise IntelError("Cymru whois: no origin AS in response")


# ---------------------------------------------------------------------- birleşik


def _first_ip(meta: dict) -> str | None:
    addr = meta.get("remote_address") or {}
    ip = (addr.get("ipAddress") or "").strip("[]")
    return ip or None


def gather(meta: dict, *, domain: bool = True, network: bool = True) -> dict:
    """Bir yakalamanın metadata'sından ihbar istihbaratını toplar.

    Her parça bağımsız denenir; biri patlarsa diğerleri yine döner ve hata
    ilgili bölümde 'error' olarak raporlanır.
    """
    from urllib.parse import urlsplit

    result: dict = {"collected_at_utc": _now_iso(), "source": "RDAP (rdap.org), Team Cymru"}
    host = urlsplit(meta.get("final_url") or meta.get("requested_url") or "").hostname

    if domain and host and not _is_ip(host):
        try:
            result["domain"] = domain_intel(_registrable(host))
        except IntelError as exc:
            result["domain"] = {"error": str(exc)}

    ip = _first_ip(meta)
    if network and ip:
        try:
            result["ip"] = ip_intel(ip)
        except IntelError as exc:
            result["ip"] = {"error": str(exc)}
        try:
            result["asn"] = asn_intel(ip)
        except IntelError as exc:
            result["asn"] = {"error": str(exc)}

    result["abuse_emails"] = _collect_abuse(result)
    return result


def _collect_abuse(result: dict) -> list[str]:
    """Rapora konacak, tekrarsız abuse e-posta listesi."""
    seen: list[str] = []
    for section in ("domain", "ip"):
        abuse = (result.get(section) or {}).get("abuse") or {}
        for email in abuse.get("emails", []):
            if email not in seen:
                seen.append(email)
    return seen


def _is_ip(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _registrable(host: str) -> str:
    """Alt alan adından kayıtlı alan adını kabaca çıkarır (www.a.example -> a.example).

    Tam bir public-suffix listesi yok; iki etiketli ccTLD'lerde (co.uk, com.tr)
    fazladan bir etiket bırakır, RDAP çoğu durumda yine doğru sonucu döndürür.
    """
    host = host.lower().strip(".")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    two_level = {"co", "com", "org", "net", "gov", "edu", "ac", "gob", "nic"}
    if parts[-2] in two_level and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])
