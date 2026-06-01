"""FastAPI 应用入口。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router

app = FastAPI(
    title="LocalNow API",
    description="本地活动规划 Agent 后端接口",
    version="0.1.0",
)

# 开发阶段允许所有来源，生产环境替换为具体域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
