#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Load prod env (DJANGO_SETTINGS_MODULE, secrets, DB path) for the manage.py commands.
set -a
# shellcheck disable=SC1091
source .env
set +a

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Syncing dependencies"
uv sync --frozen

echo "==> Applying migrations"
uv run manage.py migrate --noinput

echo "==> Collecting static files"
uv run manage.py collectstatic --noinput

echo "==> Restarting service"
sudo systemctl restart papernews

echo "==> Done"
