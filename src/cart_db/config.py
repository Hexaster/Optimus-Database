"""集中配置：只从环境变量读，密钥不进代码库。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Attempt this operation while preserving the explicit recovery/cleanup paths below.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv 可选
    pass

ROOT = Path(__file__).resolve().parents[2]

# ---------- LLM 计价口径 ----------
# 方案《六、本阶段成本预算》按 Claude Sonnet 5 测算：
#   输入 ¥20.2 / M token，输出 ¥101 / M token
# 缓存读约为输入价的 0.1×，缓存写约 1.25×（Anthropic 官方口径）
PRICE_INPUT_CNY_PER_MTOK = 20.2
PRICE_OUTPUT_CNY_PER_MTOK = 101.0
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


@dataclass(frozen=True)
class Settings:
    # 数据库
    pg_host: str = os.getenv("PGHOST", "localhost")
    pg_port: int = int(os.getenv("PGPORT", "5432"))
    pg_database: str = os.getenv("PGDATABASE", "cart")
    pg_user: str = os.getenv("PGUSER", "cart")
    pg_password: str = os.getenv("PGPASSWORD", "")

    # LLM —— API key 现在可以留空，本地建库不需要它
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    # Treat a missing or empty API key as unconfigured.
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    # Treat a missing or empty provider URL as unconfigured.
    openai_base_url: str | None = os.getenv("OPENAI_BASE_URL") or None
    llm_model: str = os.getenv("CART_LLM_MODEL", "claude-sonnet-5")
    llm_effort: str = os.getenv("CART_LLM_EFFORT", "high")
    llm_daily_cap_cny: float = float(os.getenv("CART_LLM_DAILY_CAP_CNY", "800"))

    # Jev document classification uses OpenRouter's Decisions API.
    openrouter_api_key: str | None = os.getenv("OPENROUTER_API_KEY") or None
    jev_model: str = os.getenv("CART_JEV_MODEL", "typesafe/jev-1.14")

    # 存储
    data_root: Path = Path(os.getenv("CART_DATA_ROOT", str(ROOT / "data")))

    # Build the legacy libpq connection string from local PG settings; do not log this value.
    @property
    def dsn(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_database} "
            f"user={self.pg_user} password={self.pg_password}"
        )

    @property
    def llm_ready(self) -> bool:
        """API key 未配置时返回 False —— 冒烟测试据此标为「待配置」而非失败。"""
        return bool(self.anthropic_api_key)


settings = Settings()


def cost_cny(input_tokens: int, output_tokens: int,
             cache_read: int = 0, cache_write: int = 0) -> float:
    """按方案预算口径折算人民币成本。"""
    return round(
        input_tokens  / 1e6 * PRICE_INPUT_CNY_PER_MTOK
        + output_tokens / 1e6 * PRICE_OUTPUT_CNY_PER_MTOK
        + cache_read  / 1e6 * PRICE_INPUT_CNY_PER_MTOK * CACHE_READ_MULTIPLIER
        + cache_write / 1e6 * PRICE_INPUT_CNY_PER_MTOK * CACHE_WRITE_MULTIPLIER,
        4,
    )
