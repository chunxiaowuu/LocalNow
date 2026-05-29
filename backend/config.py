from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    langsmith_api_key: str = ""
    langsmith_project: str = "localnow"

    # Agent 行为
    max_replan_count: int = 2
    availability_timeout_s: float = 5.0
    max_candidate_plans: int = 2


config = Config()
