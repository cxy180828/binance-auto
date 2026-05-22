from datetime import datetime, timedelta
from unittest.mock import patch

from src.blacklist import BlacklistManager


class TestBlacklistManager:
    def _make_manager(self, consecutive_losses=2, duration_minutes=30):
        return BlacklistManager({
            "consecutive_losses": consecutive_losses,
            "duration_minutes": duration_minutes,
        })

    def test_consecutive_loss_tracking_triggers_blacklist(self):
        """Two consecutive losses triggers blacklist."""
        bm = self._make_manager(consecutive_losses=2)
        bm.record_loss("BTC/USDT")
        assert not bm.is_blacklisted("BTC/USDT")

        bm.record_loss("BTC/USDT")
        assert bm.is_blacklisted("BTC/USDT")

    def test_win_resets_counter(self):
        """A win resets the loss counter so next loss starts from 0."""
        bm = self._make_manager(consecutive_losses=2)
        bm.record_loss("ETH/USDT")
        bm.record_win("ETH/USDT")
        bm.record_loss("ETH/USDT")
        assert not bm.is_blacklisted("ETH/USDT")

    def test_auto_expiry_after_duration(self):
        """Blacklist entry expires after configured duration."""
        bm = self._make_manager(consecutive_losses=2, duration_minutes=30)
        bm.record_loss("SOL/USDT")
        bm.record_loss("SOL/USDT")
        assert bm.is_blacklisted("SOL/USDT")

        # Simulate time passing beyond duration
        past_time = datetime.now() - timedelta(minutes=31)
        bm._blacklist["SOL/USDT"] = past_time

        assert not bm.is_blacklisted("SOL/USDT")

    def test_not_blacklisted_returns_false(self):
        """Symbols not in blacklist return False."""
        bm = self._make_manager()
        assert not bm.is_blacklisted("DOGE/USDT")
        assert not bm.is_blacklisted("XRP/USDT")

    def test_get_blacklisted_symbols(self):
        """Returns list of currently blacklisted symbols."""
        bm = self._make_manager(consecutive_losses=2)
        bm.record_loss("AAA/USDT")
        bm.record_loss("AAA/USDT")
        bm.record_loss("BBB/USDT")
        bm.record_loss("BBB/USDT")

        blacklisted = bm.get_blacklisted_symbols()
        assert "AAA/USDT" in blacklisted
        assert "BBB/USDT" in blacklisted

    def test_get_blacklisted_symbols_removes_expired(self):
        """get_blacklisted_symbols removes expired entries."""
        bm = self._make_manager(consecutive_losses=2, duration_minutes=30)
        bm.record_loss("OLD/USDT")
        bm.record_loss("OLD/USDT")

        # Expire it
        bm._blacklist["OLD/USDT"] = datetime.now() - timedelta(minutes=31)

        blacklisted = bm.get_blacklisted_symbols()
        assert "OLD/USDT" not in blacklisted

    def test_three_losses_threshold(self):
        """Custom threshold of 3 consecutive losses."""
        bm = self._make_manager(consecutive_losses=3)
        bm.record_loss("TEST/USDT")
        bm.record_loss("TEST/USDT")
        assert not bm.is_blacklisted("TEST/USDT")

        bm.record_loss("TEST/USDT")
        assert bm.is_blacklisted("TEST/USDT")
