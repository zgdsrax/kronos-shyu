"""Hyperliquid OHLCV fetcher with retry logic."""
from datetime import datetime
from typing import Dict, List, Optional

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
    retry_if_exception_type,
)

from .schemas import Candle, OHLCVFrame

# Hyperliquid candle endpoint
_BASE_URL = "https://api.hyperliquid.xyz"


logger: Optional[object] = None  # injected at runtime


def _set_logger():
    global logger
    if logger is None:
        import logging
        logger = logging.getLogger("kronos_bot.data")


class HyperliquidFetcher:
    """
    Fetches OHLCV candles from Hyperliquid with retry logic and validation.
    """

    def __init__(
        self,
        symbols: List[str],
        timeframe: str = "15m",
        lookback: int = 150,
    ):
        self.symbols = symbols
        self.timeframe = timeframe
        self.lookback = lookback
        self._failure_counts: Dict[str, int] = {}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type((requests.RequestException, ValueError)),
        reraise=True,
    )
    def _fetch_raw(self, symbol: str) -> dict:
        """
        Raw fetch — raises on failure so tenacity can retry.
        """
        url = f"{_BASE_URL}/candles"
        params = {
            "symbol": symbol,
            "interval": self.timeframe,
            "num": self.lookback,
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            raise requests.RequestException(f"HTTP {resp.status_code}")
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"Unexpected response type for {symbol}: {type(data)}")
        return {"symbol": symbol, "candles": data}

    def fetch(self, symbol: str) -> Optional[OHLCVFrame]:
        """
        Fetch candles for one symbol. Returns None on final failure.
        """
        import logging
        log = logging.getLogger("kronos_bot.data")

        try:
            raw = self._fetch_raw(symbol)
        except Exception as exc:
            log.error("[%s] Fetch failed after 3 retries: %s", symbol, exc)
            self._failure_counts[symbol] = self._failure_counts.get(symbol, 0) + 1
            return None

        candles: List[Candle] = []
        for raw_c in raw["candles"]:
            try:
                # Hyperliquid returns [timestamp, open, high, low, close, volume]
                ts_ms = raw_c[0]
                candles.append(
                    Candle(
                        timestamp=datetime.utcfromtimestamp(ts_ms / 1000),
                        open=float(raw_c[1]),
                        high=float(raw_c[2]),
                        low=float(raw_c[3]),
                        close=float(raw_c[4]),
                        volume=float(raw_c[5]),
                    )
                )
            except (IndexError, ValueError) as exc:
                log.warning("[%s] Skipping malformed candle %s: %s", symbol, raw_c, exc)
                continue

        if not candles:
            log.error("[%s] No valid candles after parsing", symbol)
            return None

        self._failure_counts[symbol] = 0
        return OHLCVFrame(symbol=symbol, timeframe=self.timeframe, candles=candles)

    def fetch_all(self) -> Dict[str, Optional[OHLCVFrame]]:
        """
        Fetch all configured symbols with per-symbol error isolation.
        """
        results: Dict[str, Optional[OHLCVFrame]] = {}
        for sym in self.symbols:
            results[sym] = self.fetch(sym)
        return results

    @property
    def failure_count(self) -> Dict[str, int]:
        return dict(self._failure_counts)