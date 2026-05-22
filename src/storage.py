import sqlite3
import os
import logging
from datetime import datetime, date
from typing import List, Optional

from src.models import Trade

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, config: dict):
        db_path = config.get("database", {}).get("path", "data/trades.db")
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self):
        """Create database tables if they don't exist."""
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    amount REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    profit_loss REAL,
                    status TEXT NOT NULL DEFAULT 'open',
                    reason TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    date TEXT PRIMARY KEY,
                    total_trades INTEGER NOT NULL DEFAULT 0,
                    total_pnl REAL NOT NULL DEFAULT 0.0,
                    winning_trades INTEGER NOT NULL DEFAULT 0,
                    losing_trades INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.commit()
            logger.info("Database initialized at %s", self.db_path)
        finally:
            conn.close()

    def record_trade(self, trade: Trade, reason: str = None):
        """Insert a trade record into the database."""
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO trades (id, symbol, side, price, quantity, amount, timestamp, profit_loss, status, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.id,
                    trade.symbol,
                    trade.side,
                    trade.price,
                    trade.quantity,
                    trade.amount,
                    trade.timestamp.isoformat(),
                    trade.profit_loss,
                    trade.status,
                    reason,
                ),
            )
            conn.commit()
            logger.info("Recorded trade %s for %s", trade.id, trade.symbol)
        finally:
            conn.close()

    def get_trades_today(self) -> List[dict]:
        """Return all trades from today."""
        conn = self._get_connection()
        try:
            today_str = date.today().isoformat()
            cursor = conn.execute(
                "SELECT * FROM trades WHERE timestamp >= ?",
                (today_str,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_daily_pnl(self) -> float:
        """Return sum of profit_loss for today."""
        conn = self._get_connection()
        try:
            today_str = date.today().isoformat()
            cursor = conn.execute(
                "SELECT COALESCE(SUM(profit_loss), 0) as total FROM trades WHERE timestamp >= ?",
                (today_str,),
            )
            row = cursor.fetchone()
            return float(row["total"]) if row else 0.0
        finally:
            conn.close()

    def get_consecutive_losses(self, symbol: str) -> int:
        """Return count of most recent consecutive losing trades for a symbol."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT profit_loss FROM trades
                WHERE symbol = ? AND side = 'sell' AND profit_loss IS NOT NULL
                ORDER BY timestamp DESC
                """,
                (symbol,),
            )
            count = 0
            for row in cursor.fetchall():
                if row["profit_loss"] < 0:
                    count += 1
                else:
                    break
            return count
        finally:
            conn.close()

    def get_trade_count_today(self) -> int:
        """Return number of trades today."""
        conn = self._get_connection()
        try:
            today_str = date.today().isoformat()
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM trades WHERE timestamp >= ?",
                (today_str,),
            )
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0
        finally:
            conn.close()

    def get_all_trades_in_range(self, start: datetime, end: datetime) -> List[dict]:
        """Return all trades in a given time range."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM trades WHERE timestamp >= ? AND timestamp <= ?",
                (start.isoformat(), end.isoformat()),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
