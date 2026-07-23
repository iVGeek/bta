from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import json
import os


class ExchangeConfig(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Webhook
    webhook_host: str = Field(default="0.0.0.0", alias="WEBHOOK_HOST")
    webhook_port: int = Field(default=8080, alias="WEBHOOK_PORT")
    webhook_secret: str = Field(default="secret", alias="WEBHOOK_SECRET")

    # Binance
    binance_api_key: str = Field(default="", alias="BINANCE_API_KEY")
    binance_api_secret: str = Field(default="", alias="BINANCE_API_SECRET")
    binance_testnet: bool = Field(default=True, alias="BINANCE_TESTNET")

    # Bybit
    bybit_api_key: str = Field(default="", alias="BYBIT_API_KEY")
    bybit_api_secret: str = Field(default="", alias="BYBIT_API_SECRET")
    bybit_testnet: bool = Field(default=True, alias="BYBIT_TESTNET")

    # OKX
    okx_api_key: str = Field(default="", alias="OKX_API_KEY")
    okx_api_secret: str = Field(default="", alias="OKX_API_SECRET")
    okx_passphrase: str = Field(default="", alias="OKX_PASSPHRASE")
    okx_testnet: bool = Field(default=True, alias="OKX_TESTNET")

    # Bitget
    bitget_api_key: str = Field(default="", alias="BITGET_API_KEY")
    bitget_api_secret: str = Field(default="", alias="BITGET_API_SECRET")
    bitget_passphrase: str = Field(default="", alias="BITGET_PASSPHRASE")
    bitget_testnet: bool = Field(default=True, alias="BITGET_TESTNET")

    # Gate.io
    gate_api_key: str = Field(default="", alias="GATE_API_KEY")
    gate_api_secret: str = Field(default="", alias="GATE_API_SECRET")

    # Risk
    max_position_pct: float = Field(default=5.0, alias="MAX_POSITION_PCT")
    max_daily_trades: int = Field(default=20, alias="MAX_DAILY_TRADES")
    max_daily_loss_pct: float = Field(default=10.0, alias="MAX_DAILY_LOSS_PCT")
    default_leverage: int = Field(default=1, alias="DEFAULT_LEVERAGE")

    # Active exchanges (comma-separated)
    active_exchanges: str = Field(default="binance", alias="ACTIVE_EXCHANGES")
    default_exchange: str = Field(default="binance", alias="DEFAULT_EXCHANGE")

    # Mode
    dry_run: bool = Field(default=True, alias="DRY_RUN")

    def get_exchange_list(self) -> list[str]:
        return [e.strip() for e in self.active_exchanges.split(",") if e.strip()]

    def has_exchange(self, name: str) -> bool:
        return name.lower() in self.get_exchange_list()
