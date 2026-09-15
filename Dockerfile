# webdamga: Chromium'u paketli hazır bir imaj.
# Playwright'in resmi imajı doğru sürümde Chromium ve tüm sistem
# bağımlılıklarını (font, kütüphaneler) zaten içerir.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

LABEL org.opencontainers.image.title="webdamga"
LABEL org.opencontainers.image.description="Local web evidence and archiving tool"
LABEL org.opencontainers.image.source="https://github.com/gorkemguler/webdamga"

WORKDIR /app

# openssl RFC 3161 token doğrulaması için; ca-certificates TLS ve TSA kökleri için.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Önce bağımlılıklar (katman önbelleği): pyproject'i kopyalayıp kur.
COPY pyproject.toml README.md ./
COPY webdamga ./webdamga
RUN pip install --no-cache-dir .

# pip'in çözdüğü Playwright sürümüne uygun Chromium'u indir; base imajın
# paketlediği sürümle olası uyumsuzluğu böylece ortadan kaldırıyoruz.
RUN playwright install chromium

# Yakalamalar, karşılaştırmalar, veritabanı ve imza anahtarları burada durur;
# kalıcı olması için bir volume bağlayın.
ENV WEBDAMGA_DATA_DIR=/data
ENV WEBDAMGA_KEY_DIR=/data/keys
VOLUME ["/data"]

EXPOSE 8000

# Konteyner dışından erişilebilsin diye 0.0.0.0'a bağlanır. Konteyneri
# ağa açacaksanız README'deki güvenlik notlarına bakın
# (WEBDAMGA_ALLOWED_HOSTS, önüne reverse proxy vb.).
CMD ["webdamga", "serve", "--host", "0.0.0.0", "--port", "8000"]
