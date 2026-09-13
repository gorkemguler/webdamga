# webdamga

**Yerel web kanıt/arşiv aracı.** Bir URL'nin belirli bir andaki halini kayıt
altına alır ve bunu başkasına verilebilir bir delile dönüştürür: ekran
görüntüleri, sayfanın özgün baytları, yeniden oynatılabilir bir WARC arşivi ve
ağ trafiği; hepsi SHA-256 manifestosuyla mühürlenir, istenirse imzalanır ve
güvenilir bir zamana bağlanır. Bir URL'yi zaman içinde izleyip sayfa
değiştiğinde haber de verebilir. urlscan.io / archive.today mantığında, ama her
şey kendi makinende çalışır.

Tipik kullanım: bir phishing sayfasını ihbar etmeden önce (registrar, hosting,
CERT, banka) sayfanın o anki halini, alıcının sana güvenmeden ve hiçbir şey
kurmadan doğrulayabileceği bir biçimde kayıt altına almak.

*[English README is here](README.md).*

---

## Ekran görüntüleri

| Yakalama başlat / geçmiş | Kanıt + SHA-256 doğrulama |
| --- | --- |
| ![Ana sayfa: yeni yakalama formu ve geçmiş yakalamalar listesi](docs/screenshots/index-tr.png) | ![Yakalama detayı: özet, ekran görüntüsü, dosya listesi ve bütünlük doğrulama sonucu](docs/screenshots/capture-detail-tr.png) |

---

## Bir yakalama ne üretir

Her yakalama `data/captures/<id>/` altına bir klasör yazar:

| Dosya | İçerik |
| --- | --- |
| `screenshot.png` | Tam sayfa ekran görüntüsü |
| `screenshot-viewport.png` | Kaydırmadan görünen kısım |
| `response.html` | Ana belge, **sunucunun gönderdiği baytlarla birebir**, JavaScript öncesi |
| `dom.html` | JavaScript çalıştıktan sonraki **render edilmiş DOM** |
| `archive.warc.gz` | Özgün yanıt baytlarıyla WARC/1.1 arşivi, ReplayWeb.page ya da pywb ile oynatılır |
| `page.mhtml` | Tek dosyalık, kendi kendine yeten arşiv (Chrome'da açılır) |
| `page.pdf` | Sayfanın PDF çıktısı |
| `network.har` | Tüm istek ve yanıtlar, gövdeleriyle |
| `console.log` | Tarayıcı konsolu ve sayfa hataları |
| `metadata.json` | İstenen/nihai URL, yönlendirme zinciri, HTTP durumu ve başlıklar, sunucu IP, TLS sertifikası, ağ yolu ve çıkış IP, sayfa başlığı, favicon, UTC zaman damgaları, User-Agent, zamanlamalar, kaynak özeti, yakalayan makine, imza anahtarı kimliği |
| `manifest.json` | **Yukarıdaki her dosyanın SHA-256 özeti** |
| `manifest.sha256` | `manifest.json`'un kendi özeti |
| `manifest.json.minisig` | İmza anahtarı oluşturduysan manifesto üzerinde Ed25519 imzası |
| `manifest.json.tsr` | İstendiyse RFC 3161 zaman damgası |
| `manifest.json.ots` | İstendiyse OpenTimestamps (Bitcoin) kanıtı |

`webdamga verify <id>` her özeti yeniden hesaplar, imzayı ve zaman damgalarını
kontrol eder.

**Özgün baytlar hakkında.** Playwright'in `response.body()`'si de yazdığı HAR
da metin kaynaklarını sayfanın charset'iyle çözüp UTF-8'e yeniden kodlar. UTF-8
olmayan bir sayfada (ör. windows-1254) bu baytları sessizce değiştirir. webdamga
gövdeleri Chrome DevTools'un `Fetch` alanından okur; böylece `response.html` ve
WARC sunucunun gerçekten gönderdiği baytları korur. `network.har` Playwright'in
kendi çıktısıdır ve bu kısıtı taşımaya devam eder.

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

### Yakalama

```bash
webdamga capture https://ornek.com/giris
webdamga capture https://ornek.com --wait-until networkidle --wait 3 --width 1440
webdamga list
webdamga verify 20260910T142530Z-ornek-com-ab12cd
```

### Web arayüzü

```bash
webdamga serve            # http://127.0.0.1:8000
```

Yakalamalar arka plandaki bir kuyrukta çalışır; bitmelerini beklerken sayfa
kullanılabilir kalır ve kuyruk yeniden başlatmalarda kaybolmaz. Arayüzden
yakalama, gezinme, doğrulama, karşılaştırma, dışa aktarma ve izleme yapılabilir.
`WEBDAMGA_CONCURRENCY` aynı anda kaç yakalama çalışacağını belirler (varsayılan 1).

### Bir yakalamayı kanıt olarak gönderme

```bash
webdamga export 20260910T142530Z-ornek-com-ab12cd
```

ihbara ekleyebileceğin tek bir `.zip` üretir:

```
webdamga-<id>.zip
└── <id>/
    ├── README.txt            bu nedir, webdamga olmadan nasıl doğrulanır
    ├── evidence-report.pdf   okunur özet: URL'ler, TLS, ekran görüntüsü, özetler
    ├── signer.pub            yakalama imzalıysa imzalayanın public key'i
    └── …                     yakalamanın tüm delilleri ve manifestosu
```

Komut paketin kendi SHA-256 özetini yazar; bunu ihbarınla birlikte sakla. Karşı
tarafın bu araca ihtiyacı yok: `README.txt`, paketin içeriğine göre `shasum`,
`minisign`, `openssl ts` ve `ots` komutlarıyla doğrulamayı adım adım anlatır.
Web arayüzünde bu, bir yakalamanın **Kanıt olarak gönder** bölümüdür.

---

## İmzalama: kim mühürledi

Manifesto bir klasörün değişmediğini kanıtlar ama kimin ürettiğini kanıtlamaz:
biri bir dosyayı değiştirip manifestoyu da ona göre yeniden üretebilir. İmza bu
açığı kapatır.

```bash
webdamga keygen           # bir kez; yeni yakalamalar otomatik imzalanır
webdamga pubkey           # yayınlanacak public key'i yazdır
webdamga sign <id>        # eski bir yakalamayı imzala
```

İmzalar **minisign uyumludur** (Ed25519, BLAKE2b ön özetli); herkes standart
araçla doğrulayabilir:

```bash
minisign -Vm manifest.json -P RWS...public-key...
```

İmzanın içindeki güvenilir yorum yakalama kimliğini ve imza zamanını taşır, imzayı
bozmadan değiştirilemez. Gizli anahtar, kuyruktaki ve zamanlanmış yakalamalar
gözetimsiz imzalayabilsin diye `~/.config/webdamga/keys` altında şifrelenmeden
(0600 izniyle) saklanır; başka bir yerde tutmak için `WEBDAMGA_KEY_DIR`. Public
key'ini alıcıların zaten güvendiği bir yerde yayınla; paketin içinden gelen bir
anahtar kendi kendine kefil olamaz.

---

## Güvenilir zaman damgası: ne zaman vardı

İmza kimin mühürlediğini söyler ama zamanı senin saatin söyler. Güvenilir zaman
damgası bunu üçüncü bir tarafa bağlar. Dışarıya yalnızca manifestonun SHA-256
özeti gider, URL ya da içerik asla; bu yüzden isteğe bağlıdır:

```bash
webdamga capture https://ornek.com --timestamp
webdamga timestamp <id>   # mevcut bir yakalamaya ekle
```

İki bağımsız yöntem birlikte kullanılır:

- **RFC 3161**: bir zaman damgası otoritesi özeti ve o anki zamanı imzalar.
  Varsayılan, token'ları işletim sisteminin standart kök sertifikalarıyla
  doğrulanan DigiCert'in herkese açık TSA'sıdır:
  `openssl ts -verify -data manifest.json -in manifest.json.tsr -CAfile /etc/ssl/cert.pem`.
  `WEBDAMGA_TSA_URL` ya da `--tsa` ile değiştirilebilir.
- **OpenTimestamps**: özet birkaç takvim sunucusuna gönderilir ve Bitcoin blok
  zincirine bağlanır. Güvenilecek tek bir kurum yoktur ama onay birkaç saat
  sürer; kanıt sonradan resmi istemciyle yükseltilip doğrulanır (`ots upgrade`,
  `ots verify`).

`webdamga verify` ikisini de mevcut manifestoya karşı kontrol eder, `openssl`
varsa TSA imzasını ve sertifika zincirini de doğrular. Doğrulayamazsa başarılı
gibi göstermez, bunu açıkça söyler.

---

## Proxy ya da Tor üzerinden yakalama

Phishing sayfaları ziyaretçinin IP'sine ya da ülkesine göre sık sık farklı
içerik gösterir. Bir yakalama proxy üzerinden yapılabilir:

```bash
webdamga capture https://ornek.com --tor
webdamga capture https://ornek.com --proxy socks5://127.0.0.1:1080
webdamga capture https://ornek.com --via de --record-egress
webdamga proxies
```

Adlandırılmış profiller `data/proxies.json` içindedir:

```json
{ "de": "socks5://10.0.0.2:1080", "us": "http://kullanici:parola@proxy.ornek:3128" }
```

Ülke seçmek bir profil seçmek demektir; çıkış ülkesini proxy'n belirler, webdamga
ülke IP'si sağlamaz. `tor` profili her zaman vardır. `--record-egress`,
yakalamanın gerçekten hangi IP'den çıktığını kaydeder (check.torproject.org ile,
delillere karışmasın diye ayrı bir context'te). Proxy kimlik bilgileri metadata'ya,
raporlara ya da loglara asla yazılmaz. Chromium kimlikli SOCKS proxy'lerini
desteklemediği için bunlar kimliksiz kullanılmak yerine reddedilir. Web arayüzü
yalnızca adlandırılmış profilleri sunar, serbest proxy adresi kabul etmez.

---

## İki yakalamayı karşılaştırma

```bash
webdamga diff <eski-id> <yeni-id>
webdamga diff <eski-id> <yeni-id> --json
```

Karşılaştırma katman katman yapılır ve bir yargıyla (değişiklik yok, küçük,
önemli) sade gerekçelerle biter:

- **ekran görüntüsü**: değişen piksel oranı, değişen bölgeler ve işaretli bir fark görseli
- **görünür metin**: satır bazında fark ve benzerlik
- **formlar**: en güçlü phishing sinyalleri ayrıca işaretlenir; bir parola
  alanının belirmesi ya da formun artık başka bir siteye göndermesi gibi
- HAR'dan **bağlanılan sunucular ve scriptler**
- **metadata**: nihai URL (başka sunucuya taşınmak önemlidir), HTTP durumu,
  başlık, sunucu IP, TLS sertifikası

Web arayüzünde bir yakalamanın sayfası aynı sunucunun diğer yakalamalarını
karşılaştırma için listeler. Sonuçlar `data/diffs/` altına yazılır; mühürlü
yakalama klasörlerine dokunulmaz.

---

## Bir URL'yi zaman içinde izleme

```bash
webdamga monitor add https://ornek.com/giris --every 60 --label "Banka taklidi"
webdamga monitor list
webdamga monitor pause 1
webdamga monitor run      # web arayüzü olmadan zamanlayıcı
```

Her tur, izleyicinin ağ yolu ve zaman damgası ayarlarıyla yapılan normal bir
yakalamadır ve son başarılı yakalamayla karşılaştırılır. Başarısız bir tur (ör.
alan adı artık çözülmüyor) kaydedilir ama tabanı değiştirmez; sonraki başarılı
yakalama yine son sağlam hâlle karşılaştırılır. Zamanlayıcı `webdamga serve`
içinde ya da tek başına `webdamga monitor run` ile çalışır. **İzleme** sayfası
her izleyicinin turlarını, karşılaştırmaya bağlanan değişiklik rozetleriyle
gösterir. Bir izleyiciyi silmek yakalamalarını silmez.

---

## Dil

CLI ve web arayüzü **Türkçe ve İngilizce** konuşur. Varsayılan İngilizce;
ortamın ya da tarayıcın Türkçe istiyorsa Türkçeye geçer.

| Arayüz | Dil nasıl seçilir (ilk eşleşen kazanır) |
| --- | --- |
| CLI | `--lang` → `WEBDAMGA_LANG` → sistem locale (`LC_ALL` / `LANG`) → İngilizce |
| Web | `?lang=` → `webdamga_lang` çerezi → `Accept-Language` → İngilizce |

---

## JSON API

| Uç | Açıklama |
| --- | --- |
| `GET /api/captures`, `GET /api/captures/{id}` | Yakalama indeksi, bir yakalamanın metadata'sı |
| `POST /api/jobs`, `GET /api/jobs`, `GET/DELETE /api/jobs/{id}` | Yakalamayı kuyruğa ekle, listele, incele, iptal et |
| `GET /captures/{id}/verify` | Bütünlük, imza ve zaman damgası kontrolü |
| `POST /captures/{id}/timestamp` | Mevcut bir yakalamayı zaman damgala |
| `GET /captures/{id}/export.zip` | Kanıt paketi; SHA-256 özeti `x-webdamga-package-sha256` başlığında |
| `GET /captures/{id}/report.pdf` | PDF kanıt raporu |
| `GET /captures/{id}/files/{ad}` | Tek bir delil (yalnızca manifestodaki adlar) |
| `GET /api/diff?a=&b=` | İki yakalamayı karşılaştır |
| `GET/POST /api/monitors`, `GET/PATCH/DELETE /api/monitors/{id}`, `POST /api/monitors/{id}/run` | İzleyiciler |
| `GET /api/routes` | Kullanılabilir proxy profilleri |

---

## Yapılandırma

| Değişken | Varsayılan | Amaç |
| --- | --- | --- |
| `WEBDAMGA_DATA_DIR` | `./data` | Yakalamalar, karşılaştırmalar, veritabanı, `proxies.json` |
| `WEBDAMGA_LANG` | sistem locale | Arayüz dili |
| `WEBDAMGA_CONCURRENCY` | `1` | Aynı anda çalışan yakalama sayısı |
| `WEBDAMGA_KEY_DIR` | `~/.config/webdamga/keys` | İmza anahtarının yeri |
| `WEBDAMGA_TSA_URL` | DigiCert | RFC 3161 zaman damgası otoritesi |
| `WEBDAMGA_TSA_CA` | sistem paketi | TSA token'larını doğrulamak için CA dosyası |
| `WEBDAMGA_OTS_CALENDARS` | herkese açık havuzlar | Virgülle ayrılmış OpenTimestamps takvimleri |

---

## Testler

```bash
pip install -e ".[dev]"
pytest
WEBDAMGA_INTEGRATION=1 pytest   # Chromium ve ağ erişimi gerektiren testleri de çalıştırır
```

Biçimler yalnızca webdamga'nın kendisine karşı değil, bağımsız uygulamalara karşı
sınanır: WARC dosyaları warcio'nun digest doğrulayıcısından geçer, imzalar gerçek
minisign çıktısıyla, zaman damgası token'ları gerçek DigiCert ve FreeTSA
yanıtlarıyla, OpenTimestamps kanıtları resmi istemciyle karşılaştırılır.

---

## Yol haritası

Tamamlananlar:

- [x] Yakalama durumunu gösteren arka plan kuyruğu
- [x] Adlandırılmış profillerle proxy ya da Tor üzerinden yakalama
- [x] Özgün baytlarla WARC çıktısı (Wayback / pywb / ReplayWeb.page)
- [x] Manifesto imzalama (minisign uyumlu)
- [x] RFC 3161 ve OpenTimestamps güvenilir zaman damgası
- [x] İki yakalamayı karşılaştırma (görsel, metin, formlar, sunucular, metadata)
- [x] Bir URL'yi zamanlanmış aralıklarla izleme
- [x] PDF kanıt raporu ve gönderilebilir `.zip` paketi

Sıradakiler:

- [ ] Tek dosyada oynatma için WACZ paketleme
- [ ] İzlenen sayfa değişince bildirim (webhook, e-posta)
- [ ] Arayüzü localhost dışında çalıştırmak için kimlik doğrulama
- [ ] Chromium'un yanında Firefox ve WebKit ile yakalama

---

## Yasal / etik not

`webdamga` yalnızca **yetkili ve yasal** amaçlarla (kendi varlıklarının takibi,
phishing/marka istismarı ihbarı, olay müdahalesi, akademik araştırma) kullanılmak
üzere tasarlanmıştır. Yakaladığınız sitelere erişimde ve topladığınız veriyi
saklama/paylaşmada geçerli mevzuata ve hedef sitenin kullanım şartlarına uymak
kullanıcının sorumluluğundadır.

## Lisans

MIT, bkz. [LICENSE](LICENSE).
