#!/usr/bin/env bash
# AgentOTel prod deploy script — run on 47.237.100.232 as user `admin`.
# Idempotent. No docker.
#
#   Usage:  bash deploy/deploy-prod.sh
#   Env:    reads ~/agentotel/.env (must exist, copy from .env.prod.example first)
#
# What it does:
#   1. git pull on prod checkout (~/agentotel)
#   2. Ensure venv at ~/agentotel/.venv, pip install -r requirements.txt
#   3. Install/refresh systemd unit (needs sudo, prompts once) — first run only
#   4. Install/refresh nginx site conf (needs sudo, prompts once) — first run only
#   5. Reload nginx, restart backend
#   6. Smoke test 127.0.0.1:8091 and 127.0.0.1:8088/api/
#   7. Write version.txt

set -euo pipefail

REPO="${REPO:-$HOME/agentotel}"
VENV="$REPO/.venv"
SYSTEMD_UNIT="/etc/systemd/system/agentotel-backend.service"
NGINX_SITE="/etc/nginx/conf.d/agentotel.conf"

cd "$REPO"

echo "==> [1/7] git pull"
git fetch --all --prune
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git pull --ff-only origin "$BRANCH"
COMMIT="$(git rev-parse --short HEAD)"

echo "==> [2/7] venv + pip"
# Python 3.11 required — 3.6 (system default on alinux3) fails on `from __future__ import annotations` + cryptography build deps.
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "!! $PYTHON_BIN not found. Install with: sudo dnf install -y python3.11 python3.11-pip"
  exit 1
fi
if [[ ! -d "$VENV" ]]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -r "$REPO/server/backend-api/requirements.txt" --quiet

echo "==> [3/7] systemd units"
# Ensure nginx can traverse into /home/admin to reach front/ (nginx runs as user 'nginx').
# `o+x` on $HOME only allows path traversal, NOT directory listing — safe for a single-admin box.
sudo chmod o+x "$HOME"

for unit_src in "$REPO"/deploy/systemd/*.service; do
  unit_name="$(basename "$unit_src")"
  unit_dst="/etc/systemd/system/$unit_name"
  if ! sudo -n cmp -s "$unit_src" "$unit_dst" 2>/dev/null; then
    sudo cp "$unit_src" "$unit_dst"
    sudo systemctl daemon-reload
    sudo systemctl enable "$unit_name"
    echo "    $unit_name refreshed + enabled"
  else
    echo "    $unit_name unchanged"
  fi
done

echo "==> [4/7] nginx site"
if ! sudo -n cmp -s "$REPO/deploy/nginx/agentotel.conf" "$NGINX_SITE" 2>/dev/null; then
  sudo cp "$REPO/deploy/nginx/agentotel.conf" "$NGINX_SITE"
  sudo nginx -t
  echo "    nginx conf refreshed"
else
  echo "    nginx conf unchanged"
fi

echo "==> [5/7] reload nginx + restart services"
sudo systemctl reload nginx || sudo systemctl restart nginx
for unit_src in "$REPO"/deploy/systemd/*.service; do
  unit_name="$(basename "$unit_src")"
  sudo systemctl restart "$unit_name"
  echo "    restarted $unit_name"
done
sleep 2

echo "==> [6/7] smoke test"
BACKEND_CODE=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8091/health 2>/dev/null || echo "000")
NGINX_CODE=$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST http://127.0.0.1:8088/api/auth/phone/code \
  -H 'Content-Type: application/json' \
  -d '{"phone":"18800000000","scene":"login"}' 2>/dev/null || echo "000")
echo "    backend :8091/health  -> $BACKEND_CODE"
echo "    nginx   :8088/api/... -> $NGINX_CODE"
if [[ "$NGINX_CODE" != "200" && "$NGINX_CODE" != "429" && "$NGINX_CODE" != "400" ]]; then
  echo "!! smoke test FAILED — check: journalctl -u agentotel-backend -n 50"
  exit 1
fi

echo "==> [7/7] write version.txt"
cat > "$REPO/version.txt" <<EOF
version: git-${COMMIT}-$(date +%s)
build_time: $(date '+%Y-%m-%d %H:%M:%S %Z')
commit: ${COMMIT}
branch: ${BRANCH}
mode: systemd-native (no-docker)
EOF
cat "$REPO/version.txt"

echo "==> ✅ deploy done"
