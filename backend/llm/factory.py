"""
LLM 工厂：根据 config.llm_provider 返回对应的 LangChain ChatModel。

两个角色：
  main  → 规划/执行节点，需要强推理能力（generate_plans）
  fast  → 解析/通知节点，速度优先（parse_intent, send_notification）

节点代码只依赖角色名，切换 provider 只需改 .env，节点代码不动。
"""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from config import config

# provider → (main_model, fast_model)
_MODEL_MAP: dict[str, tuple[str, str]] = {
    "anthropic": ("claude-sonnet-4-6",   "claude-haiku-4-5-20251001"),
    "openai":    ("gpt-4o",              "gpt-4o-mini"),
    "deepseek":  ("deepseek-chat",       "deepseek-chat"),
    "ollama":    ("qwen3:8b",            "qwen3:8b"),
    "gemini":    ("gemini-2.5-flash",    "gemini-2.5-flash"),
    "longcat":   ("LongCat-2.0-Preview", "LongCat-2.0-Preview"),
}


@lru_cache(maxsize=4)
def get_llm(role: str = "main") -> BaseChatModel:
    """
    返回指定角色的 LLM 实例，全局缓存避免重复初始化。

    role: "main" | "fast"
    """
    provider = config.llm_provider.lower()
    if provider not in _MODEL_MAP:
        raise ValueError(
            f"未知 provider: {provider}，可选: {list(_MODEL_MAP.keys())}"
        )

    main_model, fast_model = _MODEL_MAP[provider]
    model_name = main_model if role == "main" else fast_model

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_name,
            api_key=config.anthropic_api_key,
            temperature=0,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=config.openai_api_key,
            temperature=0,
        )

    if provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            base_url="https://api.deepseek.com/v1",
            api_key=config.openai_api_key,
            temperature=0,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model_name, temperature=0)

    if provider == "gemini":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=config.google_api_key,
            temperature=0,
        )

    if provider == "longcat":
        # 美团 LongCat，OpenAI 兼容端点（https://longcat.chat/platform）
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            base_url="https://api.longcat.chat/openai/v1",
            api_key=config.longcat_api_key,
            temperature=0,
        )

    raise ValueError(f"provider {provider} 未实现")
