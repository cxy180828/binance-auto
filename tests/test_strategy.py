from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

import pytest

from src.blacklist import BlacklistManager
from src.models import Position, Signal
from src.notifier import FeishuNotifier
from src.strategy import TradingStrategy


def make_config():
    return {
        "trading": {
            "buy_amount_usdt": 100,
            "price_increase_threshold": 0.05,
            "trailing_stop_activation": 0.05,
            "trailing_stop_drop": 0.02,
            "time_stop_loss_minutes": 3,
            "volume_multiplier": 2.0,
            "cooldown_minutes": 5,
        },
        "limits": {
            "max_daily_trades": 50,
            "max_daily_loss_usdt": 500,
        },
        "filter_list": ["SCAM/USDT"],
        "blacklist": {
            "consecutive_losses": 2,
            "duration_minutes": 30,
        },
    }


def make_strategy(config=None):
    """Create strategy with mocked dependencies."""
    config = config or make_config()
    exchange = Mock()
    storage = Mock()
    storage.load_positions.return_value = []
    notifier = Mock()
    blacklist_manager = BlacklistManager(config.get("blacklist", {}))

    strategy = TradingStrategy(config, exchange, storage, notifier, blacklist_manager)
    return strategy, exchange, storage, notifier, blacklist_manager


class TestSignalDetection:
    def test_signal_detected_with_sufficient_increase_and_volume(self):
        """Signal should be detected when price increase > 5% and volume > 2x average."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        # Create klines: 7 candles, format [timestamp, open, high, low, close, volume]
        # Candles -7 to -3 (index 0-4): avg volume = 100
        # Candle -2 (index 5): 6% increase, volume 250 (> 2 * 100)
        # Candle -1 (index 6): current (not checked)
        klines = [
            [1000, 1.0, 1.1, 0.9, 1.05, 100],  # -7
            [2000, 1.0, 1.1, 0.9, 1.02, 100],  # -6
            [3000, 1.0, 1.1, 0.9, 1.03, 100],  # -5
            [4000, 1.0, 1.1, 0.9, 1.01, 100],  # -4
            [5000, 1.0, 1.1, 0.9, 1.04, 100],  # -3
            [6000, 1.0, 1.1, 0.9, 1.06, 250],  # -2 (signal: 6% increase, 2.5x volume)
            [7000, 1.06, 1.1, 1.0, 1.07, 50],  # -1 (current, not checked)
        ]

        exchange.get_all_alpha_symbols.return_value = ["TEST/USDT"]
        exchange.get_klines.return_value = klines
        exchange.place_market_buy.return_value = {
            "average": 1.06, "filled": 94.34, "amount": 94.34
        }
        storage.get_trade_count_today.return_value = 0
        storage.get_daily_pnl.return_value = 0.0

        strategy.scan_signals()

        exchange.place_market_buy.assert_called_once()

    def test_signal_rejected_volume_too_low(self):
        """Signal rejected when volume is below threshold."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        # Signal candle has 6% increase but volume only 150 (< 2 * 100)
        klines = [
            [1000, 1.0, 1.1, 0.9, 1.05, 100],
            [2000, 1.0, 1.1, 0.9, 1.02, 100],
            [3000, 1.0, 1.1, 0.9, 1.03, 100],
            [4000, 1.0, 1.1, 0.9, 1.01, 100],
            [5000, 1.0, 1.1, 0.9, 1.04, 100],
            [6000, 1.0, 1.1, 0.9, 1.06, 150],  # volume 150 < 2 * 100
            [7000, 1.06, 1.1, 1.0, 1.07, 50],
        ]

        exchange.get_all_alpha_symbols.return_value = ["TEST/USDT"]
        exchange.get_klines.return_value = klines

        strategy.scan_signals()

        exchange.place_market_buy.assert_not_called()

    def test_signal_rejected_price_increase_too_small(self):
        """Signal rejected when price increase is below threshold."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        # Signal candle has only 3% increase
        klines = [
            [1000, 1.0, 1.1, 0.9, 1.05, 100],
            [2000, 1.0, 1.1, 0.9, 1.02, 100],
            [3000, 1.0, 1.1, 0.9, 1.03, 100],
            [4000, 1.0, 1.1, 0.9, 1.01, 100],
            [5000, 1.0, 1.1, 0.9, 1.04, 100],
            [6000, 1.0, 1.1, 0.9, 1.03, 300],  # only 3% increase
            [7000, 1.03, 1.1, 1.0, 1.04, 50],
        ]

        exchange.get_all_alpha_symbols.return_value = ["TEST/USDT"]
        exchange.get_klines.return_value = klines

        strategy.scan_signals()

        exchange.place_market_buy.assert_not_called()


class TestTrailingStop:
    def test_trailing_stop_activates_and_triggers_sell(self):
        """Position rises 5%, trailing activates, then drops 2% triggers sell."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        position = Position(
            symbol="TEST/USDT",
            entry_price=1.0,
            quantity=100.0,
            amount=100.0,
            entry_time=datetime.now(),
            highest_price=1.0,
        )
        strategy.positions["TEST/USDT"] = position

        # Price rises to 1.06 (6% above entry) - activates trailing stop
        exchange.get_ticker_price.return_value = 1.06
        exchange.place_market_sell.return_value = {"average": 1.06, "filled": 100.0}
        storage.record_trade = Mock()

        strategy.manage_positions()

        # Trailing stop should be active now
        assert strategy.positions["TEST/USDT"].trailing_stop_active is True
        assert strategy.positions["TEST/USDT"].highest_price == 1.06
        # trailing_stop_price = 1.06 * (1 - 0.02) = 1.0388
        assert abs(strategy.positions["TEST/USDT"].trailing_stop_price - 1.0388) < 0.0001

        # Price hasn't dropped below trailing stop yet
        exchange.place_market_sell.assert_not_called()

        # Now price drops to 1.03 (below trailing_stop_price of 1.0388)
        exchange.get_ticker_price.return_value = 1.03
        exchange.place_market_sell.return_value = {"average": 1.03, "filled": 100.0}

        strategy.manage_positions()

        exchange.place_market_sell.assert_called_once_with("TEST/USDT", 100.0)

    def test_trailing_stop_updates_highest_price(self):
        """Highest price tracks upward movement."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        position = Position(
            symbol="TEST/USDT",
            entry_price=1.0,
            quantity=100.0,
            amount=100.0,
            entry_time=datetime.now(),
            highest_price=1.0,
        )
        strategy.positions["TEST/USDT"] = position

        # Price goes to 1.08
        exchange.get_ticker_price.return_value = 1.08
        strategy.manage_positions()

        assert strategy.positions["TEST/USDT"].highest_price == 1.08
        # trailing_stop_price = 1.08 * 0.98 = 1.0584
        assert abs(strategy.positions["TEST/USDT"].trailing_stop_price - 1.0584) < 0.0001


class TestTimeStopLoss:
    def test_time_stop_loss_triggers_after_elapsed_time(self):
        """Position sold after time_stop_loss_minutes if trailing stop not active."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        # Position entered 4 minutes ago (> 3 minute limit), price hasn't risen 5%
        position = Position(
            symbol="TEST/USDT",
            entry_price=1.0,
            quantity=100.0,
            amount=100.0,
            entry_time=datetime.now() - timedelta(minutes=4),
            highest_price=1.03,
        )
        strategy.positions["TEST/USDT"] = position

        # Current price is 1.02 (below 5% activation threshold)
        exchange.get_ticker_price.return_value = 1.02
        exchange.place_market_sell.return_value = {"average": 1.02, "filled": 100.0}

        strategy.manage_positions()

        exchange.place_market_sell.assert_called_once_with("TEST/USDT", 100.0)

    def test_time_stop_loss_does_not_trigger_if_trailing_active(self):
        """Time stop does not apply if trailing stop is already active."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        # Position entered 4 minutes ago but trailing stop is active
        position = Position(
            symbol="TEST/USDT",
            entry_price=1.0,
            quantity=100.0,
            amount=100.0,
            entry_time=datetime.now() - timedelta(minutes=4),
            highest_price=1.06,
            trailing_stop_active=True,
            trailing_stop_price=1.0388,
        )
        strategy.positions["TEST/USDT"] = position

        # Price is above trailing stop price
        exchange.get_ticker_price.return_value = 1.05
        strategy.manage_positions()

        exchange.place_market_sell.assert_not_called()


class TestCooldown:
    def test_cooldown_enforcement(self):
        """Cannot buy same symbol within cooldown period."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        # Set cooldown for TEST/USDT 2 minutes ago (within 5 min cooldown)
        strategy.cooldowns["TEST/USDT"] = datetime.now() - timedelta(minutes=2)

        can_enter, reason = strategy.check_entry_conditions("TEST/USDT")
        assert can_enter is False
        assert "cooldown" in reason

    def test_cooldown_expired_allows_entry(self):
        """Can buy symbol after cooldown period expires."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        # Set cooldown 6 minutes ago (beyond 5 min cooldown)
        strategy.cooldowns["TEST/USDT"] = datetime.now() - timedelta(minutes=6)
        storage.get_trade_count_today.return_value = 0
        storage.get_daily_pnl.return_value = 0.0

        can_enter, reason = strategy.check_entry_conditions("TEST/USDT")
        assert can_enter is True


class TestDailyLimits:
    def test_max_daily_trades_enforcement(self):
        """Won't buy after max trades reached."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        storage.get_trade_count_today.return_value = 50

        can_enter, reason = strategy.check_entry_conditions("TEST/USDT")
        assert can_enter is False
        assert "max daily trades" in reason

    def test_daily_loss_limit_enforcement(self):
        """Won't buy after loss limit hit."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        storage.get_trade_count_today.return_value = 5
        storage.get_daily_pnl.return_value = -500.0

        can_enter, reason = strategy.check_entry_conditions("TEST/USDT")
        assert can_enter is False
        assert "daily loss limit" in reason


class TestEntryConditions:
    def test_filter_list_blocks_entry(self):
        """Symbols in filter_list cannot be entered."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        can_enter, reason = strategy.check_entry_conditions("SCAM/USDT")
        assert can_enter is False
        assert "filter_list" in reason

    def test_blacklisted_symbol_blocks_entry(self):
        """Blacklisted symbol cannot be entered."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        bm.record_loss("BAN/USDT")
        bm.record_loss("BAN/USDT")

        can_enter, reason = strategy.check_entry_conditions("BAN/USDT")
        assert can_enter is False
        assert "blacklisted" in reason

    def test_already_holding_blocks_entry(self):
        """Cannot enter a position already held."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        strategy.positions["TEST/USDT"] = Position(
            symbol="TEST/USDT",
            entry_price=1.0,
            quantity=100.0,
            amount=100.0,
            entry_time=datetime.now(),
            highest_price=1.0,
        )

        can_enter, reason = strategy.check_entry_conditions("TEST/USDT")
        assert can_enter is False
        assert "already holding" in reason

    def test_max_open_positions_blocks_entry(self):
        """Cannot enter when max open positions limit is reached."""
        config = make_config()
        config["limits"]["max_open_positions"] = 2
        strategy, exchange, storage, notifier, bm = make_strategy(config)

        # Fill up to the limit
        strategy.positions["AAA/USDT"] = Position(
            symbol="AAA/USDT",
            entry_price=1.0,
            quantity=100.0,
            amount=100.0,
            entry_time=datetime.now(),
            highest_price=1.0,
        )
        strategy.positions["BBB/USDT"] = Position(
            symbol="BBB/USDT",
            entry_price=1.0,
            quantity=100.0,
            amount=100.0,
            entry_time=datetime.now(),
            highest_price=1.0,
        )

        can_enter, reason = strategy.check_entry_conditions("CCC/USDT")
        assert can_enter is False
        assert "max open positions" in reason

    def test_below_max_open_positions_allows_entry(self):
        """Can enter when below max open positions limit."""
        config = make_config()
        config["limits"]["max_open_positions"] = 3
        strategy, exchange, storage, notifier, bm = make_strategy(config)

        strategy.positions["AAA/USDT"] = Position(
            symbol="AAA/USDT",
            entry_price=1.0,
            quantity=100.0,
            amount=100.0,
            entry_time=datetime.now(),
            highest_price=1.0,
        )

        storage.get_trade_count_today.return_value = 0
        storage.get_daily_pnl.return_value = 0.0

        can_enter, reason = strategy.check_entry_conditions("CCC/USDT")
        assert can_enter is True

    def test_all_conditions_pass(self):
        """All conditions met allows entry."""
        strategy, exchange, storage, notifier, bm = make_strategy()

        storage.get_trade_count_today.return_value = 0
        storage.get_daily_pnl.return_value = 0.0

        can_enter, reason = strategy.check_entry_conditions("NEW/USDT")
        assert can_enter is True
        assert reason == ""
