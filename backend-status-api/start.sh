#!/usr/bin/env bash
set -euo pipefail
cd /home/admin/workspace/agent-mission-control/backend-status-api
mkdir -p run
echo $$ > run/status-api.pid
exec python3 status_api.py >> run/status-api.log 2>&1
