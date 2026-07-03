# AgentOTel 运维手册 (SOP)

> 所有研发和运维必读。发布流程严格按此执行。
> Owner: Jack (CTO)  |  Last updated: 2026-07-03

---

## 1. 环境地址

| 环境 | 用途 | IP | 域名 | 部署形态 | 责任人 |
|------|------|----|----|---------|----|
| **Dev** | 开发 + 联调 + 打包 | `47.110.255.35` | `agentotel.cloud` | Docker Compose | David / Vivi |
| **Prod** | 线上生产 | `47.237.100.232` | (对外服务) | **原生进程** (systemd + nginx) | Tiger |
| **ClickHouse** | 遥测数据 (**外部实例，两环境共用**) | `121.43.27.45:8123` | — | 独立部署 | Simon |

### 端口约定

| 端口 | 服务 | 说明 |
|------|------|------|
| 8088 | Frontend (nginx) | 用户界面 + `/api/` 反代到 8091 |
| 8091 | Backend API | `python backend_api.py`，仅 nginx 内部访问（`127.0.0.1`） |
| 4317 | OTel Collector gRPC | OTLP 数据接收 |
| 4318 | OTel Collector HTTP | OTLP HTTP `/v1/traces` |
| 3306 | MySQL | dev 与 prod 各自本机跑 |

### 域名分工
- `http://agentotel.cloud:8088` → **dev** (联调 / 演示)
- Prod：`http://47.237.100.232:8088`（对外域名待补 DNS）
- OTLP 上报：`http://agentotel.cloud:4318/v1/traces`

---

## 2. 两环境部署形态对比

**规则：dev 用 docker-compose 保持隔离，prod 用原生进程降低复杂度。**

| 项 | Dev (`47.110.255.35`) | Prod (`47.237.100.232`) |
|----|----------------------|------------------------|
| 仓库路径 | `/home/admin/workspace/agentotel` | `/home/admin/agentotel` |
| Backend | `agentotel-server` 容器 | systemd unit `agentotel-backend.service`，venv `~/agentotel/.venv` |
| Frontend | `agentotel-front` 容器 (nginx-alpine) | 系统 nginx (`apt install nginx`)，配置 `/etc/nginx/conf.d/agentotel.conf`，静态文件 `~/agentotel/front/` |
| Collector | `agentotel-collector` 容器 | systemd unit `agentotel-collector.service` |
| ClickHouse | 外部 `121.43.27.45:8123` | 外部 `121.43.27.45:8123` |
| MySQL | 本机 3306 | 本机 3306 |
| 配置文件模板 | `.env.dev.example` → 拷成 `.env` | `.env.prod.example` → 拷成 `~/agentotel/.env` |
| 启动命令 | `docker compose up -d --build` | `bash deploy/deploy-prod.sh` |

### 关键路径
```
Dev  : /home/admin/workspace/agentotel/{docker-compose.yml, .env, front/, server/, ...}
Prod : /home/admin/agentotel/{deploy/, front/, server/, .env, .venv/, version.txt}
       /etc/systemd/system/agentotel-backend.service          (由 deploy-prod.sh 安装)
       /etc/systemd/system/agentotel-collector.service        (由 Simon 维护)
       /etc/nginx/conf.d/agentotel.conf                       (由 deploy-prod.sh 安装)
```

### 账号 & 密钥
真实值全部落在 `docs/SECRETS.md`（**git-ignored**）或各机器的 `.env`。
- Prod SSH：`admin@47.237.100.232`，key `~/.ssh/id_ed25519_47.237.100.232`
- MySQL：dev 与 prod 各自 `agentotel@localhost` + `agentotel@%`
- Aliyun SMS：签名"广州浮光智能科技"，模板 `SMS_498805405`
- GitHub：`git@github-agentotel:CrazyJoey/agentotel.git`

⚠️ **禁止**将真实密码写入任何进 git 的文件。

---

## 3. 发布 SOP（强制流程）

### 铁律
1. **线上问题必须先在 dev 复现修复**，禁止直接改线上代码/配置作为最终修复。
2. **热补丁只允许作为诊断手段**，事后必须走完整流程。
3. **未经老板验收的改动不能进 git**。
4. **一次 release 只带一组相关改动**。
5. **敏感信息永远不进 git**。

### 七步发布流程

| # | 阶段 | 责任人 | 动作 | 完成标志 |
|---|------|--------|------|---------|
| 1 | 发现问题 | Jack / QA | 定位根因，写"问题总结" | 报告给老板 |
| 2 | 开发修复 | David / Vivi | 在 dev 改代码，docker compose 起容器验 | 本地跑通 |
| 3 | 团队自测 | May + Jack | curl / 浏览器 / 日志三件套 | 通知老板："请验证 dev" |
| 4 | 老板验收 | 老板 | 浏览器实测 `agentotel.cloud:8088` | 回复：OK 或退回 2 |
| 5a | 代码入库 | David / Vivi | `git add` 只 stage 本次改动，`git commit`，`git push` | 远端有提交 |
| 5b | Prod 发布 | Tiger | ssh prod → `cd ~/agentotel && bash deploy/deploy-prod.sh` | version.txt 写入新 commit |
| 6 | 上线通知 | Jack | 通知老板："请验证 prod" | 消息已发 |
| 7 | 线上验收 | 老板 | 实测生产环境 | 回复 OK → 关闭工单 |

### Step 5a：精确 stage 单个文件

```bash
cd /home/admin/workspace/agentotel
git status --short
git diff <file>
git add server/backend-api/backend_api.py       # 只加本次相关文件
git diff --cached --stat
git commit -m "fix(scope): <一句话>"
git push origin <branch>
```

### Step 5b：Prod 发布（新版，无 docker）

```bash
ssh -i ~/.ssh/id_ed25519_47.237.100.232 admin@47.237.100.232
cd ~/agentotel
bash deploy/deploy-prod.sh
```

脚本自动做：
1. `git pull` 到最新
2. 更新 venv 依赖 (`pip install -r server/backend-api/requirements.txt`)
3. 若 systemd unit / nginx conf 有变更 → 拷到系统目录 + `daemon-reload`
4. `systemctl reload nginx` + `systemctl restart agentotel-backend`
5. 冒烟测试 `:8091/health` 与 `:8088/api/auth/phone/code`
6. 写 `version.txt`（含 commit + build_time + branch）

### Step 5b 冒烟测试（脚本自动跑，也可手动复核）

```bash
# 直连 backend
curl -si http://127.0.0.1:8091/health

# 经过 nginx
curl -si -X POST http://127.0.0.1:8088/api/auth/phone/code \
  -H 'Content-Type: application/json' \
  -d '{"phone":"18800000000","scene":"login"}'

# 服务状态
sudo systemctl status agentotel-backend --no-pager
journalctl -u agentotel-backend -n 50 --no-pager
```

### 回滚流程

```bash
# 在 prod
cd ~/agentotel
git log --oneline -10                       # 找上个稳定 commit
git checkout <上个 commit>                  # detached HEAD 状态
bash deploy/deploy-prod.sh                  # 重跑部署（会用当前 checkout）
# 验证通过后切回分支：git checkout <branch> && git reset --hard <上个 commit>
```

---

## 4. 常见问题排查

### 4.1 "验证码发送失败"
1. `journalctl -u agentotel-backend -n 100 --no-pager` 看 backend 报什么
2. `curl -si http://127.0.0.1:8091/api/auth/phone/code ...` 直连 backend
3. `curl -si http://127.0.0.1:8088/api/auth/phone/code ...` 经过 nginx
4. 检查 `~/agentotel/.env` 里的 `MYSQL_*` / `ALIYUN_SMS_*`
5. 检查 `sudo nginx -t` 是否 OK，`/etc/nginx/conf.d/agentotel.conf` 有 `location /api/`

### 4.2 MySQL Access denied
- `agentotel@localhost` 和 `agentotel@'%'` 是两个独立账号，分别授权。
- prod 本机走 `@localhost`；dev 跨机连 prod 走 `@'%'`。

### 4.3 Backend 端口占用
- `sudo lsof -iTCP:8091 -sTCP:LISTEN` — 应该只有 `python`（backend_api.py）
- 若还残留 docker 容器：`docker ps | grep agentotel` → `docker stop agentotel-server agentotel-front`

### 4.4 Nginx 起不来
- `sudo nginx -t` 定位语法错
- `sudo tail -50 /var/log/nginx/error.log`
- `sudo tail -50 /var/log/nginx/agentotel.error.log`

### 4.5 ClickHouse 连不上
- 外部实例 `121.43.27.45:8123`，非本机部署 —— 找 Simon 排查
- 本地临时冒烟：`curl -sS 'http://121.43.27.45:8123/?query=SELECT+1'`

---

## 5. 联系人

| 角色 | 姓名 | 负责范围 |
|------|------|---------|
| CTO | Jack | 架构决策、问题定位、发布节奏 |
| Backend | David | `server/backend-api/` |
| Frontend | Vivi | `front/` |
| OTel | Simon | `opentelemetry-collector/` + 外部 ClickHouse |
| DevOps | Tiger | 部署、prod 机器、systemd/nginx |
| QA | May | Step 3 团队自测 |
| PM | Tina | 需求 / 优先级 |
