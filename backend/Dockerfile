# LocalNow 后端镜像：uv 装依赖 + uvicorn 运行 FastAPI
FROM python:3.12-slim

# 从官方镜像取 uv 二进制（快且可复现）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# 先装依赖（仅 lock 变化才失效，最大化缓存命中）；--no-install-project：本服务直接以源码运行
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 再拷源码（prompts/、data/ 等运行时按文件路径读取，必须随镜像带上）
COPY . .

EXPOSE 8000

# 直接用 venv 里的 uvicorn，运行时不再触发 uv 同步
CMD [".venv/bin/uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
