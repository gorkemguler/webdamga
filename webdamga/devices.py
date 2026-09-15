"""Cihaz taklidi: bir sayfayı belirli bir cihaz gibi yakalamak.

SMS phishing (smishing) sayfalarının çoğu yalnızca mobil tarayıcıya içerik
gösterir; masaüstünden bakınca boş sayfa, hata ya da masum bir yönlendirme
döner. Bir kanıt aracının kurbanın gördüğü hâli yakalayabilmesi için sayfayı
o cihaz gibi açabilmesi gerekir.

Cihaz tanımları Playwright'in kendi kayıtlarından (pw.devices) alınır; böylece
User-Agent, viewport, ölçek, dokunmatik ve mobil bayrağı gerçek cihazla
tutarlı olur. Ada göre erişim büyük/küçük harf ve boşluğa duyarsızdır
("iphone-15" == "iPhone 15").
"""

from __future__ import annotations

from dataclasses import dataclass

# İhbarlarda en çok işe yarayan, kısa ve okunur bir liste. Playwright çok daha
# fazlasını tanır; buradakiler arayüzde ve tamamlamada önerilenler.
FEATURED = (
    "iPhone 15",
    "iPhone 13",
    "Pixel 7",
    "Galaxy S9+",
    "iPad (gen 7)",
    "Desktop Chrome",
)


@dataclass(frozen=True, slots=True)
class Device:
    name: str
    user_agent: str
    viewport: dict
    device_scale_factor: float
    is_mobile: bool
    has_touch: bool

    def context_options(self) -> dict:
        """Playwright new_context() için cihaza özgü alanlar."""
        return {
            "user_agent": self.user_agent,
            "viewport": dict(self.viewport),
            "device_scale_factor": self.device_scale_factor,
            "is_mobile": self.is_mobile,
            "has_touch": self.has_touch,
        }


def _canonical(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def resolve_device(playwright, name: str) -> Device:
    """Playwright'in cihaz kaydından bir Device üretir.

    `playwright` bir async_playwright örneği (pw.devices sözlüğü). Bilinmeyen
    ad KeyError yerine anlaşılır bir hata verir.
    """
    registry = playwright.devices
    wanted = _canonical(name)
    for key, spec in registry.items():
        if _canonical(key) == wanted:
            return Device(
                name=key,
                user_agent=spec["user_agent"],
                viewport=spec["viewport"],
                device_scale_factor=spec.get("device_scale_factor", 1),
                is_mobile=spec.get("is_mobile", False),
                has_touch=spec.get("has_touch", False),
            )
    raise KeyError(name)


def known_device_names(playwright) -> list[str]:
    return sorted(playwright.devices)
