#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
python3.12 -m venv .venv || python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements-core.txt
pip install -r requirements-qwen.txt
pip install -e .
[[ -f .env ]] || cp .env.example .env
echo "Установка завершена. Запуск: ./start_linux.sh"
