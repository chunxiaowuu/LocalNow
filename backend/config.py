from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent / ".env"


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    # LLM
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    longcat_api_key: str = ""
    langsmith_api_key: str = ""
    langsmith_project: str = "localnow"

    # 高德地图
    amap_api_key: str = ""

    # Agent 行为
    max_replan_count: int = 2
    availability_timeout_s: float = 5.0
    max_candidate_plans: int = 2
    max_timeline_retries: int = 2          # 方案时间校验失败后的最大重试次数
    timeline_tolerance_min: int = 15       # 每天总时长校验的容差（分钟）

    # LLM 单次请求超时（秒）与客户端重试次数：
    # 防止某次调用在服务端卡死/限流退避导致整体卡十几分钟（实测见过 930s 的离群值）。
    llm_timeout_s: float = 240.0
    llm_max_retries: int = 2

    # 限流（部署安全）：未登录每天 1 个 plan、每个 plan 最多 3 次修改；
    # 登录后每天 3 个 plan、每个 plan 最多 9 次修改。
    anon_plans_per_day: int = 1
    anon_calls_per_plan: int = 3
    auth_plans_per_day: int = 3
    auth_calls_per_plan: int = 9
    ratelimit_db_path: str = str(Path(__file__).parent / "ratelimit.db")

    # 鉴权 / CORS（部署用；本地默认放开）
    session_secret: str = "dev-insecure-secret-change-in-prod"  # 签名登录 cookie
    allowed_origins: str = "*"                                  # 逗号分隔的前端来源；生产填具体域名
    github_client_id: str = ""                                  # GitHub OAuth App
    github_client_secret: str = ""
    oauth_redirect_base: str = "http://localhost:8000"          # 后端公网地址（OAuth 回调用）
    frontend_base: str = "http://localhost:3000"               # 登录完成后跳回前端

    @property
    def allowed_origins_list(self) -> list[str]:
        return ["*"] if self.allowed_origins.strip() == "*" else [
            o.strip() for o in self.allowed_origins.split(",") if o.strip()
        ]


config = Config()
