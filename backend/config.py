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


config = Config()
