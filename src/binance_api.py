#!/usr/bin/env python3
"""
Functions to query BTC price from Binance and compute trend.
Uses only public endpoints (no authentication).
"""
from __future__ import annotations

import logging
import os

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

BINANCE_API = "https://api.binance.com/api/v3"

# Persistent HTTP session (reuses TCP connections via keep-alive)
_session = requests.Session()

# Configurable indicator periods
RSI_PERIOD = int(os.getenv('RSI_PERIOD', '7'))
MACD_FAST = int(os.getenv('MACD_FAST', '5'))
MACD_SLOW = int(os.getenv('MACD_SLOW', '10'))
MACD_SIGNAL = int(os.getenv('MACD_SIGNAL', '4'))
BB_PERIOD = int(os.getenv('BB_PERIOD', '14'))
BB_STD = float(os.getenv('BB_STD', '2'))
ADX_PERIOD = int(os.getenv('ADX_PERIOD', '7'))


def get_btc_price(symbol: str = "BTCUSDT") -> float:
    """Returns the current price for a symbol from Binance."""
    r = _session.get(f"{BINANCE_API}/ticker/price", params={"symbol": symbol}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])


def get_price_at_timestamp(timestamp_sec: int, symbol: str = "BTCUSDT") -> float:
    """Returns the open price at a specific timestamp (Price to Beat).

    Args:
        timestamp_sec: Unix timestamp in seconds (e.g. from market slug)
        symbol: Binance trading pair (default: BTCUSDT)

    Returns:
        float: price at that timestamp, or 0.0 on error
    """
    try:
        r = _session.get(
            f"{BINANCE_API}/klines",
            params={
                "symbol": symbol,
                "interval": "1m",
                "startTime": timestamp_sec * 1000,
                "limit": 1,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data:
            return float(data[0][1])  # open price
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.debug("get_price_at_timestamp error: %s", e)
    return 0.0


def get_klines(symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 15) -> list[dict]:
    """
    Returns the latest candles for a symbol.

    Args:
        symbol: Binance trading pair (default: BTCUSDT)
        interval: "1m", "3m", "5m", "15m", etc.
        limit: number of candles (max 1000)

    Returns list of dicts with: open, high, low, close, volume, timestamp
    """
    r = _session.get(
        f"{BINANCE_API}/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10,
    )
    r.raise_for_status()

    candles = []
    for k in r.json():
        candles.append({
            "timestamp": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return candles


def compute_rsi(candles: list[dict], period: int | None = None) -> float:
    """Fast RSI for scalping (short period = more reactive)"""
    if period is None:
        period = RSI_PERIOD
    if len(candles) < period + 1:
        return 50.0  # neutral

    changes = [candles[i]['close'] - candles[i - 1]['close'] for i in range(1, len(candles))]
    changes = changes[-period:]

    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_gain == 0 and avg_loss == 0:
        return 50.0

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_atr(candles: list[dict]) -> float:
    """ATR (Average True Range) - measures volatility"""
    if len(candles) < 2:
        return 0.0

    trs = []
    for i in range(1, len(candles)):
        c = candles[i]
        prev_close = candles[i - 1]['close']
        tr = max(
            c['high'] - c['low'],
            abs(c['high'] - prev_close),
            abs(c['low'] - prev_close),
        )
        trs.append(tr)

    return sum(trs) / len(trs) if trs else 0.0


def compute_adx(candles: list[dict], period: int | None = None) -> float:
    """ADX (Average Directional Index) - measures trend strength (0-100).
    High ADX (>25) = strong trend, Low ADX (<20) = range/chop."""
    if period is None:
        period = ADX_PERIOD
    if len(candles) < period + 2:
        return 25.0  # neutral

    plus_dm_list = []
    minus_dm_list = []
    tr_list = []

    for i in range(1, len(candles)):
        high = candles[i]['high']
        low = candles[i]['low']
        prev_high = candles[i - 1]['high']
        prev_low = candles[i - 1]['low']
        prev_close = candles[i - 1]['close']

        plus_dm = max(high - prev_high, 0)
        minus_dm = max(prev_low - low, 0)
        if plus_dm > minus_dm:
            minus_dm = 0
        elif minus_dm > plus_dm:
            plus_dm = 0
        else:
            plus_dm = minus_dm = 0

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
        tr_list.append(tr)

    if len(tr_list) < period:
        return 25.0

    # Smoothed averages (Wilder's method using SMA for initial)
    atr_s = sum(tr_list[:period]) / period
    plus_di_s = sum(plus_dm_list[:period]) / period
    minus_di_s = sum(minus_dm_list[:period]) / period

    dx_list = []
    for i in range(period, len(tr_list)):
        atr_s = (atr_s * (period - 1) + tr_list[i]) / period
        plus_di_s = (plus_di_s * (period - 1) + plus_dm_list[i]) / period
        minus_di_s = (minus_di_s * (period - 1) + minus_dm_list[i]) / period

        if atr_s > 0:
            plus_di = (plus_di_s / atr_s) * 100
            minus_di = (minus_di_s / atr_s) * 100
        else:
            plus_di = minus_di = 0

        di_sum = plus_di + minus_di
        if di_sum > 0:
            dx = abs(plus_di - minus_di) / di_sum * 100
        else:
            dx = 0
        dx_list.append(dx)

    if not dx_list:
        return 25.0

    # ADX = smoothed average of DX
    adx = sum(dx_list[-period:]) / min(len(dx_list), period)
    return adx


def compute_bollinger_bandwidth(candles: list[dict], period: int | None = None) -> tuple[float, float]:
    """Bollinger Bandwidth - measures volatility spread.
    High bandwidth = high volatility, Low bandwidth = squeeze."""
    if period is None:
        period = BB_PERIOD
    if len(candles) < period:
        return 0.0, 0.5

    closes = [c['close'] for c in candles[-period:]]
    sma = sum(closes) / len(closes)
    variance = sum((c - sma) ** 2 for c in closes) / len(closes)
    std_dev = variance ** 0.5

    upper = sma + 2 * std_dev
    lower = sma - 2 * std_dev
    bandwidth = (upper - lower) / sma * 100 if sma > 0 else 0

    # Position within bands (0 = at lower, 1 = at upper)
    current = candles[-1]['close']
    band_range = upper - lower
    position = (current - lower) / band_range if band_range > 0 else 0.5

    return bandwidth, max(0, min(1, position))


def _ema_list(values: list[float], period: int) -> list[float]:
    """Compute EMA (Exponential Moving Average) for a list of values."""
    k = 2 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def compute_macd(candles: list[dict], fast: int | None = None, slow: int | None = None, signal_period: int | None = None) -> tuple[float, float, float, float]:
    """MACD optimized for 1-min scalping (fast periods for quick signals).

    Returns:
        macd_line: MACD line value
        signal_line: signal line value
        histogram: MACD - signal
        hist_delta: change in histogram (momentum acceleration)
    """
    if fast is None:
        fast = MACD_FAST
    if slow is None:
        slow = MACD_SLOW
    if signal_period is None:
        signal_period = MACD_SIGNAL
    closes = [c['close'] for c in candles]
    if len(closes) < slow + signal_period:
        return 0.0, 0.0, 0.0, 0.0

    fast_ema = _ema_list(closes, fast)
    slow_ema = _ema_list(closes, slow)

    # MACD line = fast EMA - slow EMA
    macd_values = [f - s for f, s in zip(fast_ema, slow_ema)]

    # Signal line = EMA of MACD
    signal_values = _ema_list(macd_values[slow - 1:], signal_period)

    macd_line = macd_values[-1]
    signal_line = signal_values[-1]
    histogram = macd_line - signal_line

    # Histogram delta (acceleration)
    if len(signal_values) >= 2:
        prev_hist = macd_values[-2] - signal_values[-2]
        hist_delta = histogram - prev_hist
    else:
        hist_delta = 0.0

    return macd_line, signal_line, histogram, hist_delta


def compute_vwap(candles: list[dict]) -> tuple[float, float, float]:
    """VWAP (Volume Weighted Average Price).

    Returns:
        vwap: VWAP price
        price_vs_vwap: (current - vwap) / vwap as percentage
        vwap_slope: slope direction of recent VWAP (-1 to +1)
    """
    if len(candles) < 3:
        return 0.0, 0.0, 0.0

    cum_vol = 0.0
    cum_tp_vol = 0.0
    vwap_values = []

    for c in candles:
        typical = (c['high'] + c['low'] + c['close']) / 3
        cum_vol += c['volume']
        cum_tp_vol += typical * c['volume']
        if cum_vol > 0:
            vwap_values.append(cum_tp_vol / cum_vol)
        else:
            vwap_values.append(typical)

    vwap = vwap_values[-1]
    current = candles[-1]['close']
    price_vs_vwap = ((current - vwap) / vwap * 100) if vwap > 0 else 0.0

    # VWAP slope (last 5 values)
    if len(vwap_values) >= 5:
        recent = vwap_values[-5:]
        slope = (recent[-1] - recent[0]) / recent[0] * 100 if recent[0] > 0 else 0
        vwap_slope = max(-1.0, min(1.0, slope * 50))  # normalize
    else:
        vwap_slope = 0.0

    return vwap, price_vs_vwap, vwap_slope


def compute_bollinger(candles: list[dict], period: int | None = None, num_std: int | None = None) -> tuple[float, float, float, float, float, bool]:
    """Bollinger Bands with position and squeeze detection.

    Returns:
        upper: upper band
        middle: middle band (SMA)
        lower: lower band
        bandwidth: (upper - lower) / middle as percentage
        position: current price position within bands (0=lower, 1=upper)
        squeeze: True if bandwidth is historically narrow
    """
    if period is None:
        period = BB_PERIOD
    if num_std is None:
        num_std = BB_STD
    if len(candles) < period:
        price = candles[-1]['close'] if candles else 0
        return price, price, price, 0.0, 0.5, False

    closes = [c['close'] for c in candles[-period:]]
    middle = sum(closes) / len(closes)
    variance = sum((c - middle) ** 2 for c in closes) / len(closes)
    std_dev = variance ** 0.5

    upper = middle + num_std * std_dev
    lower = middle - num_std * std_dev
    bandwidth = ((upper - lower) / middle * 100) if middle > 0 else 0

    current = candles[-1]['close']
    band_range = upper - lower
    position = (current - lower) / band_range if band_range > 0 else 0.5
    position = max(0.0, min(1.0, position))

    # Squeeze detection: bandwidth < 50% of its recent average
    squeeze = False
    if len(candles) >= period * 2:
        prev_closes = [c['close'] for c in candles[-(period * 2):-period]]
        prev_mid = sum(prev_closes) / len(prev_closes)
        prev_var = sum((c - prev_mid) ** 2 for c in prev_closes) / len(prev_closes)
        prev_std = prev_var ** 0.5
        prev_bw = (4 * prev_std / prev_mid * 100) if prev_mid > 0 else 0
        if prev_bw > 0 and bandwidth < prev_bw * 0.5:
            squeeze = True

    return upper, middle, lower, bandwidth, position, squeeze


def detect_regime(candles: list[dict]) -> tuple[str, float]:
    """Detect market regime: TREND_UP, TREND_DOWN, RANGE, or CHOP.

    Based on:
    - ADX: trend strength (>25 = trending)
    - Price vs SMA: direction
    - Bollinger bandwidth: volatility
    - Candle consistency: green/red ratio

    Returns: (regime, adx_value)
    """
    if len(candles) < 14:
        return "RANGE", 25.0

    adx = compute_adx(candles)
    bb_bw, bb_pos = compute_bollinger_bandwidth(candles)

    # Price direction (SMA)
    closes = [c['close'] for c in candles[-10:]]
    sma = sum(closes) / len(closes)
    current = candles[-1]['close']
    price_above_sma = current > sma

    # Candle consistency
    greens = sum(1 for c in candles[-7:] if c['close'] > c['open'])

    # Regime logic
    if adx >= 25:
        # Strong trend detected
        if price_above_sma and greens >= 4:
            return "TREND_UP", adx
        elif not price_above_sma and greens <= 3:
            return "TREND_DOWN", adx
        else:
            # ADX high but mixed signals
            return "RANGE", adx
    elif adx < 18:
        # Very weak directional movement
        if bb_bw > 0.15:
            # Wide bands + no direction = choppy
            return "CHOP", adx
        else:
            # Narrow bands + no direction = range (squeeze)
            return "RANGE", adx
    else:
        # ADX 18-25: transitional
        return "RANGE", adx


def get_full_analysis(candles: list[dict] | None = None, symbol: str = "BTCUSDT") -> tuple[str, float, dict]:
    """Returns full analysis with all indicators.

    Args:
        candles: pre-fetched candles (from WebSocket). If None, fetches via HTTP.
        symbol: Binance trading pair (used when fetching via HTTP)

    Returns:
        direction, confidence, details
    """
    if candles is None:
        candles = get_klines(symbol=symbol, interval="1m", limit=20)
    direction, confidence, details = analyze_trend(candles)

    details['rsi'] = compute_rsi(candles)
    details['atr'] = compute_atr(candles)
    details['candles_raw'] = candles

    # Regime detection
    regime, adx = detect_regime(candles)
    details['regime'] = regime
    details['adx'] = adx

    # MACD
    macd_line, signal_line, histogram, hist_delta = compute_macd(candles)
    details['macd_line'] = macd_line
    details['macd_signal'] = signal_line
    details['macd_hist'] = histogram
    details['macd_hist_delta'] = hist_delta

    # VWAP
    vwap, price_vs_vwap, vwap_slope = compute_vwap(candles)
    details['vwap'] = vwap
    details['vwap_pos'] = price_vs_vwap
    details['vwap_slope'] = vwap_slope

    # Bollinger Bands
    bb_upper, bb_mid, bb_lower, bb_bw, bb_pos, bb_squeeze = compute_bollinger(candles)
    details['bb_upper'] = bb_upper
    details['bb_mid'] = bb_mid
    details['bb_lower'] = bb_lower
    details['bb_bw'] = bb_bw
    details['bb_pos'] = bb_pos
    details['bb_squeeze'] = bb_squeeze

    return direction, confidence, details


def analyze_trend(candles: list[dict]) -> tuple[str, float, dict]:
    """
    Analyzes short-term trend based on candles.

    Returns:
        direction: "up", "down" or "neutral"
        confidence: float 0.0 to 1.0
        details: dict with computed metrics
    """
    if len(candles) < 5:
        return "neutral", 0.0, {"error": "insufficient candles"}

    # Current price vs price N candles ago
    current_price = candles[-1]["close"]
    start_price = candles[0]["open"]
    total_change = ((current_price - start_price) / start_price) * 100

    # Momentum: average of last 3 closes vs average of previous 3
    recent = [c["close"] for c in candles[-3:]]
    previous = [c["close"] for c in candles[-6:-3]] if len(candles) >= 6 else [c["close"] for c in candles[:3]]
    avg_recent = sum(recent) / len(recent)
    avg_previous = sum(previous) / len(previous)
    momentum = ((avg_recent - avg_previous) / avg_previous) * 100

    # Green vs red candles (last N)
    green = sum(1 for c in candles[-5:] if c["close"] > c["open"])
    red = 5 - green

    # Volume on up vs down candles
    vol_up = sum(c["volume"] for c in candles[-5:] if c["close"] > c["open"])
    vol_down = sum(c["volume"] for c in candles[-5:] if c["close"] <= c["open"])
    vol_total = vol_up + vol_down

    details = {
        "btc_price": current_price,
        "total_change": total_change,
        "momentum": momentum,
        "green_candles": green,
        "red_candles": red,
        "vol_up_pct": (vol_up / vol_total * 100) if vol_total > 0 else 50,
    }

    # Combined score (-1 to +1)
    score = 0.0

    # Total change (weight 0.35)
    if abs(total_change) > 0.02:
        score += 0.35 * (1.0 if total_change > 0 else -1.0)
    elif abs(total_change) > 0.01:
        score += 0.20 * (1.0 if total_change > 0 else -1.0)

    # Momentum (weight 0.35)
    if abs(momentum) > 0.02:
        score += 0.35 * (1.0 if momentum > 0 else -1.0)
    elif abs(momentum) > 0.01:
        score += 0.20 * (1.0 if momentum > 0 else -1.0)

    # Green/red candles (weight 0.15)
    if green >= 4:
        score += 0.15
    elif green <= 1:
        score -= 0.15
    elif green >= 3:
        score += 0.07
    elif green <= 2:
        score -= 0.07

    # Volume (weight 0.15)
    if vol_total > 0:
        ratio = vol_up / vol_total
        if ratio > 0.65:
            score += 0.15
        elif ratio < 0.35:
            score -= 0.15
        elif ratio > 0.55:
            score += 0.07
        elif ratio < 0.45:
            score -= 0.07

    details["score"] = score

    # Convert score to direction and confidence
    if score > 0.10:
        return "up", min(abs(score), 1.0), details
    elif score < -0.10:
        return "down", min(abs(score), 1.0), details
    else:
        return "neutral", abs(score), details


def get_btc_trend(symbol: str = "BTCUSDT") -> tuple[str, float, dict]:
    """
    Main function: fetches klines and returns trend analysis.

    Args:
        symbol: Binance trading pair (default: BTCUSDT)

    Returns:
        direction: "up", "down" or "neutral"
        confidence: float 0.0 to 1.0
        details: dict with metrics
    """
    candles = get_klines(symbol=symbol, interval="1m", limit=10)
    return analyze_trend(candles)
