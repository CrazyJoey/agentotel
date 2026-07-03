# Changelog

本文档记录 AgentOTel 平台每次发布的变更。格式参考 [Keep a Changelog](https://keepachangelog.com/)。
版本号使用镜像发布时间戳（形如 `v1.0.<unix_ts>`），Git commit 是唯一权威来源。

发布流程见 [docs/OPERATIONS.md](docs/OPERATIONS.md)。

---

## [Unreleased]

### Added
- **Deploy model pivot: prod 弃 docker，改用 systemd 原生进程 + 系统 nginx**
  - `deploy/systemd/agentotel-backend.service` — backend 走 venv (`~/agentotel/.venv`)
  - `deploy/nginx/agentotel.conf` — 系统 nginx 站点配置（listen 8088，反代 8091）
  - `deploy/deploy-prod.sh` — 幂等发布脚本：git pull → venv install → 拷 unit/nginx → reload → 冒烟 → version.txt
- **配置文件区分环境**：`.env.dev.example`（docker-compose）+ `.env.prod.example`（系统进程）
- **ClickHouse 明确为外部实例** `121.43.27.45:8123`，不再本地部署

### Changed
- `docs/OPERATIONS.md` — 全量重写，反映 dev=docker / prod=systemd 双形态；Step 5b 从 "build+push image" 改为 `bash deploy/deploy-prod.sh`
- Dev 仍保留 docker-compose 用于隔离，无变化

### Removed
- Prod 的 `agentotel-clickhouse` 容器（迁到外部实例）
- Prod 的 docker image build + save + scp + load 流程

---

## [v1.0.1783147] - 2026-07-02

**Type**: bugfix  |  **Commit**: `5aba57b`  |  **Branch**: `collector-agentotel-v0.154.0`

### Context
线上 (47.237.100.232) 前端点击"发送验证码"始终报错"验证码发送失败，请稍后重试"。

### Root causes
1. **MySQL 授权缺失** — prod backend 容器从 `127.0.0.1` 连 MySQL，命中 `agentotel@'localhost'`，但 MySQL 只授权了 `agentotel@'%'`。
2. **阿里云短信签名错误** — `backend_api.py` 的 canonical query string 只做了整串 percent-encode，缺了先对每个 k/v 分别编码的步骤，导致 `SignatureDoesNotMatch`。
3. **nginx 缺 `/api` 反代** — 前端容器 nginx 只有静态 root，任何 `POST /api/*` 被当作静态资源写请求，返回 405。
4. **PyMySQL 缺 cryptography** — `requirements.txt` 未装 `cryptography`，遇到 MySQL 8 默认的 `caching_sha2_password` 认证方式直接抛异常。
5. **Backend Dockerfile 用了不可达 registry** — 基础镜像 `python:3.11-slim` 走 docker.io，在国内 dev 机被墙。

### Changes
| 文件 | 改动 |
|------|------|
| `server/backend-api/backend_api.py` | Aliyun SendSms 签名改为先对每个 k/v percent-encode 再拼接，最后整体再编码一次（双重编码） |
| `server/backend-api/requirements.txt` | 新增 `cryptography==43.0.3` |
| `server/backend-api/Dockerfile` | 基础镜像改为 `docker.m.daocloud.io/python:3.11-slim` |
| `front/agentotel-front.conf` | 新增 `location /api/` 反代到 `http://127.0.0.1:8091` |

### Runtime config changes (not in git)
- Prod MySQL 已由老板执行 `CREATE USER 'agentotel'@'localhost' ... ; GRANT ALL ON agentotel_meta.* ...`
- Prod `.env` 里 `ALIYUN_SMS_ACCESS_KEY_SECRET` 已确认为完整 30 字节值

### Verification
- Dev (47.110.255.35)：curl 8091 直连 & 8088 经 nginx 都返回 200；老板浏览器实测收到真实短信。
- Prod：Tiger 拉新镜像后按 Step 5b 冒烟测试通过。

### Deploy
- Dev build 时间: 2026-07-02 16:xx CST
- Prod deploy 时间: **待 Tiger 完成后补充**
- Prod version.txt: **待 Tiger 更新**

---

## [v1.0.1782789250] - 2026-06-30

**Type**: baseline  |  Prior tag before 2026-07-02 fix.

### Contents
- backend-api 迁 MySQL 存储元数据
- 三 Agent per project 上限（本地代码有实现但当时未随此版发布）
- OTLP → 本地 collector → ClickHouse 直连链路打通
- 前后端登录 UX 打磨

---

## 模板：新版本请按这个格式填写

```markdown
## [vX.Y.Z] - YYYY-MM-DD

**Type**: bugfix | feature | refactor | ops  |  **Commit**: `<sha>`  |  **Branch**: `<name>`

### Context
（为什么要发这一版；解决什么问题）

### Root causes  ← 仅 bugfix 需要
1. ...

### Changes
| 文件 | 改动 |
|------|------|
| ... | ... |

### Runtime config changes (not in git)  ← 若涉及 .env / MySQL 授权 / 密钥
- ...

### Verification
- Dev：...
- 老板验收：OK / 未通过
- Prod：...

### Deploy
- Dev build 时间:
- Prod deploy 时间:
- Prod version.txt:
```
