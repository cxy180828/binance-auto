import logging
from datetime import datetime, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


class BlacklistManager:
    def __init__(self, config: dict):
        self._consecutive_losses_threshold = config.get("consecutive_losses", 2)
        self._duration_minutes = config.get("duration_minutes", 30)
        self._blacklist: Dict[str, datetime] = {}
        self._loss_counts: Dict[str, int] = {}

    def seed_from_storage(self, storage):
        """Seed loss counts from the database on startup.

        Queries recent traded symbols and pre-loads their consecutive loss
        counts so that the blacklist state survives restarts.
        """
        try:
            symbols = storage.get_recent_traded_symbols()
            for symbol in symbols:
                count = storage.get_consecutive_losses(symbol)
                if count > 0:
                    self._loss_counts[symbol] = count
                    if count >= self._consecutive_losses_threshold:
                        self._blacklist[symbol] = datetime.now()
                        logger.info(
                            "Seeded blacklist: %s with %d consecutive losses",
                            symbol,
                            count,
                        )
            if symbols:
                logger.info(
                    "Seeded blacklist manager from %d symbols in storage",
                    len(symbols),
                )
        except Exception as e:
            logger.error("Failed to seed blacklist from storage: %s", str(e))
            raise

    def record_loss(self, symbol: str):
        """Increment loss count for a symbol; blacklist if threshold reached."""
        self._loss_counts[symbol] = self._loss_counts.get(symbol, 0) + 1
        if self._loss_counts[symbol] >= self._consecutive_losses_threshold:
            self._blacklist[symbol] = datetime.now()
            logger.info(
                "Symbol %s blacklisted after %d consecutive losses",
                symbol,
                self._loss_counts[symbol],
            )

    def record_win(self, symbol: str):
        """Reset loss count for a symbol."""
        self._loss_counts[symbol] = 0

    def is_blacklisted(self, symbol: str) -> bool:
        """Check if symbol is blacklisted and hasn't expired."""
        if symbol not in self._blacklist:
            return False

        blacklist_time = self._blacklist[symbol]
        duration = timedelta(minutes=self._duration_minutes)

        if datetime.now() - blacklist_time >= duration:
            del self._blacklist[symbol]
            self._loss_counts[symbol] = 0
            logger.info("Symbol %s removed from blacklist (expired)", symbol)
            return False

        return True

    def get_blacklisted_symbols(self) -> List[str]:
        """Return list of currently blacklisted symbols."""
        now = datetime.now()
        duration = timedelta(minutes=self._duration_minutes)
        expired = [
            s for s, t in self._blacklist.items() if now - t >= duration
        ]
        for s in expired:
            del self._blacklist[s]
            self._loss_counts[s] = 0
            logger.info("Symbol %s removed from blacklist (expired)", s)

        return list(self._blacklist.keys())
