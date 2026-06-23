#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path('/home/admin/workspace/agentotel')
ENV_FILE = ROOT / '.env'
BACKEND = ROOT / 'server/backend-api/backend_api.py'

def load_env(path: Path) -> dict[str, str]:
    env = os.environ.copy()
    if path.exists():
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip().removeprefix('export ').strip()
            value = value.strip()
            if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
                value = value[1:-1]
            env[key] = value
    defaults = {
        'MYSQL_PORT': '3306',
        'MYSQL_DB': 'agentotel_meta',
        'CLICKHOUSE_DB': 'agentotel_project_proj_c9a73efa88944295',
        'CLICKHOUSE_URL': 'http://127.0.0.1:8123/?database=agentotel_project_proj_c9a73efa88944295',
        'PROJECT_ID': 'proj_c9a73efa88944295',
        'ENVIRONMENT': 'default',
        'PYTHONUNBUFFERED': '1',
    }
    for key, value in defaults.items():
        env.setdefault(key, value)
    return env

if __name__ == '__main__':
    env = load_env(ENV_FILE)
    os.chdir(ROOT)
    os.execvpe('python3', ['python3', str(BACKEND), '--host', '0.0.0.0', '--port', '8091'], env)
