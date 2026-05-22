import argparse
import logging
import os
import signal
import sys
import time
from logging.handlers import RotatingFileHandler

import schedule
import yaml

from src.blacklist import BlacklistManager
from src.exchange import Exchange
from src.notifier import FeishuNotifier
from src.storage import Storage
from src.strategy import TradingStrategy

logger = logging.getLogger(__name__)

shutdown_requested = False


def setup_logging(config: dict):
    """Setup logging to console and rotating file."""
    log_config = config.get("logging", {})
    log_level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    log_file = log_config.get("file", "logs/trading.log")

    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def load_config(path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def daily_summary(strategy: TradingStrategy, storage: Storage, notifier: FeishuNotifier):
    """Generate and send daily trading summary."""
    try:
        trades = storage.get_trades_today()
        sell_trades = [t for t in trades if t.get("side") == "sell"]

        total_trades = len(sell_trades)
        winning_trades = sum(1 for t in sell_trades if (t.get("profit_loss") or 0) > 0)
        losing_trades = sum(1 for t in sell_trades if (t.get("profit_loss") or 0) < 0)
        total_pnl = sum(t.get("profit_loss") or 0 for t in sell_trades)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        summary = {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "total_pnl": total_pnl,
            "win_rate": win_rate,
        }

        notifier.send_daily_summary(summary)
        logger.info("Daily summary sent: %s", summary)

    except Exception as e:
        logger.error("Failed to generate daily summary: %s", str(e))


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    shutdown_requested = True
    logger.info("Shutting down...")


def main():
    global shutdown_requested

    parser = argparse.ArgumentParser(description="Binance Alpha Trading Bot")
    parser.add_argument(
        "--check", action="store_true", help="Validate config and exit"
    )
    args = parser.parse_args()

    config = load_config()
    setup_logging(config)

    if args.check:
        logger.info("Config loaded successfully")
        logger.info("Binance testnet: %s", config.get("binance", {}).get("testnet", True))
        logger.info("Trading parameters: %s", config.get("trading", {}))
        logger.info("Blacklist config: %s", config.get("blacklist", {}))
        logger.info("Daily limits: %s", config.get("limits", {}))
        logger.info("Config OK")
        sys.exit(0)

    # Initialize components
    storage = Storage(config)
    storage.initialize()

    exchange = Exchange(config)
    notifier = FeishuNotifier(config)
    blacklist_manager = BlacklistManager(config.get("blacklist", {}))
    try:
        blacklist_manager.seed_from_storage(storage)
    except Exception as e:
        logger.error(
            "Failed to seed blacklist from storage: %s. "
            "Blacklist state may be incomplete.", str(e)
        )
    strategy = TradingStrategy(config, exchange, storage, notifier, blacklist_manager)

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Schedule daily summary
    summary_time = config.get("daily_summary_time", "20:00")
    schedule.every().day.at(summary_time).do(
        daily_summary, strategy, storage, notifier
    )
    logger.info("Daily summary scheduled at %s", summary_time)

    logger.info("Bot started, entering main loop...")

    while not shutdown_requested:
        try:
            strategy.scan_signals()
            strategy.manage_positions()
            schedule.run_pending()
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error("Error in main loop: %s", str(e))
            time.sleep(5)

    logger.info("Bot shutdown complete")


if __name__ == "__main__":
    main()
