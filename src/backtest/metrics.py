"""
Backtest performance metrics.

Computes: Sharpe, Sortino, max drawdown, win rate, avg R:R ratio, profit factor,
expectancy, total return.
"""
from typing import List, Dict, Union

import numpy as np
import pandas as pd

from .engine import TradeRecord

__all__ = ["compute_metrics"]


def compute_metrics(trades: List[TradeRecord]) -> Dict[str, Union[float, str, int]]:
    """
    Compute performance metrics from a list of TradeRecord objects.

    Parameters
    ----------
    trades : List[TradeRecord]

    Returns
    -------
    dict
        Keys:
        - total_trades (int)
        - win_rate (float, 0–1)
        - avg_win_pct (float, fraction)
        - avg_loss_pct (float, fraction, negative)
        - avg_rr (float)
        - profit_factor (float, inf if no losses)
        - max_drawdown_pct (float, negative)
        - sharpe_ratio (float)
        - sortino_ratio (float)
        - expectancy_pct (float, fraction per trade)
        - total_return_pct (float, fraction)
        - win_count (int)
        - loss_count (int)
        - error (str) if no trades
    """
    if not trades:
        return {"error": "no trades in backtest result"}

    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Equity curve
    equity = pd.Series(pnls).add(1).cumprod()
    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax

    # Annualization factor for 15-min candles (96 candles per trading day)
    annualization = np.sqrt(252 * 96)

    # Sharpe
    mean_pnl = np.mean(pnls)
    std_pnl = np.std(pnls, ddof=1)
    sharpe = (mean_pnl / std_pnl) * annualization if std_pnl > 0 else 0.0

    # Sortino (downside deviation)
    downside = [p for p in pnls if p < 0]
    downside_std = np.std(downside, ddof=1) if len(downside) > 1 else 0.0
    sortino = (mean_pnl / downside_std) * annualization if downside_std > 0 else 0.0

    # Win/loss stats
    win_rate = len(wins) / len(pnls)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    avg_rr = abs(avg_win / avg_loss) if losses and avg_loss != 0 else 0.0

    # Profit factor
    total_wins = sum(wins)
    total_losses = abs(sum(losses)) if losses else 0.0
    profit_factor = float("inf") if total_losses == 0 else total_wins / total_losses

    return {
        "total_trades": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(win_rate, 4),
        "avg_win_pct": round(avg_win, 6),
        "avg_loss_pct": round(avg_loss, 6),
        "avg_rr": round(avg_rr, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else float("inf"),
        "max_drawdown_pct": round(float(drawdown.min()), 6),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "expectancy_pct": round(mean_pnl, 6),
        "total_return_pct": round(float(equity.iloc[-1] - 1), 6),
    }