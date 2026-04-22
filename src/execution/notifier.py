"""Telegram notifier — sends formatted HTML alerts."""
import os
import logging
from typing import Optional

import requests

from config.loader import TelegramConfig, Config
from src.signals.composer import TradeSignal

logger = logging.getLogger("kronos_bot.execution.notifier")


class TelegramNotifier:
    """
    Sends formatted alerts to Telegram using the Bot API.

    Messages are sent in HTML format with full trade context.
    Supports signal alerts, trade outcome notifications, and daily summaries.
    """

    _BOT_TOKEN: Optional[str] = None
    _CHAT_ID: Optional[str] = None

    def __init__(self, config: Config):
        self.config = config.telegram
        self._bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not self._bot_token or not self._chat_id:
            logger.warning(
                "Telegram credentials not set (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID). "
                "Notifications will be logged but NOT sent."
            )

    @property
    def _base_url(self) -> str:
        return f"https://api.telegram.org/bot{self._bot_token}/sendMessage"

    def _send(self, text: str, disable_notification: bool = False) -> bool:
        """Internal HTTP POST to Telegram API."""
        if not self._bot_token or not self._chat_id:
            logger.info("[TELEGRAM (mock)] %s", text)
            return True

        try:
            resp = requests.post(
                self._base_url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": self.config.parse_mode,
                    "disable_notification": disable_notification,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.error("Telegram send failed: %s", exc)
            return False

    def send_signal(self, signal: TradeSignal) -> None:
        """
        Send a trade signal alert to Telegram.

        Parameters
        ----------
        signal : TradeSignal
        """
        direction_emoji = "🟢" if signal.direction.value == "LONG" else "🔴"
        direction_word = signal.direction.value.capitalize()

        text = (
            f"<b>{direction_emoji} KRONOS SIGNAL — {signal.symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Direction:</b> {direction_word}\n"
            f"<b>Entry:</b> {signal.entry_price:.4f}\n"
            f"<b>Stop Loss:</b> {signal.sl:.4f}\n"
            f"<b>Take Profit:</b> {signal.tp:.4f}\n"
            f"<b>Risk/Reward:</b> 1:{signal.rr_ratio:.1f}\n"
            f"\n"
            f"<b>Position Size:</b> {signal.position_size_contracts:.4f} contracts\n"
            f"<b>Risk:</b> ${signal.risk_usd:.2f}\n"
            f"{'[CAPPED] ' if signal.position_size_contracts > 0 else ''}"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Indicators</b>\n"
            f"  RSI: {signal.rsi:.1f}\n"
            f"  VWAP: {signal.vwap:.4f}\n"
            f"  ATR: {signal.atr:.4f}\n"
            f"  Vol Ratio: {signal.volume_ratio:.2f}\n"
            f"\n"
            f"<b>Kronos</b>\n"
            f"  Signal: {signal.kronos_signal}\n"
            f"  Predicted Δ: {signal.kronos_change_pct:+.3f}%\n"
            f"\n"
            f"<i>{signal.timestamp}</i>"
        )

        self._send(text)
        logger.info("[%s] Signal notification sent", signal.symbol)

    def send_outcome(self, outcome: dict) -> None:
        """
        Send a trade outcome notification (SL or TP hit).

        Parameters
        ----------
        outcome : dict with keys: symbol, result, pnl_pct
        """
        symbol = outcome.get("symbol", "?")
        result = outcome.get("result", "?")  # "TP" or "SL"
        pnl_pct = outcome.get("pnl_pct", 0.0)

        result_emoji = "✅" if result == "TP" else "❌"
        pnl_str = f"{pnl_pct * 100:+.2f}%"

        text = (
            f"{result_emoji} <b>TRADE CLOSED — {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Result:</b> {result}\n"
            f"<b>P&amp;L:</b> {pnl_str}\n"
        )

        self._send(text, disable_notification=False)
        logger.info("[%s] Outcome notification sent: %s %s", symbol, result, pnl_str)

    def send_daily_summary(self, stats: dict) -> None:
        """
        Send a daily performance summary.

        Parameters
        ----------
        stats : dict with keys: total_trades, win_rate, expectancy_pct,
               sharpe_ratio, max_drawdown_pct, total_return_pct, avg_rr
        """
        total_trades = stats.get("total_trades", 0)
        if total_trades == 0:
            return  # nothing to summarize

        text = (
            f"<b>📊 KRONOS DAILY SUMMARY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Trades:</b> {total_trades}\n"
            f"<b>Win Rate:</b> {stats.get('win_rate', 0):.1%}\n"
            f"<b>Avg R:R:</b> {stats.get('avg_rr', 0):.2f}\n"
            f"<b>Expectancy:</b> {stats.get('expectancy_pct', 0):.2%}/trade\n"
            f"<b>Total Return:</b> {stats.get('total_return_pct', 0):+.2%}\n"
            f"<b>Max Drawdown:</b> {stats.get('max_drawdown_pct', 0):.1%}\n"
            f"<b>Sharpe:</b> {stats.get('sharpe_ratio', 0):.2f}\n"
        )

        self._send(text, disable_notification=True)
        logger.info("Daily summary notification sent")

    def send_circuit_breaker_alert(self, reason: str) -> None:
        """Send an alert when the circuit breaker halts the bot."""
        text = (
            f"🛑 <b>CIRCUIT BREAKER TRIGGERED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Reason:</b> {reason}\n"
            f"<b>Action:</b> Bot halted. Will auto-resume after cooldown.\n"
        )
        self._send(text, disable_notification=False)
        logger.warning("Circuit breaker alert sent: %s", reason)