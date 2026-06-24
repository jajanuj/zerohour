from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./zerohour_dev.db")
    supabase_url: str = Field(default="")
    supabase_anon_key: str = Field(default="")

    # Redis / Celery
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Market data
    alpha_vantage_api_key: str = Field(default="")
    fugle_api_key: str = Field(default="")

    # Broker
    ibkr_host: str = Field(default="127.0.0.1")
    ibkr_port: int = Field(default=7497)
    ibkr_client_id: int = Field(default=1)
    yuanta_api_key: str = Field(default="")
    yuanta_secret: str = Field(default="")

    # Alerts
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    # Gemini API
    gemini_api_key: str = Field(default="")

    # Trading parameters
    trading_mode: str = Field(default="paper")  # paper | live | observe
    max_position_pct: float = Field(default=0.30)
    max_total_exposure_pct: float = Field(default=0.80)
    us_signal_threshold: float = Field(default=1.5)
    ma_period: int = Field(default=200)
    index_stop_loss_pct: float = Field(default=0.12)
    trailing_stop_pct: float = Field(default=0.15)
    min_confidence: float = Field(default=0.6)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
