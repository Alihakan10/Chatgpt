"""Independent BIST BUY engine.

This module is intentionally isolated from the production scanner.
It reproduces the TradingView public Supertrend script
(PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45) without using Study.

BUY = previous trend -1 -> current trend +1.
Settings: ATR 10, multiplier 2.0, source HL2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import math


ATR_PERIOD = 10
ATR_MULTIPLIER = 2.0


@dataclass(frozen=True)
class Candle:
    timestamp: float
    open: float
    high: float
    low: float
    close: float


def _rma(values: Sequence[float], period: int) -> list[float]:
    """TradingView-style Wilder RMA, seeded with SMA."""
    if len(values) < period:
        return []

    out = [math.nan] * len(values)
    out[period - 1] = sum(values[:period]) / period
    alpha = 1.0 / period

    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]

    return out


def _true_range(candles: Sequence[Candle]) -> list[float]:
    tr = []
    for i, c in enumerate(candles):
        if i == 0:
            tr.append(c.high - c.low)
        else:
            prev_close = candles[i - 1].close
            tr.append(max(
                c.high - c.low,
                abs(c.high - prev_close),
                abs(c.low - prev_close),
            ))
    return tr


def calculate_directions(
    candles: Sequence[Candle],
    atr_period: int = ATR_PERIOD,
    multiplier: float = ATR_MULTIPLIER,
) -> list[int]:
    """Reproduce the public TradingView Supertrend state logic.

    ATR uses Wilder RMA. Source is HL2.
    BUY is strictly a -1 -> +1 direction change on the final candle.
    """
    if len(candles) < atr_period + 2:
        return []

    tr = _true_range(candles)
    atr = _rma(tr, atr_period)
    n = len(candles)
    directions = [0] * n
    up_band = [math.nan] * n
    dn_band = [math.nan] * n

    first = atr_period - 1
    trend = 1

    for i in range(n):
        if math.isnan(atr[i]):
            directions[i] = trend
            continue

        hl2 = (candles[i].high + candles[i].low) / 2.0
        up = hl2 - multiplier * atr[i]
        dn = hl2 + multiplier * atr[i]

        up1 = up if i == first or math.isnan(up_band[i - 1]) else up_band[i - 1]
        dn1 = dn if i == first or math.isnan(dn_band[i - 1]) else dn_band[i - 1]

        prev_close = candles[i - 1].close if i > 0 else candles[i].close

        if prev_close > up1:
            up = max(up, up1)
        if prev_close < dn1:
            dn = min(dn, dn1)

        up_band[i] = up
        dn_band[i] = dn

        if i > first:
            if trend == -1 and candles[i].close > dn1:
                trend = 1
            elif trend == 1 and candles[i].close < up1:
                trend = -1

        directions[i] = trend

    return directions


def latest_buy_signal(
    candles: Sequence[Candle],
    atr_period: int = ATR_PERIOD,
    multiplier: float = ATR_MULTIPLIER,
) -> bool:
    directions = calculate_directions(candles, atr_period, multiplier)
    return len(directions) >= 2 and directions[-2] == -1 and directions[-1] == 1


def latest_result(
    candles: Sequence[Candle],
    atr_period: int = ATR_PERIOD,
    multiplier: float = ATR_MULTIPLIER,
) -> dict:
    directions = calculate_directions(candles, atr_period, multiplier)
    if len(directions) < 2:
        return {
            "buy": False,
            "previous_direction": None,
            "current_direction": None,
            "candle_timestamp": None,
        }

    return {
        "buy": directions[-2] == -1 and directions[-1] == 1,
        "previous_direction": directions[-2],
        "current_direction": directions[-1],
        "candle_timestamp": candles[-1].timestamp,
    }
