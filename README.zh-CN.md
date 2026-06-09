# LocalNow

[English](README.md) | **中文**

面向本地生活场景的短时活动**规划与执行** Agent。

接收一句口语目标——*"今天下午带老婆孩子 / 朋友出去玩几个小时，别太远，帮我安排"*——输出**可对比、可执行**的多环节行程（玩 → 吃 → 活动），用户确认后**一键完成关键预订**并把计划**分享给同伴**。

不是搜索推荐，是"帮你把事情做完"。

📄 **设计文档（Planning 策略 / 工具调用链路 / 异常处理）**：[docs/design.zh-CN.md](docs/design.zh-CN.md)

## 它能做什么

- 🗣️ **口语目标 + 差异化场景**：结构化表单 + 自然语言补充；家庭（孩子 5 岁 → 亲子场所 + 儿童餐、老婆减肥 → 低卡餐厅）/ 朋友（多人聚会）自动套用不同约束。
- 🗺️ **真实地图数据**：`geocode 地名 → 坐标 → 周边搜索`，**全国任意城市 / 区县 / 景区 / 海岛**都可用（无 API Key 时自动降级到本地 mock）。
- 🧠 **LLM + LangGraph 工作流**：召回 → 生成 → **程序化时间/预算校验 + 失败回灌重试**（不只信 LLM 自述）→ 人在环路确认 / 带反馈重规划。
- ❄️ **冷门诉求语义降级**：找不到"某家拉面馆 / 莫奈特展"时，LLM 产出"具体→宽泛"检索阶梯逐级降级到相近人气候选，并向用户说明。
- ⚡ **并发单方案生成**：多日行程墙钟耗时约提速 2 倍；请求超时 + 重试上限，防止单次调用卡死。
- ✅ **确认后行程清单**：按天勾选"已完成 / 已预订"（localStorage 持久化）、**一键打开全部预订页**、复制 / 导出 PDF / 邮件分享。
- 🔌 **多模型 Provider 抽象**（Gemini / LongCat / OpenAI / DeepSeek / Ollama，改 `.env` 即切换）；**Docker + GitHub Actions CI**。

## 工作流（LangGraph，确定性编排 + 人在环路）

```
parse_intent → search_candidates → generate_plans → check_availability
   ├─ 有可用方案 → [interrupt] human_review
   │      ├─ 确认 → execute_bookings → send_notification → END
   │      └─ 拒绝 → parse_replan_feedback → search_candidates …（重规划）
   └─ 全部不可用 → 重规划 →（超上限）handle_error → END
```

## 项目结构

```
LocalNow/
├── backend/          # Python 后端（FastAPI + LangGraph）
│   ├── agent/        # 状态图与节点（解析/召回/生成/校验/预订/通知）
│   ├── tools/        # 工具：amap_http(geocode+周边搜索)、geo、travel、links、notification
│   ├── llm/          # LLM 工厂（多 provider 切换）
│   ├── models/       # Pydantic 数据模型
│   ├── data/         # 本地 mock 数据（无 API Key 时兜底）
│   ├── prompts/      # Prompt 模板
│   ├── api/          # FastAPI 入口（SSE 流式进度）
│   └── tests/        # 单元测试（131 个）
├── frontend/         # Next.js 16 前端（表单 / 实时进度 / 方案对比 / 行程清单）
├── docs/             # design / architecture / development / deployment
└── docker-compose.yml + .github/workflows/ci.yml
```

## 快速开始

### 环境要求

- Python 3.11+ ·  Node.js 20+ ·  [uv](https://github.com/astral-sh/uv)

### 后端

```bash
cd backend
cp .env.example .env      # 填入 API Key
uv sync
uv run uvicorn api.main:app --reload
```

`.env` 关键配置：

```env
# LLM Provider：anthropic | openai | deepseek | gemini | ollama | longcat
LLM_PROVIDER=gemini
GOOGLE_API_KEY=...         # 或对应 provider 的 Key
AMAP_API_KEY=...           # 地图（真实场所/餐厅召回；缺省走本地 mock）
```

### 前端

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
```

## Docker 一键启动

```bash
cp .env.example .env      # 填入 LLM_PROVIDER / 对应 API Key / AMAP_API_KEY
docker compose up --build
```

前端 http://localhost:3000 ·  后端 http://localhost:8000
（`NEXT_PUBLIC_API_URL` 在前端构建时内联，浏览器直连后端；部署时改为后端公网地址并重新构建前端镜像。）

## CI

GitHub Actions（`.github/workflows/ci.yml`）在 push 到 main 和所有 PR 上运行：

- **backend**：`ruff check` + `pytest`
- **frontend**：`tsc --noEmit` + `eslint` + `next build`
- **docker**：构建前后端镜像（验证 Dockerfile）

## 文档

- [设计文档 design.zh-CN.md](docs/design.zh-CN.md)：Planning 策略 / 工具调用链路（含 Tool + Mock 表）/ 异常处理机制
- [架构设计 architecture.zh-CN.md](docs/architecture.zh-CN.md)：技术选型与设计决策
- [开发记录 development.zh-CN.md](docs/development.zh-CN.md)
- [部署指南 deployment.zh-CN.md](docs/deployment.zh-CN.md) · 测试说明：[backend/tests/README.zh-CN.md](backend/tests/README.zh-CN.md)
