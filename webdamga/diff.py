"""İki yakalamayı karşılaştırma.

Aynı URL'nin iki yakalaması arasında neyin değiştiğini katman katman çıkarır:

görsel      ekran görüntülerinde değişen piksellerin oranı ve değişen bölgeler
metin       sayfanın görünür metni (script/style hariç), satır bazında fark
formlar     form hedefleri, yöntemler ve alanlar; parola alanı ve formun başka
            bir alan adına post etmeye başlaması ayrıca işaretlenir
kaynaklar   HAR'daki istek sunucuları ve script adresleri
metadata    nihai URL, HTTP durumu, başlık, sunucu IP, TLS sertifikası, ...

Sonunda "aynı / küçük / önemli" şeklinde bir yargı ve gerekçe listesi üretir.
Yargı kuralları kasten sade ve açıklanabilir tutuldu; eşikler aşağıda sabit.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from PIL import Image, ImageChops, ImageDraw

PIXEL_THRESHOLD = 40  # kanal farkı bundan küçükse kenar yumuşatma gürültüsü sayılır
GRID = 24  # değişen bölgeleri bulmak için hücre boyu (px)
VISUAL_MINOR = 0.001  # bu oranın altı "görsel olarak aynı"
VISUAL_MAJOR = 0.15
TEXT_MAJOR = 0.85  # metin benzerliği bunun altına düşerse önemli
MAX_TEXT_LINES = 5000
MAX_DIFF_LINES = 400

_SKIP_TEXT = {"script", "style", "noscript", "template", "svg", "head"}
_BLOCK = {
    "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section", "article",
    "header", "footer", "nav", "main", "aside", "h1", "h2", "h3", "h4", "h5", "h6",
    "form", "label", "button", "option", "select", "textarea", "title", "blockquote", "pre",
}  # fmt: skip


# ========================================================================= HTML


@dataclass
class _Form:
    action: str
    method: str
    fields: list[tuple[str, str]] = field(default_factory=list)  # (type, name)

    def signature(self) -> str:
        fields = ",".join(f"{t}:{n}" for t, n in sorted(self.fields))
        return f"{self.method} {self.action} [{fields}]"

    @property
    def has_password(self) -> bool:
        return any(t == "password" for t, _ in self.fields)


class _PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.chunks: list[str] = []
        self.forms: list[_Form] = []
        self.loose_fields: list[tuple[str, str]] = []  # form dışındaki alanlar
        self._skip = 0
        self._form: _Form | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k: (v or "") for k, v in attrs}
        if tag in _SKIP_TEXT:
            self._skip += 1
        if tag in _BLOCK:
            self.chunks.append("\n")
        if tag == "form":
            action = values.get("action", "").strip()
            resolved = urljoin(self.base_url, action) if action else self.base_url
            self._form = _Form(_strip_fragment(resolved), values.get("method", "get").lower() or "get")
            self.forms.append(self._form)
        elif tag in ("input", "select", "textarea"):
            if tag == "input":
                kind = (values.get("type") or "text").lower()
                if kind in ("submit", "button", "reset", "image"):
                    return  # veri taşımayan düğmeler formun kimliğini değiştirmez
            else:
                kind = tag
            name = values.get("name") or values.get("id") or ""
            target = self._form.fields if self._form is not None else self.loose_fields
            target.append((kind, name))

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TEXT and self._skip:
            self._skip -= 1
        if tag in _BLOCK:
            self.chunks.append("\n")
        if tag == "form":
            self._form = None

    def handle_data(self, data: str) -> None:
        if not self._skip:
            # Metin içindeki satır sonu HTML'de yalnızca boşluktur; satırları
            # yalnızca blok etiketleri böler.
            self.chunks.append(re.sub(r"\s+", " ", data))


def _strip_fragment(url: str) -> str:
    return url.split("#", 1)[0]


@dataclass
class PageContent:
    lines: list[str]
    forms: list[_Form]
    loose_fields: list[tuple[str, str]]

    @property
    def has_password(self) -> bool:
        return any(f.has_password for f in self.forms) or any(t == "password" for t, _ in self.loose_fields)


def parse_page(html: str, base_url: str) -> PageContent:
    parser = _PageParser(base_url)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001, S110 - bozuk HTML'de elde edilebilen kadarı yeter
        pass
    text = "".join(parser.chunks)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line][:MAX_TEXT_LINES]
    return PageContent(lines, parser.forms, parser.loose_fields)


# ======================================================================== görsel


def _load_rgb(path: Path) -> Image.Image:
    with Image.open(path) as img:
        return img.convert("RGB")


def _connected_boxes(cells: set[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """Komşu değişen hücreleri birleştirip (x0, y0, x1, y1) hücre kutuları döner."""
    boxes, seen = [], set()
    for start in sorted(cells):
        if start in seen:
            continue
        stack, xs, ys = [start], [], []
        seen.add(start)
        while stack:
            cx, cy = stack.pop()
            xs.append(cx)
            ys.append(cy)
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (nx, ny) in cells and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        boxes.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1))
    return boxes


def compare_images(path_a: Path, path_b: Path, out_path: Path | None = None) -> dict:
    a, b = _load_rgb(path_a), _load_rgb(path_b)
    width, height = max(a.width, b.width), max(a.height, b.height)
    canvas_a = Image.new("RGB", (width, height), "white")
    canvas_b = Image.new("RGB", (width, height), "white")
    canvas_a.paste(a)
    canvas_b.paste(b)

    diff = ImageChops.difference(canvas_a, canvas_b)
    r, g, bl = diff.split()
    strongest = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    mask = strongest.point(lambda v: 255 if v > PIXEL_THRESHOLD else 0)
    changed = mask.histogram()[255]
    total = width * height
    ratio = changed / total if total else 0.0

    grid = mask.resize((max(1, width // GRID), max(1, height // GRID)), Image.Resampling.BOX)
    cells = {(x, y) for y in range(grid.height) for x in range(grid.width) if grid.getpixel((x, y)) > 0}
    regions = [
        {"x": x0 * GRID, "y": y0 * GRID, "width": (x1 - x0) * GRID, "height": (y1 - y0) * GRID}
        for x0, y0, x1, y1 in sorted(_connected_boxes(cells), key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    ][:20]

    if out_path is not None:
        # B görüntüsü soluk, değişen pikseller kırmızı, bölgeler çerçeveli.
        overlay = Image.blend(canvas_b, Image.new("RGB", (width, height), "black"), 0.55)
        overlay.paste(Image.new("RGB", (width, height), (255, 60, 60)), mask=mask)
        draw = ImageDraw.Draw(overlay)
        for region in regions:
            x, y, w, h = region["x"], region["y"], region["width"], region["height"]
            draw.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 200, 0), width=3)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(out_path, optimize=True)

    return {
        "changed_ratio": round(ratio, 6),
        "changed_pixels": changed,
        "size_a": [a.width, a.height],
        "size_b": [b.width, b.height],
        "regions": regions,
        "image": out_path.name if out_path else None,
    }


# ===================================================================== kaynaklar


def _har_summary(har_path: Path) -> dict:
    hosts: set[str] = set()
    scripts: set[str] = set()
    if not har_path.is_file():
        return {"hosts": hosts, "scripts": scripts, "available": False}
    try:
        entries = json.loads(har_path.read_text(encoding="utf-8")).get("log", {}).get("entries", [])
    except (OSError, ValueError):
        return {"hosts": hosts, "scripts": scripts, "available": False}
    for entry in entries:
        url = entry.get("request", {}).get("url", "")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            continue
        if parts.hostname:
            hosts.add(parts.hostname)
        if entry.get("_resourceType") == "script":
            scripts.add(f"{parts.scheme}://{parts.netloc}{parts.path}")
    return {"hosts": hosts, "scripts": scripts, "available": True}


# ====================================================================== metadata


def _dig(meta: dict, dotted: str):
    value = meta
    for key in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


_META_FIELDS = (
    "final_url",
    "http_status",
    "page_title",
    "remote_address.ipAddress",
    "tls.issuer",
    "tls.subjectName",
    "tls.validFrom_iso",
    "tls.validTo_iso",
    "favicon_url",
    "response_headers.server",
    "response_headers.content-type",
    "response_headers.x-frame-options",
    "response_headers.content-security-policy",
)


def _host(url: str | None) -> str | None:
    return urlsplit(url).hostname if url else None


# ========================================================================= ana


def _summary(meta: dict, capture_dir: Path) -> dict:
    return {
        "capture_id": meta.get("capture_id", capture_dir.name),
        "requested_url": meta.get("requested_url"),
        "final_url": meta.get("final_url"),
        "completed_at_utc": meta.get("completed_at_utc"),
        "http_status": meta.get("http_status"),
    }


def _pick_screenshot(capture_dir: Path) -> Path | None:
    for name in ("screenshot-viewport.png", "screenshot.png"):
        if (capture_dir / name).is_file():
            return capture_dir / name
    return None


def compare_captures(dir_a: Path, dir_b: Path, out_dir: Path | None = None) -> dict:
    """`dir_a` (eski) ile `dir_b` (yeni) yakalamalarını karşılaştırır."""
    dir_a, dir_b = Path(dir_a), Path(dir_b)
    meta_a = json.loads((dir_a / "metadata.json").read_text(encoding="utf-8"))
    meta_b = json.loads((dir_b / "metadata.json").read_text(encoding="utf-8"))
    reasons: list[dict] = []

    def reason(code: str, severity: str, **params) -> None:
        reasons.append({"code": code, "severity": severity, "params": params})

    # ---- metadata
    metadata = []
    for dotted in _META_FIELDS:
        a, b = _dig(meta_a, dotted), _dig(meta_b, dotted)
        if a != b:
            metadata.append({"field": dotted, "a": a, "b": b})
    changed = {m["field"] for m in metadata}
    if _host(meta_a.get("final_url")) != _host(meta_b.get("final_url")):
        reason("final_host", "major", a=_host(meta_a.get("final_url")), b=_host(meta_b.get("final_url")))
    elif "final_url" in changed:
        reason("final_url", "minor", a=meta_a.get("final_url"), b=meta_b.get("final_url"))
    status_a, status_b = meta_a.get("http_status"), meta_b.get("http_status")
    if status_a != status_b:
        same_class = status_a and status_b and status_a // 100 == status_b // 100
        reason("http_status", "minor" if same_class else "major", a=status_a, b=status_b)
    if "page_title" in changed:
        reason("page_title", "minor", a=meta_a.get("page_title"), b=meta_b.get("page_title"))
    if "remote_address.ipAddress" in changed:
        reason(
            "server_ip",
            "minor",
            a=_dig(meta_a, "remote_address.ipAddress"),
            b=_dig(meta_b, "remote_address.ipAddress"),
        )
    if changed & {"tls.issuer", "tls.subjectName"}:
        reason("tls_certificate", "minor", a=_dig(meta_a, "tls.issuer"), b=_dig(meta_b, "tls.issuer"))

    # ---- görsel
    visual = None
    shot_a, shot_b = _pick_screenshot(dir_a), _pick_screenshot(dir_b)
    if shot_a and shot_b:
        visual = compare_images(shot_a, shot_b, (out_dir / "visual-diff.png") if out_dir else None)
        ratio = visual["changed_ratio"]
        if ratio >= VISUAL_MAJOR:
            reason("visual", "major", percent=round(ratio * 100, 1))
        elif ratio >= VISUAL_MINOR:
            reason("visual", "minor", percent=round(ratio * 100, 2))

    # ---- metin ve formlar
    def page(dir_: Path, meta: dict) -> PageContent:
        dom = dir_ / "dom.html"
        html = dom.read_text(encoding="utf-8", errors="replace") if dom.is_file() else ""
        return parse_page(html, meta.get("final_url") or meta.get("requested_url") or "")

    page_a, page_b = page(dir_a, meta_a), page(dir_b, meta_b)
    matcher = difflib.SequenceMatcher(None, page_a.lines, page_b.lines, autojunk=False)
    similarity = matcher.ratio() if (page_a.lines or page_b.lines) else 1.0
    unified = list(difflib.unified_diff(page_a.lines, page_b.lines, "a", "b", lineterm="", n=1))[2:]
    added = sum(1 for line in unified if line.startswith("+"))
    removed = sum(1 for line in unified if line.startswith("-"))
    text = {
        "similarity": round(similarity, 4),
        "lines_a": len(page_a.lines),
        "lines_b": len(page_b.lines),
        "added": added,
        "removed": removed,
        "diff": unified[:MAX_DIFF_LINES],
        "truncated": len(unified) > MAX_DIFF_LINES,
    }
    if similarity < TEXT_MAJOR:
        reason("text", "major", percent=round(similarity * 100, 1))
    elif added or removed:
        reason("text", "minor", added=added, removed=removed)

    forms_a = {f.signature(): f for f in page_a.forms}
    forms_b = {f.signature(): f for f in page_b.forms}
    forms = {
        "count_a": len(page_a.forms),
        "count_b": len(page_b.forms),
        "added": [_form_dict(forms_b[s]) for s in forms_b.keys() - forms_a.keys()],
        "removed": [_form_dict(forms_a[s]) for s in forms_a.keys() - forms_b.keys()],
        "password_a": page_a.has_password,
        "password_b": page_b.has_password,
    }
    if page_b.has_password and not page_a.has_password:
        reason("password_field_added", "major")
    elif page_a.has_password and not page_b.has_password:
        reason("password_field_removed", "major")
    hosts_a = {_host(f.action) for f in page_a.forms} - {None}
    new_targets = sorted(
        {_host(f.action) for f in page_b.forms} - {None} - hosts_a - {_host(meta_b.get("final_url"))}
    )
    if new_targets:
        reason("form_target_host", "major", hosts=", ".join(new_targets))
    if forms["added"] or forms["removed"]:
        reason("forms_changed", "major", added=len(forms["added"]), removed=len(forms["removed"]))

    # ---- kaynaklar
    har_a, har_b = _har_summary(dir_a / "network.har"), _har_summary(dir_b / "network.har")
    resources = {
        "available": har_a["available"] and har_b["available"],
        "hosts_added": sorted(har_b["hosts"] - har_a["hosts"]),
        "hosts_removed": sorted(har_a["hosts"] - har_b["hosts"]),
        "scripts_added": sorted(har_b["scripts"] - har_a["scripts"]),
        "scripts_removed": sorted(har_a["scripts"] - har_b["scripts"]),
    }
    if resources["available"] and (resources["hosts_added"] or resources["hosts_removed"]):
        reason("hosts", "minor", added=len(resources["hosts_added"]), removed=len(resources["hosts_removed"]))

    severities = {r["severity"] for r in reasons}
    verdict = "major" if "major" in severities else "minor" if reasons else "identical"
    result = {
        "a": _summary(meta_a, dir_a),
        "b": _summary(meta_b, dir_b),
        "verdict": verdict,
        "reasons": reasons,
        "metadata": metadata,
        "visual": visual,
        "text": text,
        "forms": forms,
        "resources": resources,
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "diff.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _form_dict(form: _Form) -> dict:
    return {
        "action": form.action,
        "method": form.method,
        "fields": [{"type": t, "name": n} for t, n in form.fields],
        "has_password": form.has_password,
    }


def diff_dir(data_dir: Path, id_a: str, id_b: str) -> Path:
    return Path(data_dir) / "diffs" / f"{id_a}__{id_b}"


def describe_reason(reason: dict, lang: str) -> str:
    """Gerekçeyi seçilen dilde tek cümleye çevirir."""
    from .i18n import t

    specific = f"diff.reason.{reason['code']}.{reason['severity']}"
    text = t(specific, lang, **reason["params"])
    if text == specific:
        text = t(f"diff.reason.{reason['code']}", lang, **reason["params"])
    return text
