from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .fmp_client import FMPClient


@dataclass(frozen=True)
class TechnicalSnapshot:
    ma_5: float | None = None
    ma_10: float | None = None
    ma_20: float | None = None
    ma_50: float | None = None
    ma_200: float | None = None
    ma_20_slope: float | None = None
    rsi_14: float | None = None
    macd_line: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    atr_14: float | None = None
    atr_pct: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    volume_ratio: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    daily_trend: str = 'sideways'
    weekly_trend: str = 'sideways'
    trend_strength_days: int = 0
    signal: str = 'wait'
    gate_is_blocked: bool = False
    gate_block_reasons: list[str] = field(default_factory=list)
    price_stale: bool = False


def _to_float(value: Any) -> float | None:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    sample = values[:window]
    return sum(sample) / window


def _ema(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    k = 2 / (window + 1)
    ema_values = [values[-1]]
    for price in reversed(values[:-1]):
        ema_values.append(price * k + ema_values[-1] * (1 - k))
    ema_values.reverse()
    return ema_values


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains = []
    losses = []
    for i in range(period):
        delta = closes[i] - closes[i + 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(rows: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(rows) <= period:
        return None
    trs: list[float] = []
    for i in range(period):
        high = _to_float(rows[i].get('high')) or _to_float(rows[i].get('close')) or 0.0
        low = _to_float(rows[i].get('low')) or _to_float(rows[i].get('close')) or 0.0
        prev_close = _to_float(rows[i + 1].get('close')) or 0.0
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs) / period


def _bollinger(closes: list[float], window: int = 20) -> tuple[float | None, float | None]:
    if len(closes) < window:
        return None, None
    values = closes[:window]
    ma = sum(values) / window
    variance = sum((value - ma) ** 2 for value in values) / window
    std = variance ** 0.5
    return ma + 2 * std, ma - 2 * std


def _trend_from_mas(ma5: float | None, ma10: float | None, ma20: float | None, ma50: float | None, slope20: float | None, rsi14: float | None) -> str:
    if None in (ma5, ma10, ma20, ma50, slope20, rsi14):
        return 'sideways'
    if ma5 > ma10 > ma20 > ma50 and slope20 > 0 and rsi14 > 50:
        return 'strong_up'
    if ma5 > ma20 and slope20 > 0:
        return 'up'
    if ma5 < ma10 < ma20 < ma50 and slope20 < -1 and rsi14 < 40:
        return 'strong_down'
    if ma5 < ma20 and slope20 < 0:
        return 'down'
    if abs(slope20) < 0.5:
        return 'sideways'
    return 'sideways'


def _weekly_trend(rows: list[dict[str, Any]]) -> str:
    weekly_closes: list[float] = []
    for idx in range(0, min(len(rows), 100), 5):
        close = _to_float(rows[idx].get('close'))
        if close is not None:
            weekly_closes.append(close)
    if len(weekly_closes) < 20:
        return 'sideways'
    ma5 = _sma(weekly_closes, 5)
    ma20 = _sma(weekly_closes, 20)
    if ma5 is None or ma20 is None:
        return 'sideways'
    if ma5 > ma20:
        return 'up'
    if ma5 < ma20:
        return 'down'
    return 'sideways'


def infer_basic_technical_snapshot(stock: dict[str, Any], *, client: FMPClient | None = None) -> TechnicalSnapshot:
    symbol = str(stock.get('symbol') or '').strip()
    historical: list[dict[str, Any]] = []
    if isinstance(stock.get('historical_prices'), list):
        historical = list(stock.get('historical_prices'))
    elif client is not None and symbol:
        historical = client.historical_price_full(symbol)

    closes = [_to_float(row.get('close')) for row in historical]
    closes = [value for value in closes if value is not None]
    price = _to_float(stock.get('price')) or (closes[0] if closes else None)
    volume_today = _to_float(stock.get('volume') or stock.get('avgVolume') or stock.get('volAvg'))

    if len(closes) < 30:
        gate_reasons = ['PRICE_HISTORY_INSUFFICIENT'] if symbol else ['PRICE_HISTORY_MISSING']
        signal = 'wait' if price else 'avoid'
        return TechnicalSnapshot(
            rsi_14=None,
            atr_pct=None,
            daily_trend='sideways',
            weekly_trend='sideways',
            signal=signal,
            gate_is_blocked=True,
            gate_block_reasons=gate_reasons,
            price_stale=True,
        )

    ma5 = _sma(closes, 5)
    ma10 = _sma(closes, 10)
    ma20 = _sma(closes, 20)
    ma50 = _sma(closes, 50)
    ma200 = _sma(closes, 200)
    ma20_5d_ago = _sma(closes[5:], 20) if len(closes) >= 25 else None
    slope20 = None
    if ma20 is not None and ma20_5d_ago not in (None, 0):
        slope20 = (ma20 - ma20_5d_ago) / ma20_5d_ago * 100

    rsi14 = _rsi(closes, 14)
    ema12 = _ema(list(reversed(closes)), 12)
    ema26 = _ema(list(reversed(closes)), 26)
    macd_line = None
    macd_signal = None
    macd_hist = None
    if ema12 and ema26 and len(ema12) == len(ema26):
        macd_series = [a - b for a, b in zip(ema12, ema26)]
        macd_line = macd_series[-1]
        signal_series = _ema(macd_series, 9)
        if signal_series:
            macd_signal = signal_series[-1]
            macd_hist = macd_line - macd_signal

    atr14 = _atr(historical, 14)
    atr_pct = (atr14 / price * 100) if atr14 and price else None
    bb_upper, bb_lower = _bollinger(closes, 20)
    avg_vol20 = sum(_to_float(row.get('volume')) or 0 for row in historical[:20]) / 20 if len(historical) >= 20 else None
    volume_ratio = (volume_today / avg_vol20) if volume_today and avg_vol20 else None
    high_52w = max(closes[:252]) if closes else None
    low_52w = min(closes[:252]) if closes else None
    daily_trend = _trend_from_mas(ma5, ma10, ma20, ma50, slope20, rsi14)
    weekly_trend = _weekly_trend(historical)

    signal = 'wait'
    if rsi14 is not None and price is not None and ma20 is not None and macd_line is not None and macd_signal is not None:
        if rsi14 < 30 and price > ma20 and macd_line > macd_signal and weekly_trend != 'down':
            signal = 'strong_buy'
        elif ma10 is not None and rsi14 < 40 and price > ma10 and daily_trend not in {'down', 'strong_down'}:
            signal = 'buy'
        elif rsi14 > 70 or daily_trend == 'strong_down' or (ma50 is not None and price < ma50 * 0.9):
            signal = 'avoid'

    gate_reasons: list[str] = []
    if daily_trend == 'strong_down':
        gate_reasons.append('GATE_001')
    if ma20 is not None and price is not None and rsi14 is not None and price < ma20 and rsi14 > 65:
        gate_reasons.append('GATE_002')
    if volume_ratio is not None and volume_ratio < 0.5:
        gate_reasons.append('GATE_003')
    if daily_trend == 'down' and weekly_trend == 'down':
        gate_reasons.append('GATE_004')
    if high_52w and price is not None and price < high_52w * 0.5 and signal in {'wait', 'avoid'}:
        gate_reasons.append('GATE_005')

    stabilization_signals = 0
    if len(closes) >= 3 and ma10 is not None and all(close > ma10 for close in closes[:3]):
        stabilization_signals += 1
    if rsi14 is not None and 35 < rsi14 < 55:
        stabilization_signals += 1
    if volume_ratio is not None and volume_ratio > 1.2 and len(closes) >= 2 and closes[0] > closes[1]:
        stabilization_signals += 1

    gate_is_blocked = bool(gate_reasons) and stabilization_signals < 2

    trend_strength_days = 0
    if len(closes) >= 6 and ma20 is not None:
        for close in closes[:6]:
            if close < ma20:
                trend_strength_days += 1

    return TechnicalSnapshot(
        ma_5=ma5,
        ma_10=ma10,
        ma_20=ma20,
        ma_50=ma50,
        ma_200=ma200,
        ma_20_slope=slope20,
        rsi_14=rsi14,
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_histogram=macd_hist,
        atr_14=atr14,
        atr_pct=atr_pct,
        bb_upper=bb_upper,
        bb_lower=bb_lower,
        volume_ratio=volume_ratio,
        high_52w=high_52w,
        low_52w=low_52w,
        daily_trend=daily_trend,
        weekly_trend=weekly_trend,
        trend_strength_days=trend_strength_days,
        signal=signal,
        gate_is_blocked=gate_is_blocked,
        gate_block_reasons=gate_reasons,
        price_stale=False,
    )


def technical_timing_score(snapshot: TechnicalSnapshot) -> float:
    trend_score = {
        ('up', 'up'): 40,
        ('strong_up', 'up'): 40,
        ('strong_up', 'strong_up'): 40,
        ('up', 'sideways'): 30,
    }.get((snapshot.daily_trend, snapshot.weekly_trend), None)
    if trend_score is None:
        trend_score = 15 if snapshot.daily_trend == 'sideways' else 0

    rsi_score = 0
    if snapshot.rsi_14 is not None:
        if snapshot.rsi_14 < 30:
            rsi_score = 30
        elif snapshot.rsi_14 < 40:
            rsi_score = 22
        elif snapshot.rsi_14 < 50:
            rsi_score = 15
        elif snapshot.rsi_14 < 60:
            rsi_score = 8

    signal_score = {
        'strong_buy': 30,
        'buy': 22,
        'wait': 10,
        'avoid': 0,
    }.get(snapshot.signal, 10)

    return float(trend_score + rsi_score + signal_score)
