from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class ScalperSettings(BaseSettings):
    """策略三設定。讀取本地 .env.scalper（不入版控），預設值對應 scalper-spec.md §0 A3/§1 v0 規則表。"""

    shioaji_api_key: str = Field(default="")
    shioaji_secret_key: str = Field(default="")
    shioaji_ca_path: str = Field(default="")
    shioaji_ca_password: str = Field(default="")
    shioaji_simulation: bool = Field(default=True)

    scalper_discord_webhook: str = Field(default="")

    # 合約與成本常數（§1）
    tick_value: float = Field(default=500.0)          # 1 tick = 500 元/口（股價>1000小型股期）
    tick_size: float = Field(default=5.0)              # 價格最小跳動
    fee_per_side: float = Field(default=25.0)
    tax_rate: float = Field(default=0.00002)

    # v0 規則表參數（A3）
    stop_loss_ticks: int = Field(default=2)
    take_profit_ticks: int = Field(default=1)
    max_inventory_lots: int = Field(default=1)
    depth_qty_threshold: int = Field(default=20)
    aggressive_volume_threshold: int = Field(default=30)
    aggressive_window_seconds: int = Field(default=30)
    aggressive_cooldown_seconds: int = Field(default=60)

    # 熔斷（A3）
    daily_loss_limit: float = Field(default=3000.0)
    consecutive_loss_pause: int = Field(default=3)
    consecutive_loss_pause_minutes: int = Field(default=30)

    # 交易時段
    session_start: str = Field(default="09:05")
    session_end: str = Field(default="13:15")

    # 下單延遲模擬（Phase 2 悲觀回測用）
    order_ack_delay_ms: int = Field(default=300)

    class Config:
        env_file = ".env.scalper"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache
def get_scalper_settings() -> ScalperSettings:
    return ScalperSettings()
