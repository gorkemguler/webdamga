"""Ortak test ayarları.

Entegrasyon testleri (gerçek Chromium ve ağ gerektirenler) varsayılan olarak
atlanır; çalıştırmak için: WEBDAMGA_INTEGRATION=1 pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/ altındaki yardımcı modüller (proxy_server gibi) doğrudan import edilebilsin.
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def _isolated_signing_keys(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Testler kullanıcının gerçek imza anahtarını ne okusun ne de üzerine yazsın."""
    key_dir = tmp_path_factory.mktemp("keys")
    monkeypatch.setenv("WEBDAMGA_KEY_DIR", str(key_dir))
    # Starlette TestClient varsayılan olarak "Host: testserver" gönderir; host
    # koruması bunu tanısın (yalnızca test yapılandırması).
    monkeypatch.setenv("WEBDAMGA_ALLOWED_HOSTS", "testserver")
    return key_dir
