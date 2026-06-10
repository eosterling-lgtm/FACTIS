#!/bin/bash
set -e

# Escribir secrets.toml desde variable de entorno (Railway no soporta archivos secrets nativos)
mkdir -p .streamlit
if [ -n "$STREAMLIT_SECRETS" ]; then
    echo "$STREAMLIT_SECRETS" > .streamlit/secrets.toml
    echo "[railway] secrets.toml generado desde STREAMLIT_SECRETS"
fi

# Instalar browsers de Playwright (Chromium para generación de PDFs)
if ! playwright install chromium --with-deps 2>/dev/null; then
    echo "[railway] Playwright install falló — PDFs pueden no generarse"
fi

# Iniciar Streamlit
exec streamlit run solum.py \
    --server.port "${PORT:-8501}" \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection true
