"""Config loader with Pydantic validation."""
from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field, field_validator


class KronosConfig(BaseModel):
    model_id: str = "NeoQuasar/Kronos-small"
    pred_len: int = 4
    threshold_pct: float = 0.5
    device: str = "cpu"


class IndicatorsConfig(BaseModel):
    rsi_length: int = 14
    atr_length: int = 14
    volume_ma_length: int = 20
    vwap_min_candles: int = 5


class LongFilter(BaseModel):
    rsi_min: float = 40.0
    rsi_max: float = 70.0
    require_price_above_vwap: bool = True
    volume_ratio_min: float = 1.2


class ShortFilter(BaseModel):
    rsi_min: float = 30.0
    rsi_max: float = 60.0
    require_price_below_vwap: bool = True
    volume_ratio_min: float = 1.2


class FiltersConfig(BaseModel):
    long: LongFilter = Field(default_factory=LongFilter)
    short: ShortFilter = Field(default_factory=ShortFilter)


class RiskConfig(BaseModel):
    account_size_usd: float = 10000.0
    risk_per_trade_pct: float = 0.01
    max_position_usd: float = 2000.0
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    min_rr_ratio: float = 1.5

    @field_validator("risk_per_trade_pct")
    def risk_pct_range(cls, v):
        if not (0 < v <= 1):
            raise ValueError("risk_per_trade_pct must be in (0, 1]")
        return v


class CircuitBreakersConfig(BaseModel):
    max_daily_loss_pct: float = 0.03
    max_consecutive_losses: int = 4
    cooldown_minutes: int = 120

    @field_validator("max_daily_loss_pct")
    def daily_loss_range(cls, v):
        if not (0 < v <= 1):
            raise ValueError("max_daily_loss_pct must be in (0, 1]")
        return v


class DedupConfig(BaseModel):
    cooldown_candles: int = 4
    price_tolerance_pct: float = 0.005


class SchedulerConfig(BaseModel):
    cycle_seconds: int = 900
    symbol_delay_seconds: int = 2


class TelegramConfig(BaseModel):
    parse_mode: str = "HTML"
    send_no_signal: bool = False
    send_daily_summary: bool = True
    summary_hour_utc: int = 0


class Config(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: ["BTC"])
    timeframe: str = "15m"
    lookback_candles: int = 150
    kronos: KronosConfig = Field(default_factory=KronosConfig)
    indicators: IndicatorsConfig = Field(default_factory=IndicatorsConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    circuit_breakers: CircuitBreakersConfig = Field(default_factory=CircuitBreakersConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


def load_config(path: Path = Path("config/settings.yaml")) -> Config:
    with open(path, "r") as f:
        raw = yaml.safe_load(f)
    return Config(**raw)