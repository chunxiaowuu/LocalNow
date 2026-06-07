# LocalNow

面向本地生活场景的短时活动规划与执行 Agent。

接收一句自然语言目标（"今天下午带娃出去玩，顺便吃个饭"），输出可落地的完整方案，并在用户确认后自动完成所有预订/购票动作。

## 项目结构

```
LocalNow/
├── backend/          # Python 后端（FastAPI + LangGraph）
│   ├── agent/        # LangGraph 状态图和节点
│   ├── tools/        # 工具函数（搜索/可用性/预订/通知）
│   ├── llm/          # LLM 工厂（多 provider 切换）
│   ├── models/       # Pydantic 数据模型
│   ├── data/         # Mock 数据（50 家餐厅 + 30 个场所）
│   ├── prompts/      # Prompt 模板
│   ├── api/          # FastAPI 入口
│   └── tests/        # 单元测试
├── frontend/         # Next.js 14 前端
└── docs/             # 技术文档
    ├── architecture.md   # 架构设计与技术选型
    ├── development.md    # 开发过程记录
    └── troubleshooting.md
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv)（Python 包管理）

### 后端启动

```bash
cd backend
cp .env.example .env      # 填入 API Key
uv sync                   # 安装依赖
uv run uvicorn api.main:app --reload
```

`.env` 关键配置：

```env
# LLM Provider：anthropic | openai | deepseek | gemini | ollama
LLM_PROVIDER=gemini

# 对应 provider 的 API Key（填其中一个即可）
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...          # Google AI Studio：aistudio.google.com/apikey
OPENAI_API_KEY=sk-...
```

### 前端启动

```bash
cd frontend
npm install
npm run dev
```

## Docker 一键启动

```bash
cp .env.example .env      # 填入 LLM_PROVIDER / 对应 API Key / AMAP_API_KEY
docker compose up --build
```

- 前端：http://localhost:3000
- 后端：http://localhost:8000

说明：`NEXT_PUBLIC_API_URL` 在前端**构建时**内联，浏览器直连后端，本地保持默认 `http://localhost:8000` 即可；部署到服务器时改成后端公网地址并重新构建前端镜像。

## CI

GitHub Actions（`.github/workflows/ci.yml`）在 push 到 main 和所有 PR 上运行：

- **backend**：`ruff check` + `pytest`
- **frontend**：`tsc --noEmit` + `eslint` + `next build`
- **docker**：构建前后端镜像（验证 Dockerfile，不推送）

## 测试

详见 [backend/tests/README.md](backend/tests/README.md)

## 技术文档

- [架构设计](docs/architecture.md)：技术选型、设计决策、参考来源
- [开发记录](docs/development.md)：各模块实现细节
- [问题记录](docs/troubleshooting.md)：开发过程中遇到的问题与解法
