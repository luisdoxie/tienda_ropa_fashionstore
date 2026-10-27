#!/usr/bin/env bash
# Arranque en Railway: corre las migraciones una sola vez y recién después
# levanta uvicorn. Si uvicorn se levantara con --workers > 1, las
# migraciones NO se repiten por worker porque "alembic upgrade head" corre
# acá, antes del exec, en un único proceso.
set -euo pipefail

echo "Aplicando migraciones de Alembic..."
alembic upgrade head

echo "Iniciando uvicorn en el puerto ${PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --proxy-headers --forwarded-allow-ips "*"
