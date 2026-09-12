"""i18n katmanı için testler."""

from __future__ import annotations

import pytest

from webdamga.i18n import (
    _CATALOG,
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    detect_lang,
    normalize_lang,
    parse_accept_language,
    t,
    translator,
)


def test_catalogs_have_identical_keys() -> None:
    """Her anahtar tüm dillerde tanımlı olmalı, yoksa arayüz yarım çevrilir."""
    reference = set(_CATALOG[DEFAULT_LANG])
    for lang, catalog in _CATALOG.items():
        assert set(catalog) == reference, f"{lang} katalogu eksik/fazla anahtar içeriyor"


def test_no_catalog_value_is_empty() -> None:
    for lang, catalog in _CATALOG.items():
        for key, value in catalog.items():
            assert value.strip(), f"{lang}:{key} boş"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("tr", "tr"),
        ("TR", "tr"),
        ("tr-TR", "tr"),
        ("tr_TR.UTF-8", "tr"),
        ("en-GB", "en"),
        ("de", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_lang(raw: str | None, expected: str | None) -> None:
    assert normalize_lang(raw) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("tr,en;q=0.9", "tr"),
        ("en-US,en;q=0.9,tr;q=0.8", "en"),
        ("de-DE,de;q=0.9,tr;q=0.5", "tr"),
        ("de,fr", None),
        ("tr;q=0", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_accept_language(header: str | None, expected: str | None) -> None:
    assert parse_accept_language(header) == expected


def test_accept_language_respects_quality_order() -> None:
    assert parse_accept_language("tr;q=0.3,en;q=0.9") == "en"
    assert parse_accept_language("tr;q=0.9,en;q=0.3") == "tr"


def test_t_translates_and_formats() -> None:
    assert t("web.index.submit", "tr") == "Yakala"
    assert t("web.index.submit", "en") == "Capture"
    assert t("web.detail.requests.other", "en", count=12) == "12 requests"
    assert t("web.detail.requests.other", "tr", count=12) == "12 istek"


def test_t_falls_back_to_english_then_key() -> None:
    assert t("web.index.submit", "de") == "Capture"  # desteklenmeyen dil
    assert t("web.index.submit", None) == "Capture"
    assert t("bilinmeyen.anahtar", "tr") == "bilinmeyen.anahtar"


def test_t_ignores_bad_format_args() -> None:
    # Eksik format argümanı çıktıyı patlatmamalı.
    assert t("web.detail.requests.other", "en") == "{count} requests"


def test_translator_binds_language() -> None:
    tr = translator("tr")
    assert tr("web.index.submit") == "Yakala"
    assert tr("web.detail.requests", count=3) == "3 istek"


def test_detect_lang_prefers_webdamga_lang(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBDAMGA_LANG", "tr")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert detect_lang() == "tr"


def test_detect_lang_falls_back_to_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBDAMGA_LANG", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert detect_lang() == "tr"


def test_detect_lang_defaults_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("WEBDAMGA_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    assert detect_lang() == DEFAULT_LANG


def test_supported_langs_are_catalogued() -> None:
    assert set(SUPPORTED_LANGS) == set(_CATALOG)


def test_tn_selects_singular_and_plural() -> None:
    from webdamga.i18n import tn

    assert tn("web.detail.requests", 1, "en") == "1 request"
    assert tn("web.detail.requests", 2, "en") == "2 requests"
    assert tn("web.detail.requests", 0, "en") == "0 requests"
    # Türkçede sayıdan sonra çoğul eki yok, iki varyant da aynı.
    assert tn("web.detail.requests", 1, "tr") == "1 istek"
    assert tn("web.detail.requests", 5, "tr") == "5 istek"


def test_translator_handles_plurals() -> None:
    en = translator("en")
    assert en("web.detail.requests", count=1) == "1 request"
    assert en("web.detail.requests", count=3) == "3 requests"
