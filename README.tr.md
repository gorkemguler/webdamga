# webdamga

**Yerel web kanıt/arşiv aracı.** Bir URL'nin belirli bir andaki halini (ekran
görüntüsü, ham + render edilmiş HTML, ağ trafiği, MHTML arşivi, PDF ve konsol
kayıtlarıyla birlikte) kayıt altına alır ve tüm çıktıları **SHA-256 bütünlük
manifestosu** ile mühürler. urlscan.io / archive.today mantığında, ama elde
tutulabilir delil üretmeye odaklı ve tamamen `localhost`'ta çalışır.

Tipik kullanım: bir phishing sayfasını ihbar etmeden önce (registrar, hosting,
CERT, banka) sayfanın o anki halini oynanmamış biçimde kayıt altına almak.

*[English README is here](README.md).*

---

## Ekran görüntüleri

| Yakalama başlat / geçmiş | Kanıt + SHA-256 doğrulama |
| --- | --- |
| ![Ana sayfa: yeni yakalama formu ve geçmiş yakalamalar listesi](docs/screenshots/index.png) | ![Yakalama detayı: özet, ekran görüntüsü, dosya listesi ve bütünlük doğrulama sonucu](docs/screenshots/capture-detail.png) |

---

## Ne üretir

Her yakalama `data/captures/<id>/` altında şu dosyaları oluşturur:

| Dosya | İçerik |
| --- | --- |
| `screenshot.png` | Tam sayfa ekran görüntüsü |
| `screenshot-viewport.png` | Görünür alan (ekran üstü) |
| `response.html` | Ana belgenin **ham HTTP yanıt gövdesi** (JS öncesi) |
| `dom.html` | JS çalıştıktan sonra **render edilmiş DOM** |
| `page.mhtml` | Tek dosyalık, kendi kendine yeten arşiv (Chrome'da açılır) |
| `page.pdf` | Yazdır → PDF |
| `network.har` | Tüm istek/yanıtlar, gövdeler gömülü |
| `console.log` | Konsol mesajları + sayfa hataları |
| `metadata.json` | İstenen/nihai URL, yönlendirme zinciri, HTTP durumu ve başlıklar, sunucu IP'si, TLS sertifikası, sayfa başlığı, favicon, UTC zaman damgaları, User-Agent, gezinme zamanlamaları, kaynak özeti, yakalayan makine |
| `manifest.json` | Yukarıdaki **her dosyanın SHA-256 özeti** + araç sürümü |
| `manifest.sha256` | `manifest.json`'un kendi özeti (sidecar) |

`manifest.json` + `manifest.sha256`, klasörün sonradan değiştirilmediğini
göstermenin çıpasıdır. `webdamga verify <id>` her iki katmanı da yeniden
hesaplar.

---

## Kurulum

Python **3.11+** gerekir.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

> `playwright install chromium` bir kez Chromium'u (~150 MB) indirir.

---

## Kullanım

### CLI

```bash
# Tek bir URL yakala
webdamga capture https://ornek.com/giris

# Seçeneklerle
webdamga capture https://ornek.com --wait-until networkidle --wait 3 --width 1440

# Son yakalamalar
webdamga list

# Bir yakalamanın bütünlüğünü doğrula
webdamga verify 20260910T142530Z-ornek-com-ab12cd
```

`webdamga capture` çıkışta yakalama `id`'sini, nihai URL'yi, HTTP durumunu,
sunucu IP'sini, TLS bilgisini ve `manifest.sha256` özetini yazar. Bu özeti
ayrı bir yere (e-posta, ihbar formu, not) kaydetmek, delili daha sonra
"bu klasör o gün buydu" diye kanıtlamayı sağlar.

### Web arayüzü

```bash
webdamga serve            # http://127.0.0.1:8000
```

- URL gir → yakala
- Geçmiş yakalamaları gez
- Ekran görüntüsü, metadata, yönlendirme zinciri, dosya listesi + SHA-256
- **Bütünlüğü doğrula** düğmesi

### JSON API

| Uç | Açıklama |
| --- | --- |
| `GET /api/captures` | Yakalama indeksi |
| `GET /api/captures/{id}` | Bir yakalamanın `metadata.json`'u |
| `GET /captures/{id}/verify` | Bütünlük doğrulama sonucu (JSON) |
| `GET /captures/{id}/files/{ad}` | Yakalama dosyasını indir (yalnızca manifestodaki adlar) |

---

## Veri klasörü

Varsayılan: çalışılan dizinde `./data`. `--data-dir` ile ya da
`WEBDAMGA_DATA_DIR` ortam değişkeniyle değiştirilebilir. İndeks
`data/webdamga.db` (SQLite) dosyasında tutulur. `data/` klasörü `.gitignore`
kapsamındadır.

---

## Testler

```bash
pip install -e ".[dev]"
pytest
```

---

## Yol haritası

- [ ] WARC çıktısı (Wayback / replay uyumlu)
- [ ] RFC 3161 / OpenTimestamps güvenilir zaman damgası
- [ ] Manifesto imzalama (minisign / age / PGP)
- [ ] Tor / proxy üzerinden yakalama, ülke seçimi
- [ ] Aynı URL'nin iki yakalamasını karşılaştırma (görsel + DOM diff)
- [ ] Bir URL'yi zamanlanmış aralıklarla izleme
- [ ] Tek sayfalık PDF delil raporu (ekran görüntüsü + hash'ler + metadata)
- [ ] Arka planda kuyruk + yakalama durumu (arayüzü kilitlememek için)

---

## Yasal / etik not

`webdamga` yalnızca **yetkili ve yasal** amaçlarla (kendi varlıklarının
takibi, phishing/marka istismarı ihbarı, olay müdahalesi, akademik araştırma)
kullanılmak üzere tasarlanmıştır. Yakaladığınız sitelere erişimde ve topladığınız
veriyi saklama/paylaşmada geçerli mevzuata ve hedef sitenin kullanım şartlarına
uymak kullanıcının sorumluluğundadır.

## Lisans

MIT, bkz. [LICENSE](LICENSE).
