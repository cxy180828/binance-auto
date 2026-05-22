import logging
import time
from typing import List, Optional, Dict, Any

import ccxt

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1.0


class Exchange:
    def __init__(self, config: dict):
        binance_config = config.get("binance", {})
        api_key = binance_config.get("api_key", "")
        secret = binance_config.get("secret", "")
        testnet = binance_config.get("testnet", True)

        exchange_params = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        }

        if testnet:
            exchange_params["options"] = {
                "defaultType": "spot",
            }
            exchange_params["urls"] = {
                "api": {
                    "public": "https://testnet.binance.vision/api",
                    "private": "https://testnet.binance.vision/api",
                },
            }

        self.exchange = ccxt.binance(exchange_params)

        if testnet:
            self.exchange.set_sandbox_mode(True)

        self.testnet = testnet
        logger.info(
            "Exchange initialized (testnet=%s)", testnet
        )

    def _retry(self, func, *args, **kwargs):
        """Retry a function call on transient errors."""
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except (
                ccxt.NetworkError,
                ccxt.RequestTimeout,
                ccxt.ExchangeNotAvailable,
            ) as e:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        "Transient error (attempt %d/%d): %s",
                        attempt + 1,
                        MAX_RETRIES,
                        str(e),
                    )
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    logger.error("Max retries reached: %s", str(e))
                    raise

    def get_klines(
        self, symbol: str, timeframe: str = "1m", limit: int = 10
    ) -> List[List]:
        """Fetch OHLCV candles for a symbol.

        Returns list of [timestamp, open, high, low, close, volume].
        """
        try:
            ohlcv = self._retry(
                self.exchange.fetch_ohlcv, symbol, timeframe, limit=limit
            )
            return ohlcv
        except ccxt.BaseError as e:
            logger.error("Failed to fetch klines for %s: %s", symbol, str(e))
            raise

    def get_all_alpha_symbols(self) -> List[str]:
        """Get all USDT trading pairs as a proxy for Alpha tokens."""
        try:
            self._retry(self.exchange.load_markets)
            symbols = [
                s
                for s in self.exchange.symbols
                if s.endswith("/USDT") and self.exchange.markets[s].get("active", True)
            ]
            logger.info("Found %d USDT pairs", len(symbols))
            return symbols
        except ccxt.BaseError as e:
            logger.error("Failed to load markets: %s", str(e))
            raise

    def place_market_buy(self, symbol: str, usdt_amount: float) -> Dict[str, Any]:
        """Place a market buy order for a given USDT amount."""
        try:
            ticker = self._retry(self.exchange.fetch_ticker, symbol)
            price = ticker["last"]
            if not price or price <= 0:
                raise ValueError(f"Invalid price for {symbol}: {price}")

            quantity = usdt_amount / price
            order = self._retry(
                self.exchange.create_market_buy_order, symbol, quantity
            )
            logger.info(
                "Market buy %s: quantity=%.8f, usdt_amount=%.2f",
                symbol,
                quantity,
                usdt_amount,
            )
            return order
        except ccxt.BaseError as e:
            logger.error("Failed to place market buy for %s: %s", symbol, str(e))
            raise

    def place_market_sell(self, symbol: str, quantity: float) -> Dict[str, Any]:
        """Place a market sell order for a given quantity."""
        try:
            order = self._retry(
                self.exchange.create_market_sell_order, symbol, quantity
            )
            logger.info("Market sell %s: quantity=%.8f", symbol, quantity)
            return order
        except ccxt.BaseError as e:
            logger.error("Failed to place market sell for %s: %s", symbol, str(e))
            raise

    def get_ticker_price(self, symbol: str) -> Optional[float]:
        """Get the current price for a symbol."""
        try:
            ticker = self._retry(self.exchange.fetch_ticker, symbol)
            return ticker.get("last")
        except ccxt.BaseError as e:
            logger.error("Failed to get ticker for %s: %s", symbol, str(e))
            raise
