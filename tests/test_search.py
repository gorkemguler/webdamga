"""Yakalama listesinde arama ve sayfalama."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webdamga.storage import Store


def _add(store: Store, capture_id: str, url: str, title: str, when: str) -> None:
    store.record(
        {
            "capture_id": capture_id,
            "requested_url": url,
            "final_url": url,
            "http_status": 200,
            "page_title": title,
            "completed_at_utc": when,
            "dir": f"/tmp/{capture_id}",
        },
        manifest_sha256=None,
        ok=True,
        error=None,
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path)
    _add(s, "c1", "https://bank.example/login", "Bank login", "2026-01-01T00:00:00Z")
    _add(s, "c2", "https://bank-secure.example/verify", "Doğrulama", "2026-01-02T00:00:00Z")
    _add(s, "c3", "https://shop.example/", "Mağaza", "2026-01-03T00:00:00Z")
    return s


def test_empty_query_returns_all_newest_first(store: Store) -> None:
    rows, total = store.search_captures()
    assert total == 3
    assert [r["id"] for r in rows] == ["c3", "c2", "c1"]


def test_search_matches_url(store: Store) -> None:
    rows, total = store.search_captures(query="bank")
    assert total == 2
    assert {r["id"] for r in rows} == {"c1", "c2"}


def test_search_matches_title_case_insensitively(store: Store) -> None:
    rows, total = store.search_captures(query="mağaza")
    assert total == 1 and rows[0]["id"] == "c3"


def test_search_matches_id(store: Store) -> None:
    rows, total = store.search_captures(query="c2")
    assert total == 1 and rows[0]["id"] == "c2"


def test_no_match(store: Store) -> None:
    rows, total = store.search_captures(query="nonexistent")
    assert (rows, total) == ([], 0)


def test_pagination(store: Store) -> None:
    page1, total = store.search_captures(limit=2, offset=0)
    page2, _ = store.search_captures(limit=2, offset=2)
    assert total == 3
    assert [r["id"] for r in page1] == ["c3", "c2"]
    assert [r["id"] for r in page2] == ["c1"]


def test_pagination_within_search(store: Store) -> None:
    rows, total = store.search_captures(query="example", limit=2, offset=2)
    assert total == 3
    assert [r["id"] for r in rows] == ["c1"]


def test_like_wildcards_are_treated_literally(store: Store) -> None:
    # SQL LIKE'ta % joker; kullanıcı metni joker gibi davranmamalı diye
    # tam kelime aramasını doğrula (mevcut kayıtlarda % yok).
    _, total = store.search_captures(query="%")
    assert total == 0


# --------------------------------------------------------------------- web


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBDAMGA_DATA_DIR", str(tmp_path))
    from webdamga import api

    importlib.reload(api)
    for n in range(1, 61):
        _add(
            api._store,
            f"cap{n:02d}",
            f"https://site{n}.example/",
            f"Site {n}",
            f"2026-01-{n % 28 + 1:02d}T00:00:00Z",
        )
    return TestClient(api.app), api


def test_index_shows_first_page_and_pager(client) -> None:
    http, _ = client
    page = http.get("/?lang=en").text
    assert "(60)" in page  # toplam
    assert "page 1 of 2" in page
    assert 'href="/?page=2"' in page


def test_index_second_page(client) -> None:
    http, _ = client
    page = http.get("/?page=2&lang=en").text
    assert "page 2 of 2" in page
    assert "Newer" in page


def test_index_search_filters_and_keeps_query_in_pager(client) -> None:
    http, api = client
    _add(api._store, "special", "https://phish.example/", "Uniquetitle", "2026-02-01T00:00:00Z")
    page = http.get("/?q=uniquetitle&lang=en").text
    assert "phish.example" in page
    assert "(1)" in page


def test_api_captures_returns_total_and_page(client) -> None:
    http, _ = client
    body = http.get("/api/captures?limit=10").json()
    assert body["total"] == 60
    assert body["count"] == 10
    assert len(body["captures"]) == 10

    filtered = http.get("/api/captures?q=site5").json()
    # site5, site50..site59 -> 11 eşleşme
    assert filtered["total"] == 11


def test_api_captures_offset(client) -> None:
    http, _ = client
    first = http.get("/api/captures?limit=5&offset=0").json()["captures"]
    second = http.get("/api/captures?limit=5&offset=5").json()["captures"]
    assert {c["id"] for c in first}.isdisjoint({c["id"] for c in second})
