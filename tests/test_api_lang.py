"""Web arayüzünün dil seçimi davranışı."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webdamga.i18n import LANG_COOKIE


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """API'yi izole bir veri klasörüyle yeniden yükler."""
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    from webdamga import api

    importlib.reload(api)
    return TestClient(api.app)


def test_defaults_to_english(client: TestClient) -> None:
    page = client.get("/").text
    assert "New capture" in page
    assert "Yeni yakalama" not in page


def test_accept_language_selects_turkish(client: TestClient) -> None:
    page = client.get("/", headers={"accept-language": "tr-TR,tr;q=0.9,en;q=0.5"}).text
    assert "Yeni yakalama" in page


def test_accept_language_ignores_unsupported(client: TestClient) -> None:
    page = client.get("/", headers={"accept-language": "de-DE,de;q=0.9"}).text
    assert "New capture" in page


def test_query_param_overrides_and_sets_cookie(client: TestClient) -> None:
    response = client.get("/?lang=tr")
    assert "Yeni yakalama" in response.text
    assert response.cookies.get(LANG_COOKIE) == "tr"


def test_cookie_is_remembered(client: TestClient) -> None:
    client.get("/?lang=tr")
    # Çerez client'ta saklandı, sonraki istekte dil korunmalı.
    assert "Yeni yakalama" in client.get("/").text


def test_query_param_beats_cookie(client: TestClient) -> None:
    client.get("/?lang=tr")
    assert "New capture" in client.get("/?lang=en").text


def test_unsupported_query_param_falls_back(client: TestClient) -> None:
    response = client.get("/?lang=de")
    assert "New capture" in response.text
    assert LANG_COOKIE not in response.cookies


def test_language_switch_links_are_rendered(client: TestClient) -> None:
    page = client.get("/").text
    assert 'href="?lang=tr"' in page
    assert 'href="?lang=en"' in page


def test_html_lang_attribute_follows_selection(client: TestClient) -> None:
    assert '<html lang="tr">' in client.get("/?lang=tr").text
    assert '<html lang="en">' in client.get("/?lang=en").text
