import logging
import os
import time
from typing import List, Optional, Dict, Any

import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1.0

ALPHA_SYMBOL_LIST_URL = "https://www.binance.com/bapi/composite/v1/public/market/alpha/symbol/list"
ALPHA_MARKET_LIST_URL = "https://www.binance.com/gateway-api/v1/public/market/alpha/list"


class Exchange:
    def __init__(self, config: dict):
        binance_config = config.get("binance", {})
        api_key = os.environ.get("BINANCE_API_KEY") or binance_config.get("api_key", "")
        secret = os.environ.get("BINANCE_SECRET") or binance_config.get("secret", "")
        testnet = binance_config.get("testnet", True)

        self.client = Client(api_key, secret)

        if testnet:
            self.client.API_URL = 'https://testnet.binance.vision/api'

        self.testnet = testnet
        self.config = config

        # Alpha symbols cache
        alpha_cfg = config.get("alpha", {})
        self.alpha_cache_minutes = alpha_cfg.get("cache_minutes", 10)
        self.alpha_symbols_cache: List[str] = []
        self.alpha_symbols_cache_time: float = 0

        logger.info(
            "Exchange initialized (testnet=%s)", testnet
        )

    def _retry(self, func, *args, **kwargs):
        """Retry a function call on transient errors."""
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except (
                BinanceRequestException,
                ConnectionError,
                TimeoutError,
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
            raw_klines = self._retry(
                self.client.get_klines, symbol=symbol, interval=timeframe, limit=limit
            )
            # python-binance returns lists with many fields; extract the first 6
            # Format: [open_time, open, high, low, close, volume, ...]
            result = []
            for k in raw_klines:
                result.append([
                    k[0],           # timestamp (open time)
                    float(k[1]),    # open
                    float(k[2]),    # high
                    float(k[3]),    # low
                    float(k[4]),    # close
                    float(k[5]),    # volume
                ])
            return result
        except BinanceAPIException as e:
            logger.error("Failed to fetch klines for %s: %s", symbol, str(e))
            raise

    def fetch_alpha_symbols(self) -> List[str]:
        """Fetch Binance Alpha market token list from web API with caching."""
        # Check cache validity
        cache_ttl = self.alpha_cache_minutes * 60
        if self.alpha_symbols_cache and (time.time() - self.alpha_symbols_cache_time) < cache_ttl:
            return self.alpha_symbols_cache

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
        }

        symbols: List[str] = []

        # Try primary endpoint
        try:
            resp = requests.post(
                ALPHA_SYMBOL_LIST_URL,
                headers=headers,
                json={},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Response may contain data.data or data directly as a list
                token_list = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(token_list, list):
                    for item in token_list:
                        if isinstance(item, str):
                            name = item.upper()
                        elif isinstance(item, dict):
                            name = (item.get("symbol") or item.get("name") or "").upper()
                        else:
                            continue
                        if not name:
                            continue
                        pair = name if name.endswith("USDT") else name + "USDT"
                        symbols.append(pair)
                if symbols:
                    logger.info("Fetched %d Alpha symbols from primary endpoint", len(symbols))
                    self.alpha_symbols_cache = symbols
                    self.alpha_symbols_cache_time = time.time()
                    return symbols
        except Exception as e:
            logger.warning("Primary Alpha endpoint failed: %s", str(e))

        # Try fallback endpoint
        try:
            resp = requests.get(
                ALPHA_MARKET_LIST_URL,
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                token_list = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(token_list, list):
                    for item in token_list:
                        if isinstance(item, str):
                            name = item.upper()
                        elif isinstance(item, dict):
                            name = (item.get("symbol") or item.get("name") or "").upper()
                        else:
                            continue
                        if not name:
                            continue
                        pair = name if name.endswith("USDT") else name + "USDT"
                        symbols.append(pair)
                if symbols:
                    logger.info("Fetched %d Alpha symbols from fallback endpoint", len(symbols))
                    self.alpha_symbols_cache = symbols
                    self.alpha_symbols_cache_time = time.time()
                    return symbols
        except Exception as e:
            logger.warning("Fallback Alpha endpoint failed: %s", str(e))

        logger.warning("All Alpha API endpoints failed, returning empty list")
        return []

    def get_all_alpha_symbols(self) -> List[str]:
        """Get Binance Alpha market token symbols.

        Tries to fetch from Binance Alpha API first. If that fails,
        falls back to scan_symbols from config. If both are empty,
        logs a warning.
        """
        symbols = self.fetch_alpha_symbols()
        if symbols:
            logger.info("Found %d Alpha symbols", len(symbols))
            return symbols

        # Fallback to scan_symbols from config
        scan_symbols = self.config.get("scan_symbols", [])
        if scan_symbols:
            logger.info("Found %d symbols (fallback to scan_symbols)", len(scan_symbols))
            return scan_symbols

        logger.warning("No Alpha symbols available: API failed and scan_symbols is empty")
        return []

    def place_market_buy(self, symbol: str, usdt_amount: float) -> Dict[str, Any]:
        """Place a market buy order for a given USDT amount."""
        try:
            order = self._retry(
                self.client.order_market_buy,
                symbol=symbol,
                quoteOrderQty=usdt_amount,
            )
            # Calculate average fill price from fills
            fills = order.get("fills", [])
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                total_cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
                avg_price = total_cost / total_qty if total_qty > 0 else 0
            else:
                total_qty = float(order.get("executedQty", 0))
                total_cost = float(order.get("cummulativeQuoteQty", 0))
                avg_price = total_cost / total_qty if total_qty > 0 else 0

            logger.info(
                "Market buy %s: quantity=%.8f, usdt_amount=%.2f",
                symbol,
                total_qty,
                usdt_amount,
            )
            return {
                "average": avg_price,
                "filled": total_qty,
                "amount": total_qty,
            }
        except BinanceAPIException as e:
            logger.error("Failed to place market buy for %s: %s", symbol, str(e))
            raise

    def place_market_sell(self, symbol: str, quantity: float) -> Dict[str, Any]:
        """Place a market sell order for a given quantity."""
        try:
            order = self._retry(
                self.client.order_market_sell,
                symbol=symbol,
                quantity=quantity,
            )
            # Calculate average fill price from fills
            fills = order.get("fills", [])
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                total_cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
                avg_price = total_cost / total_qty if total_qty > 0 else 0
            else:
                total_qty = float(order.get("executedQty", 0))
                total_cost = float(order.get("cummulativeQuoteQty", 0))
                avg_price = total_cost / total_qty if total_qty > 0 else 0

            logger.info("Market sell %s: quantity=%.8f", symbol, quantity)
            return {
                "average": avg_price,
                "filled": total_qty,
            }
        except BinanceAPIException as e:
            logger.error("Failed to place market sell for %s: %s", symbol, str(e))
            raise

    def get_ticker_price(self, symbol: str) -> Optional[float]:
        """Get the current price for a symbol."""
        try:
            ticker = self._retry(self.client.get_symbol_ticker, symbol=symbol)
            return float(ticker["price"])
        except BinanceAPIException as e:
            logger.error("Failed to get ticker for %s: %s", symbol, str(e))
            raise
