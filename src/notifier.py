import logging
import time
from typing import Dict, Any

import requests

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1.0


class FeishuNotifier:
    def __init__(self, config: dict):
        feishu_config = config.get("feishu", {})
        self._webhook_url = feishu_config.get("webhook_url", "")

        drop_alert_config = config.get("drop_alert", {})
        self._drop_alert_webhook_url = drop_alert_config.get("feishu_webhook_url", "")

    def _send_card_to_url(self, card: Dict[str, Any], webhook_url: str):
        """Send a Feishu interactive card message to a specific webhook URL with retry logic."""
        if not webhook_url:
            logger.warning("Feishu webhook URL not configured, skipping notification")
            return

        payload = {
            "msg_type": "interactive",
            "card": card,
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(
                    webhook_url, json=payload, timeout=10
                )
                response.raise_for_status()
                logger.debug("Feishu notification sent successfully")
                return
            except requests.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        "Feishu notification failed (attempt %d/%d): %s",
                        attempt + 1,
                        MAX_RETRIES,
                        str(e),
                    )
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error(
                        "Feishu notification failed after %d retries: %s",
                        MAX_RETRIES,
                        str(e),
                    )

    def _send_card(self, card: Dict[str, Any]):
        """Send a Feishu interactive card message with retry logic."""
        self._send_card_to_url(card, self._webhook_url)

    def send_trade_notification(self, trade_data: dict):
        """Send a buy/sell trade notification via Feishu webhook."""
        side = trade_data.get("side", "unknown").upper()

        if side == "BUY":
            elements = [
                {"tag": "div", "text": {"tag": "plain_text", "content": f"Symbol: {trade_data.get('symbol', '')}"}},
                {"tag": "div", "text": {"tag": "plain_text", "content": f"Price: {trade_data.get('price', 0):.8f}"}},
                {"tag": "div", "text": {"tag": "plain_text", "content": f"Quantity: {trade_data.get('quantity', 0):.8f}"}},
                {"tag": "div", "text": {"tag": "plain_text", "content": f"Amount: {trade_data.get('amount', 0):.2f} USDT"}},
            ]
            header_title = f"BUY - {trade_data.get('symbol', '')}"
            header_color = "green"
        else:
            profit_loss = trade_data.get("profit_loss", 0)
            profit_loss_pct = trade_data.get("profit_loss_pct", 0)
            pnl_sign = "+" if profit_loss >= 0 else ""
            elements = [
                {"tag": "div", "text": {"tag": "plain_text", "content": f"Symbol: {trade_data.get('symbol', '')}"}},
                {"tag": "div", "text": {"tag": "plain_text", "content": f"Price: {trade_data.get('price', 0):.8f}"}},
                {"tag": "div", "text": {"tag": "plain_text", "content": f"Quantity: {trade_data.get('quantity', 0):.8f}"}},
                {"tag": "div", "text": {"tag": "plain_text", "content": f"P/L: {pnl_sign}{profit_loss:.2f} USDT ({pnl_sign}{profit_loss_pct:.2f}%)"}},
                {"tag": "div", "text": {"tag": "plain_text", "content": f"Reason: {trade_data.get('reason', '')}"}},
            ]
            header_color = "green" if profit_loss >= 0 else "red"
            header_title = f"SELL - {trade_data.get('symbol', '')}"

        card = {
            "header": {
                "title": {"tag": "plain_text", "content": header_title},
                "template": header_color,
            },
            "elements": elements,
        }

        self._send_card(card)

    def send_daily_summary(self, summary: dict):
        """Send daily summary card via Feishu webhook."""
        total_trades = summary.get("total_trades", 0)
        winning_trades = summary.get("winning_trades", 0)
        losing_trades = summary.get("losing_trades", 0)
        total_pnl = summary.get("total_pnl", 0.0)
        win_rate = summary.get("win_rate", 0.0)

        pnl_sign = "+" if total_pnl >= 0 else ""

        elements = [
            {"tag": "div", "text": {"tag": "plain_text", "content": f"Total Trades: {total_trades}"}},
            {"tag": "div", "text": {"tag": "plain_text", "content": f"Winning Trades: {winning_trades}"}},
            {"tag": "div", "text": {"tag": "plain_text", "content": f"Losing Trades: {losing_trades}"}},
            {"tag": "div", "text": {"tag": "plain_text", "content": f"Total P/L: {pnl_sign}{total_pnl:.2f} USDT"}},
            {"tag": "div", "text": {"tag": "plain_text", "content": f"Win Rate: {win_rate:.1f}%"}},
        ]

        card = {
            "header": {
                "title": {"tag": "plain_text", "content": "Daily Trading Summary"},
                "template": "blue",
            },
            "elements": elements,
        }

        self._send_card(card)

    def send_drop_alert(self, alert_data: dict):
        """Send a sharp drop alert card to the drop alert webhook.

        Args:
            alert_data: dict with keys: level, symbol, price, drop_pct, volume, timestamp
        """
        level = alert_data.get("level", "Warning")
        symbol = alert_data.get("symbol", "")
        price = alert_data.get("price", 0)
        drop_pct = alert_data.get("drop_pct", 0)
        volume = alert_data.get("volume", 0)
        timestamp = alert_data.get("timestamp", "")

        if level == "Critical":
            header_color = "red"
            header_title = f"Critical Drop Alert - {symbol}"
        else:
            header_color = "yellow"
            header_title = f"Warning Drop Alert - {symbol}"

        elements = [
            {"tag": "div", "text": {"tag": "plain_text", "content": f"Alert Level: {level}"}},
            {"tag": "div", "text": {"tag": "plain_text", "content": f"Symbol: {symbol}"}},
            {"tag": "div", "text": {"tag": "plain_text", "content": f"Current Price: {price:.8f}"}},
            {"tag": "div", "text": {"tag": "plain_text", "content": f"1-min Drop: {drop_pct:.2f}%"}},
            {"tag": "div", "text": {"tag": "plain_text", "content": f"Volume: {volume:.2f}"}},
            {"tag": "div", "text": {"tag": "plain_text", "content": f"Timestamp: {timestamp}"}},
        ]

        card = {
            "header": {
                "title": {"tag": "plain_text", "content": header_title},
                "template": header_color,
            },
            "elements": elements,
        }

        self._send_card_to_url(card, self._drop_alert_webhook_url)
