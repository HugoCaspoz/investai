from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "InvestAI API"
    database_url: str = "sqlite:///./investai.db"
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_default_chat_id: str = ""
    openai_api_key: str = ""
    max_alerts_per_day: int = 3
    internal_job_token: str = ""
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
