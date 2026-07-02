# AgentOTel 运维手册 (SOP)

> 所有研发和运维必读。发布流程严格按此执行。
> Owner: Jack (CTO)  |  Last updated: 2026-07-02

---

## 1. 环境地址

| 环境 | 用途 | IP | 域名 | 责任人 |
|------|------|----|----|----|
| **Dev** | 开发 + 联调 + 打包 | `47.110.255.35` | `agentotel.cloud` | David / Vivi |
| **Prod** | 线上生产 | `47.237.100.232` | (对外服务) | Tiger |
| **ClickHouse** | 遥测数据 | `121.43.27.45:8123` | — | Simon |

### 端口约定（两台机器一致）

| 端口 | 服务 | 说明 |
|------|------|------|
| 8088 | Frontend (nginx) | 用户界面 + `/api/` 反代到 8091 |
| 8091 | Backend API | Python `backend_api.py`，仅 nginx 内部访问 |
| 4317 | OTel Collector gRPC | OTLP 数据接收 |
| 4318 | OTel Collector HTTP | OTLP HTTP `/v1/traces` |
| 3306 | MySQL | 仅 prod 部署（agentotel_meta 库） |

### 域名分工
- `http://agentotel.cloud:8088` → dev (联调/演示用)
- Prod 通过 IP 直连或独立域名（待补 DNS）
- OTLP 上报：`http://agentotel.cloud:4318/v1/traces`（MVP 阶段落 dev collector）

---

## 2. 服务与配置

### 目录约定
```
两台机器一致：/home/admin/workspace/agentotel   (dev, git 仓库)
              /home/admin/agentotel             (prod, 只放 docker-compose + .env + images)
```

### 关键配置文件
| 文件 | 位置 | 说明 |
|------|------|------|
| `docker-compose.yml` | 项目根 | 服务编排（front / server / opentelemetry-collector） |
| `.env` | 项目根 | 环境变量（**不进 git**，含密钥） |
| `front/agentotel-front.conf` | — | nginx 反代配置 |
| `server/backend-api/backend_api.py` | — | 后端 API 全部逻辑 |
| `version.txt` | 项目根 | 当前镜像版本号（发布时写入） |

### 账号 & 密钥存放（真值见 `docs/SECRETS.md`，未进 git）

| 项 | 用户名 | 密码位置 | 用途 |
|----|--------|---------|------|
| Prod SSH | `admin` | `~/.ssh/id_ed25519_47.237.100.232` (免密) | 部署 |
| Dev SSH | `admin` | 本机登录即可 | 开发 |
| MySQL (prod localhost) | `agentotel` | `SECRETS.md` § MySQL | backend 从容器 127.0.0.1 连 |
| MySQL (远程访问) | `agentotel@%` | 同上 | dev backend 从 47.110.255.35 连 |
| Aliyun 短信 | AccessKey `LTAI5tSnWLDrEd2QCtkNcCUK` | `SECRETS.md` § Aliyun | 登录/注册验证码 |
| ClickHouse | `default` | `SECRETS.md` § ClickHouse | 遥测存储 |
| GitHub (repo) | `git@github-agentotel:CrazyJoey/agentotel.git` | SSH deploy key | 代码托管 |

⚠️ **禁止**将真实密码写入任何进 git 的文件（包括 README、注释、示例代码）。

---

## 3. 发布 SOP（强制流程）

### 铁律
1. **线上问题必须先在 dev 复现修复**，禁止直接改线上代码/配置作为最终修复。
2. **热补丁（`docker cp` 改容器内文件）只允许作为诊断手段**，事后必须走完整流程。
3. **未经老板验收的改动不能进 git**。
4. **一次 release 只带一组相关改动**，不同类型的改动分开发布。
5. **敏感信息（密码、AccessKey、JWT secret）永远不进 git**。

### 七步发布流程

| # | 阶段 | 责任人 | 动作 | 完成标志 |
|---|------|--------|------|---------|
| 1 | 发现问题 | Jack / QA | 定位根因，写"问题总结" | 报告给老板 |
| 2 | 开发修复 | David / Vivi | 在 dev (`47.110.255.35`) 改代码，**不 commit** | 本地跑通 |
| 3 | 团队自测 | May (QA) + Jack | curl / 浏览器 / 日志三件套验证 | 通知老板："请验证 dev" |
| 4 | 老板验收 | 老板 | 浏览器实测 `agentotel.cloud:8088` | 回复："OK" 或退回 2 |
| 5a | 代码入库 | David / Vivi | `git add` 只 stage 本次改动的相关文件，`git commit`，`git push` | 远端有提交 |
| 5b | 打包发布 | Tiger | dev 上 build 镜像 → 打 tag → save → scp → prod load → `docker compose up -d --force-recreate` | prod 容器已重启 |
| 6 | 上线通知 | Jack | 通知老板："请验证 prod" | 消息已发 |
| 7 | 线上验收 | 老板 | 实测生产环境功能 | 回复 OK → 关闭工单 |

### 每一步的具体命令

**Step 5a: 精确 stage 单个文件**
```bash
cd /home/admin/workspace/agentotel
git status --short                              # 先看工作区脏文件
git diff <file>                                 # 逐个文件确认改动
git add server/backend-api/backend_api.py       # 只加本次相关文件
git diff --cached --stat                        # 二次确认 stage 内容
git commit -m "fix(scope): <一句话> \n\n<原因> \n<影响> \n<测试>"
git push origin <branch>
```

**Step 5b: dev 打镜像 → prod 部署**
```bash
# 在 dev (47.110.255.35)
cd /home/admin/workspace/agentotel
VERSION="v1.0.$(date +%s)"
docker compose build server front                                 # 或只 build 变更的
docker tag localhost/agentotel_server:latest agentotel-server:$VERSION
docker tag localhost/agentotel_front:latest  agentotel-front:$VERSION
docker save agentotel-server:$VERSION agentotel-front:$VERSION -o /tmp/release-$VERSION.tar
scp -i ~/.ssh/id_ed25519_47.237.100.232 /tmp/release-$VERSION.tar admin@47.237.100.232:/tmp/

# 在 prod (47.237.100.232)
ssh -i ~/.ssh/id_ed25519_47.237.100.232 admin@47.237.100.232 bash <<EOF
  docker load -i /tmp/release-$VERSION.tar
  cd ~/agentotel
  docker compose up -d --force-recreate server front
  docker logs agentotel-server --tail 20
  echo "version: $VERSION" > version.txt
EOF
```

**Step 5b 冒烟测试（发完必跑）**
```bash
# 直连 backend
curl -si -X POST http://127.0.0.1:8091/api/auth/phone/code \
  -H 'Content-Type: application/json' \
  -d '{"phone":"18800000000","scene":"login"}' | head -5

# 经过 nginx
curl -si -X POST http://127.0.0.1:8088/api/auth/phone/code \
  -H 'Content-Type: application/json' \
  -d '{"phone":"18800000000","scene":"login"}' | head -5

# 期望：HTTP 200，body 含 "ok":true
```

### 回滚流程
```bash
# 在 prod，用上一版本 tag
cd ~/agentotel
docker tag agentotel-server:<上个版本> localhost/agentotel_server:latest
docker tag agentotel-front:<上个版本>  localhost/agentotel_front:latest
docker compose up -d --force-recreate server front
echo "version: <上个版本> (rolled back from <坏版本>)" > version.txt
```

---

## 4. 常见问题排查

### 4.1 前端"验证码发送失败"
排查顺序：
1. `docker logs agentotel-server --tail 50` 看 backend 报什么错
2. `curl -si http://127.0.0.1:8091/api/auth/phone/code ...` 直连 backend
3. `curl -si http://127.0.0.1:8088/api/auth/phone/code ...` 经过 nginx
4. 检查 `.env` 里的 `MYSQL_*` / `ALIYUN_SMS_ACCESS_KEY_SECRET`
5. 检查 nginx 是否配了 `location /api/` 反代

### 4.2 MySQL Access denied
- `agentotel@localhost` 和 `agentotel@'%'` 是 MySQL 中**两个独立账号**，需要分别授权。
- prod backend 容器连 `127.0.0.1` 走的是 `@'localhost'`；dev backend 连 prod 走的是 `@'%'`。

### 4.3 Docker Hub 拉不动
- 所有 Dockerfile 的基础镜像用 `docker.m.daocloud.io/` 前缀。
- Aliyun 国内节点访问 docker.io 会超时。

### 4.4 podman-compose "port mappings discarded"
- host 网络模式下警告可忽略，端口直接由容器内 EXPOSE 决定。

---

## 5. 联系人

| 角色 | 姓名 | 负责范围 |
|------|------|---------|
| CTO | Jack | 架构决策、问题定位、发布节奏 |
| Backend | David | server/backend-api/ |
| Frontend | Vivi | front/ |
| OTel | Simon | opentelemetry-collector/ |
| DevOps | Tiger | 部署、镜像、prod 机器 |
| QA | May | Step 3 团队自测 |
| PM | Tina | 需求 / 优先级 |
