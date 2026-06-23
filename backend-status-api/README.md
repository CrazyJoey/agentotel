# Agent Mission Control backend-status-api

Lightweight local JSON status API for the Agent Mission Control MVP.

## Endpoints

- GET /api/status
- GET /health

## Run

```bash
cd /home/admin/workspace/agent-mission-control/backend-status-api
python3 status_api.py
```

The service listens on 0.0.0.0:8090 and returns open CORS headers for MVP use.

## Verify

```bash
curl http://127.0.0.1:8090/health
curl http://127.0.0.1:8090/api/status | python3 -m json.tool
python3 -m pytest tests/test_status_api.py -q
```
