"""Pydantic schemas for OHLCV data."""
from datetime import datetime
from typing import List

import pandas as pd
from pydantic import BaseModel, Field, field_validator


class Candle(BaseModel):
    """Single OHLCV candle."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator("high")
    @classmethod
    def high_gte_low(cls, v: float, info) -> float:
        if "low" in info.data and v < info.data["low"]:
            raise ValueError("high must be >= low")
        return v

    @field_validator("open", "close")
    @classmethod
    def price_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price must be positive")
        return v


class OHLCVFrame(BaseModel):
    """Collection of candles for one symbol/timeframe."""

    symbol: str
    timeframe: str
    candles: List[Candle] = Field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert to pandas DataFrame sorted by timestamp ascending."""
        rows = [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in self.candles
        ]
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.sort_values("timestamp").reset_index(drop=True)

    @property
    def latest_price(self) -> float:
        if not self.candles:
            raise RuntimeError("No candles in frame")
        return self.candles[-1].close