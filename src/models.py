from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Trade:
    id: str
    symbol: str
    side: str
    price: float
    quantity: float
    amount: float
    timestamp: datetime
    profit_loss: Optional[float] = None
    status: str = "open"


@dataclass
class Position:
    symbol: str
    entry_price: float
    quantity: float
    amount: float
    entry_time: datetime
    highest_price: float = 0.0
    trailing_stop_active: bool = False
    trailing_stop_price: Optional[float] = None


@dataclass
class Signal:
    symbol: str
    candle_open: float
    candle_close: float
    candle_volume: float
    avg_volume: float
    price_change_pct: float
    timestamp: datetime
