"""FastAPI 应用入口。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from config import config

app = FastAPI(
    title="LocalNow API",
    description="本地活动规划 Agent 后端接口",
    version="0.1.0",
)

# CORS：本地默认放开（"*"），生产用 ALLOWED_ORIGINS 锁定前端域名。
# 注意：带 cookie 的跨域请求要求 allow_credentials=True 且来源不能是 "*"。
_origins = config.allowed_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
