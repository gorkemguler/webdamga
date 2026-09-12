"""Ortak test ayarları.

Entegrasyon testleri (gerçek Chromium ve ağ gerektirenler) varsayılan olarak
atlanır; çalıştırmak için: WEBDAMGA_INTEGRATION=1 pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

# tests/ altındaki yardımcı modüller (proxy_server gibi) doğrudan import edilebilsin.
sys.path.insert(0, str(Path(__file__).parent))
