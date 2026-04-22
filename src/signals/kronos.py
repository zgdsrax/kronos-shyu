"""
Kronos model wrapper — singleton predictor for the Kronos transformer model.

The model is loaded ONCE at startup and reused for all subsequent predictions.
This module provides an adapter that:
1. Loads the KronosTokenizer and Kronos model from HuggingFace
2. Wraps them in the existing KronosPredictor class from the kronos-shyu repo
3. Exposes a simple `predict(df) -> KronosResult` interface

The actual model code is in `kronos_model.py` (copied from kronos-shyu/model/kronos.py).
"""
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import torch

logger = logging.getLogger("kronos_bot.signals.kronos")

# Import the model classes from the copied kronos_model
from . import kronos_model as _km

__all__ = ["KronosPredictor", "KronosResult"]


@dataclass(frozen=True)
class KronosResult:
    """
    Result from a single Kronos prediction call.

    Attributes
    ----------
    signal : str
        "UP" if predicted price change exceeds threshold upward,
        "DOWN" if predicted change exceeds threshold downward,
        "NEUTRAL" otherwise.
    predicted_close : Optional[float]
        The predicted close price (mean across samples), or None if unavailable.
    change_pct : float
        Predicted percentage change in the close price (single source of truth).
    confidence : float
        Absolute value of change_pct (higher = more confident).
    """

    signal: str  # "UP" | "DOWN" | "NEUTRAL"
    predicted_close: Optional[float]
    change_pct: float
    confidence: float


class KronosPredictor:
    """
    Singleton wrapper around KronosTokenizer + Kronos model.

    Model is loaded once at first instantiation. Subsequent instantiations
    return the same instance (singleton pattern).

    The wrapped predictor (KronosPredictor from kronos-shyu) takes a DataFrame
    of OHLCV data and returns a prediction DataFrame. We post-process that
    to produce a KronosResult.
    """

    _instance: Optional["KronosPredictor"] = None
    _loaded: bool = False

    def __new__(cls, config) -> "KronosPredictor":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
            cls._instance._tokenizer = None
            cls._instance._predictor = None
            cls._instance._config = None
        return cls._instance

    def load(self, config) -> None:
        """
        Load the Kronos model and tokenizer from HuggingFace.

        Called once at bot startup. Safe to call multiple times (idempotent).

        Parameters
        ----------
        config : KronosConfig
            Model configuration (model_id, device, pred_len, threshold_pct).
        """
        if KronosPredictor._loaded:
            logger.info("Kronos model already loaded — skipping")
            return

        logger.info("Loading Kronos model — one-time initialization")
        try:
            model_id = config.model_id
            device_str = config.device or "cpu"
            device = torch.device(device_str)

            logger.info("  Downloading tokenizer and model from HuggingFace: %s", model_id)
            self._tokenizer: "_km.KronosTokenizer" = _km.KronosTokenizer.from_pretrained(
                model_id, cache_dir=os.environ.get("HF_HOME")
            )
            self._model: "_km.Kronos" = _km.Kronos.from_pretrained(
                model_id, cache_dir=os.environ.get("HF_HOME")
            )

            self._tokenizer.to(device)
            self._model.to(device)
            self._model.eval()

            # Wrap in the existing KronosPredictor from kronos-shyu
            self._predictor = _km.KronosPredictor(
                model=self._model,
                tokenizer=self._tokenizer,
                device=device_str,
            )

            self._config = config
            KronosPredictor._loaded = True
            logger.info("  Kronos model loaded successfully on %s", device)

        except Exception as exc:
            logger.critical("Kronos model load failed: %s", exc)
            raise SystemExit(1) from exc

    def predict(self, df: pd.DataFrame) -> KronosResult:
        """
        Run a prediction on the given OHLCV DataFrame.

        Uses the last `lookback` candles for context, forecasts `pred_len` candles
        ahead, then computes the percentage change from the last actual close.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain columns: open, high, low, close, volume.
            Index is timestamps (DatetimeIndex or datetime column).

        Returns
        -------
        KronosResult
            signal: "UP" | "DOWN" | "NEUTRAL"
            predicted_close: mean predicted close price
            change_pct: percentage change vs last actual close
            confidence: absolute change_pct
        """
        if not KronosPredictor._loaded:
            raise RuntimeError("Kronos model not loaded — call load() first")

        config = self._config
        lookback = config.pred_len * 10  # use enough history for the model

        # Slice lookback from the end
        if len(df) < lookback:
            logger.warning(
                "Kronos predict: df has %d rows, need %d — using all available",
                len(df),
                lookback,
            )
            price_df = df.tail(lookback).copy()
        else:
            price_df = df.tail(lookback).copy()

        # Ensure required columns exist
        required_cols = {"open", "high", "low", "close", "volume"}
        missing = required_cols - set(price_df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {missing}")

        # Handle missing volume/amount columns
        if "amount" not in price_df.columns:
            price_df["amount"] = price_df["volume"] * price_df[["open", "close"]].mean(axis=1)

        # Build timestamp indices
        if not isinstance(price_df.index, pd.DatetimeIndex):
            if "timestamp" in price_df.columns:
                price_df = price_df.set_index("timestamp")
            else:
                raise ValueError("DataFrame must have a DatetimeIndex or 'timestamp' column")

        x_timestamp = price_df.index

        # Future timestamps for prediction (same frequency as input)
        freq = "15min"  # standard for hyperliquid
        y_timestamp = pd.date_range(
            start=x_timestamp[-1] + pd.Timedelta(freq),
            periods=config.pred_len,
            freq=freq,
        )

        # Run prediction
        pred_df: pd.DataFrame = self._predictor.predict(
            price_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=config.pred_len,
            T=1.0,
            top_k=0,
            top_p=0.9,
            sample_count=1,
            verbose=False,
        )

        # Compute change_pct from last actual close
        last_close = float(df["close"].iloc[-1])
        pred_close = float(pred_df["close"].iloc[-1])
        change_pct = ((pred_close - last_close) / last_close) * 100.0
        confidence = abs(change_pct)

        # Classify signal
        threshold = config.threshold_pct
        if change_pct > threshold:
            signal = "UP"
        elif change_pct < -threshold:
            signal = "DOWN"
        else:
            signal = "NEUTRAL"

        return KronosResult(
            signal=signal,
            predicted_close=pred_close,
            change_pct=change_pct,
            confidence=confidence,
        )

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (used in tests)."""
        cls._instance = None
        cls._loaded = False