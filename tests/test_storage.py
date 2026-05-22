import os
import tempfile
from datetime import datetime, timedelta

import pytest

from src.models import Position, Trade
from src.storage import Storage
from src.blacklist import BlacklistManager


def make_storage(tmp_path):
    """Create a storage instance backed by a temp SQLite file."""
    db_path = os.path.join(tmp_path, "test.db")
    config = {"database": {"path": db_path}}
    storage = Storage(config)
    storage.initialize()
    return storage


class TestPositionPersistence:
    def test_save_and_load_position(self, tmp_path):
        """save_position persists fields and load_positions restores them."""
        storage = make_storage(tmp_path)

        position = Position(
            symbol="TEST/USDT",
            entry_price=1.5,
            quantity=66.67,
            amount=100.0,
            entry_time=datetime(2025, 1, 15, 10, 30, 0),
            highest_price=1.65,
            trailing_stop_active=True,
            trailing_stop_price=1.617,
        )
        storage.save_position(position)

        loaded = storage.load_positions()
        assert len(loaded) == 1
        p = loaded[0]
        assert p.symbol == "TEST/USDT"
        assert p.entry_price == 1.5
        assert p.quantity == 66.67
        assert p.amount == 100.0
        assert p.entry_time == datetime(2025, 1, 15, 10, 30, 0)
        assert p.highest_price == 1.65
        assert p.trailing_stop_active is True
        assert abs(p.trailing_stop_price - 1.617) < 0.0001

    def test_save_position_updates_existing(self, tmp_path):
        """Saving a position with the same symbol updates it (INSERT OR REPLACE)."""
        storage = make_storage(tmp_path)

        position = Position(
            symbol="UPD/USDT",
            entry_price=2.0,
            quantity=50.0,
            amount=100.0,
            entry_time=datetime(2025, 1, 15, 10, 0, 0),
            highest_price=2.0,
        )
        storage.save_position(position)

        # Update highest_price and trailing stop
        position.highest_price = 2.2
        position.trailing_stop_active = True
        position.trailing_stop_price = 2.156
        storage.save_position(position)

        loaded = storage.load_positions()
        assert len(loaded) == 1
        assert loaded[0].highest_price == 2.2
        assert loaded[0].trailing_stop_active is True
        assert abs(loaded[0].trailing_stop_price - 2.156) < 0.0001

    def test_delete_position(self, tmp_path):
        """delete_position removes the position from the database."""
        storage = make_storage(tmp_path)

        position = Position(
            symbol="DEL/USDT",
            entry_price=1.0,
            quantity=100.0,
            amount=100.0,
            entry_time=datetime(2025, 1, 15, 12, 0, 0),
            highest_price=1.0,
        )
        storage.save_position(position)

        loaded = storage.load_positions()
        assert len(loaded) == 1

        storage.delete_position("DEL/USDT")

        loaded = storage.load_positions()
        assert len(loaded) == 0

    def test_delete_nonexistent_position(self, tmp_path):
        """Deleting a symbol that doesn't exist does not raise an error."""
        storage = make_storage(tmp_path)
        storage.delete_position("NOPE/USDT")  # should not raise

    def test_load_positions_empty(self, tmp_path):
        """load_positions returns empty list when no positions saved."""
        storage = make_storage(tmp_path)
        loaded = storage.load_positions()
        assert loaded == []

    def test_multiple_positions(self, tmp_path):
        """Multiple positions can be saved and loaded."""
        storage = make_storage(tmp_path)

        for i, sym in enumerate(["AAA/USDT", "BBB/USDT", "CCC/USDT"]):
            pos = Position(
                symbol=sym,
                entry_price=1.0 + i * 0.1,
                quantity=100.0,
                amount=100.0,
                entry_time=datetime(2025, 1, 15, 10, i, 0),
                highest_price=1.0 + i * 0.1,
            )
            storage.save_position(pos)

        loaded = storage.load_positions()
        assert len(loaded) == 3
        symbols = {p.symbol for p in loaded}
        assert symbols == {"AAA/USDT", "BBB/USDT", "CCC/USDT"}


class TestRecentTradedSymbols:
    def test_get_recent_traded_symbols(self, tmp_path):
        """get_recent_traded_symbols returns distinct symbols with sell trades."""
        storage = make_storage(tmp_path)

        # Record some sell trades with profit_loss set
        for symbol, pnl in [("SYM1/USDT", -5.0), ("SYM2/USDT", 10.0), ("SYM1/USDT", -3.0)]:
            trade = Trade(
                id=f"t-{symbol}-{pnl}",
                symbol=symbol,
                side="sell",
                price=1.0,
                quantity=100.0,
                amount=100.0,
                timestamp=datetime.now(),
                profit_loss=pnl,
                status="filled",
            )
            storage.record_trade(trade)

        # Also record a buy trade (should not appear)
        buy_trade = Trade(
            id="t-buy",
            symbol="SYM3/USDT",
            side="buy",
            price=1.0,
            quantity=100.0,
            amount=100.0,
            timestamp=datetime.now(),
            status="filled",
        )
        storage.record_trade(buy_trade)

        symbols = storage.get_recent_traded_symbols()
        assert "SYM1/USDT" in symbols
        assert "SYM2/USDT" in symbols
        assert "SYM3/USDT" not in symbols  # buy-only, no sell with profit_loss

    def test_get_recent_traded_symbols_empty(self, tmp_path):
        """Returns empty list when no sell trades exist."""
        storage = make_storage(tmp_path)
        symbols = storage.get_recent_traded_symbols()
        assert symbols == []


class TestSeedFromStorage:
    def test_seed_from_storage_loads_loss_counts(self, tmp_path):
        """seed_from_storage correctly pre-loads consecutive loss counts."""
        storage = make_storage(tmp_path)

        # Create trade history: SYM1 has 2 consecutive losses, SYM2 has 1
        trades = [
            Trade(id="t1", symbol="SYM1/USDT", side="sell", price=1.0, quantity=100.0,
                  amount=100.0, timestamp=datetime(2025, 1, 15, 10, 0, 0),
                  profit_loss=-5.0, status="filled"),
            Trade(id="t2", symbol="SYM1/USDT", side="sell", price=1.0, quantity=100.0,
                  amount=100.0, timestamp=datetime(2025, 1, 15, 10, 5, 0),
                  profit_loss=-3.0, status="filled"),
            Trade(id="t3", symbol="SYM2/USDT", side="sell", price=1.0, quantity=100.0,
                  amount=100.0, timestamp=datetime(2025, 1, 15, 10, 0, 0),
                  profit_loss=10.0, status="filled"),
            Trade(id="t4", symbol="SYM2/USDT", side="sell", price=1.0, quantity=100.0,
                  amount=100.0, timestamp=datetime(2025, 1, 15, 10, 5, 0),
                  profit_loss=-2.0, status="filled"),
        ]
        for trade in trades:
            storage.record_trade(trade)

        # Seed blacklist manager
        bm = BlacklistManager({"consecutive_losses": 2, "duration_minutes": 30})
        bm.seed_from_storage(storage)

        # SYM1 has 2 consecutive losses -> blacklisted
        assert bm.is_blacklisted("SYM1/USDT")
        # SYM2 has only 1 consecutive loss -> not blacklisted
        assert not bm.is_blacklisted("SYM2/USDT")

    def test_seed_from_storage_no_trades(self, tmp_path):
        """seed_from_storage handles empty trade history gracefully."""
        storage = make_storage(tmp_path)

        bm = BlacklistManager({"consecutive_losses": 2, "duration_minutes": 30})
        bm.seed_from_storage(storage)

        assert bm.get_blacklisted_symbols() == []

    def test_seed_from_storage_propagates_errors(self):
        """seed_from_storage re-raises exceptions from storage."""
        from unittest.mock import Mock

        broken_storage = Mock()
        broken_storage.get_recent_traded_symbols.side_effect = RuntimeError("DB error")

        bm = BlacklistManager({"consecutive_losses": 2, "duration_minutes": 30})
        with pytest.raises(RuntimeError, match="DB error"):
            bm.seed_from_storage(broken_storage)
