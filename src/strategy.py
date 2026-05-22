import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Tuple

from src.models import Trade, Position, Signal
from src.exchange import Exchange
from src.storage import Storage
from src.notifier import FeishuNotifier
from src.blacklist import BlacklistManager

logger = logging.getLogger(__name__)


class TradingStrategy:
    def __init__(
        self,
        config: dict,
        exchange: Exchange,
        storage: Storage,
        notifier: FeishuNotifier,
        blacklist_manager: BlacklistManager,
    ):
        self.config = config
        self.exchange = exchange
        self.storage = storage
        self.notifier = notifier
        self.blacklist_manager = blacklist_manager

        self.positions: Dict[str, Position] = {}
        self.cooldowns: Dict[str, datetime] = {}

        trading_cfg = config.get("trading", {})
        self.buy_amount_usdt = trading_cfg.get("buy_amount_usdt", 100)
        self.price_increase_threshold = trading_cfg.get("price_increase_threshold", 0.05)
        self.volume_multiplier = trading_cfg.get("volume_multiplier", 2.0)
        self.trailing_stop_activation = trading_cfg.get("trailing_stop_activation", 0.05)
        self.trailing_stop_drop = trading_cfg.get("trailing_stop_drop", 0.02)
        self.time_stop_loss_minutes = trading_cfg.get("time_stop_loss_minutes", 3)
        self.cooldown_minutes = trading_cfg.get("cooldown_minutes", 5)

        limits_cfg = config.get("limits", {})
        self.max_daily_trades = limits_cfg.get("max_daily_trades", 50)
        self.max_daily_loss_usdt = limits_cfg.get("max_daily_loss_usdt", 500)

        self.filter_list = config.get("filter_list", [])

    def scan_signals(self):
        """Scan all alpha symbols for trading signals."""
        try:
            symbols = self.exchange.get_all_alpha_symbols()
        except Exception as e:
            logger.error("Failed to get alpha symbols: %s", str(e))
            return

        for symbol in symbols:
            try:
                klines = self.exchange.get_klines(symbol, "1m", 7)
                if not klines or len(klines) < 7:
                    continue

                # Check the second-to-last candle (last closed candle, index -2)
                signal_candle = klines[-2]
                # kline format: [timestamp, open, high, low, close, volume]
                candle_open = signal_candle[1]
                candle_close = signal_candle[4]
                candle_volume = signal_candle[5]

                if candle_open <= 0:
                    continue

                price_change = (candle_close - candle_open) / candle_open

                if price_change >= self.price_increase_threshold:
                    # Calculate average volume of candles at index -7 to -3 (5 candles)
                    volume_candles = klines[-7:-2]
                    avg_volume = sum(c[5] for c in volume_candles) / len(volume_candles) if volume_candles else 0

                    if avg_volume > 0 and candle_volume > self.volume_multiplier * avg_volume:
                        signal = Signal(
                            symbol=symbol,
                            candle_open=candle_open,
                            candle_close=candle_close,
                            candle_volume=candle_volume,
                            avg_volume=avg_volume,
                            price_change_pct=price_change * 100,
                            timestamp=datetime.now(),
                        )

                        can_enter, reason = self.check_entry_conditions(symbol)
                        if can_enter:
                            self.execute_buy(signal)
                        else:
                            logger.debug(
                                "Signal for %s rejected: %s", symbol, reason
                            )

            except Exception as e:
                logger.error("Error scanning %s: %s", symbol, str(e))
                continue

    def check_entry_conditions(self, symbol: str) -> Tuple[bool, str]:
        """Check if all entry conditions are met for a symbol."""
        # Not in filter list
        if symbol in self.filter_list:
            return False, "symbol in filter_list"

        # Not blacklisted
        if self.blacklist_manager.is_blacklisted(symbol):
            return False, "symbol is blacklisted"

        # Not in cooldown
        if symbol in self.cooldowns:
            cooldown_end = self.cooldowns[symbol] + timedelta(minutes=self.cooldown_minutes)
            if datetime.now() < cooldown_end:
                return False, "symbol in cooldown"

        # Not already holding position
        if symbol in self.positions:
            return False, "already holding position"

        # Daily trade count check
        trade_count = self.storage.get_trade_count_today()
        if trade_count >= self.max_daily_trades:
            return False, "max daily trades reached"

        # Daily PnL check
        daily_pnl = self.storage.get_daily_pnl()
        if daily_pnl <= -self.max_daily_loss_usdt:
            return False, "daily loss limit reached"

        return True, ""

    def manage_positions(self):
        """Manage all open positions - check trailing stop and time-based stop."""
        symbols_to_close = []

        for symbol, position in self.positions.items():
            try:
                current_price = self.exchange.get_ticker_price(symbol)
                if current_price is None:
                    continue

                # Update highest price
                if current_price > position.highest_price:
                    position.highest_price = current_price

                # Check trailing stop activation
                activation_price = position.entry_price * (1 + self.trailing_stop_activation)
                if current_price >= activation_price:
                    position.trailing_stop_active = True
                    position.trailing_stop_price = position.highest_price * (1 - self.trailing_stop_drop)

                # Check trailing stop trigger
                if position.trailing_stop_active and current_price <= position.trailing_stop_price:
                    symbols_to_close.append((symbol, "trailing_stop"))
                    continue

                # Time-based stop-loss (only if trailing stop not active)
                elapsed = datetime.now() - position.entry_time
                if elapsed >= timedelta(minutes=self.time_stop_loss_minutes) and not position.trailing_stop_active:
                    symbols_to_close.append((symbol, "time_stop_loss"))

            except Exception as e:
                logger.error("Error managing position %s: %s", symbol, str(e))
                continue

        # Execute sells outside of iteration
        for symbol, reason in symbols_to_close:
            position = self.positions.get(symbol)
            if position:
                self.execute_sell(position, reason)

    def execute_buy(self, signal: Signal):
        """Execute a buy order based on a signal."""
        try:
            order = self.exchange.place_market_buy(signal.symbol, self.buy_amount_usdt)

            fill_price = order.get("average") or order.get("price") or signal.candle_close
            quantity = order.get("filled") or order.get("amount") or (self.buy_amount_usdt / fill_price)
            amount = fill_price * quantity

            trade = Trade(
                id=str(uuid.uuid4()),
                symbol=signal.symbol,
                side="buy",
                price=fill_price,
                quantity=quantity,
                amount=amount,
                timestamp=datetime.now(),
                status="filled",
            )

            self.storage.record_trade(trade)

            position = Position(
                symbol=signal.symbol,
                entry_price=fill_price,
                quantity=quantity,
                amount=amount,
                entry_time=datetime.now(),
                highest_price=fill_price,
            )
            self.positions[signal.symbol] = position

            # Set cooldown
            self.cooldowns[signal.symbol] = datetime.now()

            # Notify
            self.notifier.send_trade_notification({
                "side": "buy",
                "symbol": signal.symbol,
                "price": fill_price,
                "quantity": quantity,
                "amount": amount,
            })

            logger.info(
                "BUY %s: price=%.8f, qty=%.8f, amount=%.2f USDT",
                signal.symbol,
                fill_price,
                quantity,
                amount,
            )

        except Exception as e:
            logger.error("Failed to execute buy for %s: %s", signal.symbol, str(e))

    def execute_sell(self, position: Position, reason: str):
        """Execute a sell order for a position."""
        try:
            order = self.exchange.place_market_sell(position.symbol, position.quantity)

            sell_price = order.get("average") or order.get("price") or 0
            quantity = position.quantity
            profit_loss = (sell_price - position.entry_price) * quantity
            profit_loss_pct = ((sell_price - position.entry_price) / position.entry_price) * 100 if position.entry_price > 0 else 0

            trade = Trade(
                id=str(uuid.uuid4()),
                symbol=position.symbol,
                side="sell",
                price=sell_price,
                quantity=quantity,
                amount=sell_price * quantity,
                timestamp=datetime.now(),
                profit_loss=profit_loss,
                status="filled",
            )

            self.storage.record_trade(trade, reason=reason)

            # Remove from positions
            if position.symbol in self.positions:
                del self.positions[position.symbol]

            # Update blacklist
            if profit_loss < 0:
                self.blacklist_manager.record_loss(position.symbol)
            else:
                self.blacklist_manager.record_win(position.symbol)

            # Notify
            self.notifier.send_trade_notification({
                "side": "sell",
                "symbol": position.symbol,
                "price": sell_price,
                "quantity": quantity,
                "profit_loss": profit_loss,
                "profit_loss_pct": profit_loss_pct,
                "reason": reason,
            })

            logger.info(
                "SELL %s: price=%.8f, qty=%.8f, P/L=%.2f USDT (%.2f%%), reason=%s",
                position.symbol,
                sell_price,
                quantity,
                profit_loss,
                profit_loss_pct,
                reason,
            )

        except Exception as e:
            logger.error("Failed to execute sell for %s: %s", position.symbol, str(e))
