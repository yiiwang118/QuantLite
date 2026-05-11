"""统一配置。所有模块通过 settings 取，不要散落读环境变量。"""
from datetime import date
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 服务
    host: str = "0.0.0.0"
    port: int = 8000

    # 路径
    data_cache_dir: Path = Path("data_cache")
    quant_db: Path = Path("quant.db")
    users_yaml: Path = Path("users.yaml")
    frontend_dist: Path = Path("frontend/dist")

    # 数据
    initial_start_date: date = date(2018, 1, 1)

    # 跨域
    cors_allow_origins: str = "*"

    # 日志
    log_level: str = "INFO"

    # AI 模块（NL → DSL）
    ai_provider: str = "anthropic"            # anthropic | openai | none
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-20241022"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # 定时拉取
    schedule_enabled: bool = True
    schedule_tz: str = "Asia/Shanghai"
    # CN: 工作日 18:00 拉（A 股 15:00 收盘 + 缓冲）
    schedule_cn_universes: str = "cn:sample"
    schedule_cn_hour: int = 18
    schedule_cn_minute: int = 0
    # US: 次日工作日 06:00 拉（美股 16:00 ET 收盘 = 北京 04:00-05:00 + 缓冲）
    schedule_us_universes: str = "us:sample"
    schedule_us_hour: int = 6
    schedule_us_minute: int = 0


settings = Settings()
