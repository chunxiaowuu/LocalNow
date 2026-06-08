# 部署指南（GitHub Pages + Render）

[English](deployment.md) | **中文**

LocalNow 上线架构与安全限流的部署步骤。

## 架构

```
浏览器
  │  静态站点
  ▼
GitHub Pages（前端，Next.js 静态导出）  ──fetch（带 Authorization: Bearer）──►  Render（后端 FastAPI + LangGraph）
  https://chunxiaowuu.github.io/LocalNow                                       https://localnow-backend.onrender.com
                                                                                   │
                                                                          地图 API / 美团 LongCat
```

- **前端**：GitHub Pages（静态导出，`basePath=/LocalNow`），由 GitHub Actions 自动发布。
- **后端**：Render（Docker），持有所有密钥，**只用美团 LongCat**（`LLM_PROVIDER=longcat`，不配置其他 LLM key）。
- **登录**：GitHub OAuth；后端签发 token，前端存 localStorage，请求带 `Authorization: Bearer`（跨站稳，避开第三方 cookie 被拦截）。

## 安全 / 限流

| | 每天 plan 生成 | 每个 plan 修改（replan）|
|---|---|---|
| 未登录（按 IP）| 1 | ≤ 3 |
| 登录（按用户）| 3 | ≤ 9 |

超额返回 `429` + 提示。密钥仅存在后端环境变量，永不下发浏览器。

## 环境变量（在 Render 后端设置）

| 变量 | 说明 | 示例 |
|---|---|---|
| `LLM_PROVIDER` | 固定 `longcat`（蓝图已设） | `longcat` |
| `LONGCAT_API_KEY` | 美团 LongCat 密钥 | `ak_...` |
| `AMAP_API_KEY` | 地图密钥 | `...` |
| `SESSION_SECRET` | token 签名密钥（蓝图自动生成） | 自动 |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth App | |
| `ALLOWED_ORIGINS` | 前端来源（CORS） | `https://chunxiaowuu.github.io` |
| `FRONTEND_BASE` | 登录完成后跳回地址 | `https://chunxiaowuu.github.io/LocalNow` |
| `OAUTH_REDIRECT_BASE` | 后端公网地址（OAuth 回调） | `https://localnow-backend.onrender.com` |

> ⚠️ **不要**配置 `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`——线上只用 LongCat key。

前端构建变量（GitHub 仓库 Variable）：

| 变量 | 说明 | 示例 |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | 后端地址（构建时内联进前端） | `https://localnow-backend.onrender.com` |

## 步骤（按顺序）

**0. 合并部署分支到 `main`**（`render.yaml` 与发布 workflow 需在 main 上）。首次 Pages 部署会自动跑，缺少变量时会失败，按下面补齐后重跑即可。

**1. Render 部署后端**
1. render.com → **New + → Blueprint** → 选仓库 `chunxiaowuu/LocalNow`（读取 `render.yaml` 创建 `localnow-backend`）。
2. 记下其 URL（如 `https://localnow-backend.onrender.com`）。
3. 在服务 **Environment** 填上表中的密钥（`LONGCAT_API_KEY`、`AMAP_API_KEY`、`ALLOWED_ORIGINS`、`FRONTEND_BASE`、`OAUTH_REDIRECT_BASE`）。

**2. 创建 GitHub OAuth App**（GitHub → Settings → Developer settings → **OAuth Apps → New**）
- Homepage URL：`https://chunxiaowuu.github.io/LocalNow`
- **Authorization callback URL**：`https://localnow-backend.onrender.com/auth/github/callback`
- 取得 Client ID + 生成 Secret，填入 Render 的 `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`（Render 自动重部署）。

**3. GitHub Pages 部署前端**
1. 仓库 **Settings → Pages** → Source = **GitHub Actions**。
2. 仓库 **Settings → Secrets and variables → Actions → Variables** → 新建 `NEXT_PUBLIC_API_URL` = 后端 Render 地址。
3. **Actions** → 运行 **"Deploy frontend (GitHub Pages)"**（已有变量后重跑）→ 站点：`https://chunxiaowuu.github.io/LocalNow`。

**4. 验证**
- 打开 Pages 站点 → 顶栏"今日剩余规划 1/1"（未登录）→ 规划一次 → 再次应被 429 拦截。
- 点 **GitHub 登录** → 授权 → 跳回，额度变 3/3 → 可规划 3 次。

## 免费层注意（demo 可接受）

- Render 免费实例闲置 ~15 分钟后休眠 → 首次请求冷启动约 30–60s。
- 限流 SQLite 在临时磁盘 → **重部署/重启会重置**（正常运行期间每日限额有效）。需硬持久化可挂 Render Disk 或外接 Redis。

## 本地开发

仍按 `README.zh-CN.md`：`LLM_PROVIDER` 可任意（如 `gemini`，更快），不设 OAuth/限流相关变量时登录按钮隐藏、限流按匿名（每天 1 次）。Docker 一键：`docker compose up --build`。
