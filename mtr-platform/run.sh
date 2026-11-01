#!/usr/bin/env bash
# Запуск платформы: установка зависимостей, сборка интерфейса, генерация демо-данных, старт сервера.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
echo "==> Python-зависимости"
python3 -m pip install -q -r backend/requirements.txt
if [ ! -f frontend/dist/index.html ] || [ "${REBUILD:-0}" = "1" ]; then
  echo "==> Сборка интерфейса (React + Vite)"
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi
echo "==> Сервер: http://127.0.0.1:${PORT}  (при первом запуске генерируется демо-набор ~20 с)"
cd backend
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
