#!/usr/bin/env bash
# One-command launcher for ExcelLence AI (Linux / macOS)
set -e

cd "$(dirname "$0")/backend"

# Activate venv if it exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
elif [ -d "../.venv" ]; then
  source ../.venv/bin/activate
fi

# Copy .env.example → .env on first run
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo "⚠️  Created backend/.env from .env.example."
  echo "    Please open it and set GROQ_API_KEY before continuing."
  echo "    Get a free key at: https://console.groq.com/keys"
  echo ""
  exit 1
fi

echo "🚀 Starting ExcelLence AI at http://127.0.0.1:8000"
uvicorn main:app --reload --host 127.0.0.1 --port 8000
