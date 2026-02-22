#!/usr/bin/env python3
"""
Functions to query BTC price from Binance and compute trend.
Uses only public endpoints (no authentication).
"""

import requests

BINANCE_API = "https://api.binance.com/api/v3"


def get_btc_price():
    """Returns the current BTC/USDT price from Binance."""
    r = requests.get(f"{BINANCE_API}/ticker/price", params={"symbol": "BTCUSDT"}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])


def get_klines(interval="1m", limit=15):
    """
    Returns the latest BTC/USDT candles.

    Args:
        interval: "1m", "3m", "5m", "15m", etc.
        limit: number of candles (max 1000)

    Returns list of dicts with: open, high, low, close, volume, timestamp
    """
    r = requests.get(
        f"{BINANCE_API}/klines",
        params={"symbol": "BTCUSDT", "interval": interval, "limit": limit},
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


def compute_rsi(candles, period=7):
    """Fast RSI for scalping (short period = more reactive)"""
    if len(candles) < period + 1:
        return 50.0  # neutral

    changes = [candles[i]['close'] - candles[i - 1]['close'] for i in range(1, len(candles))]
    changes = changes[-period:]

    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_atr(candles):
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


def compute_adx(candles, period=7):
    """ADX (Average Directional Index) - measures trend strength (0-100).
    High ADX (>25) = strong trend, Low ADX (<20) = range/chop."""
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


def compute_bollinger_bandwidth(candles, period=14):
    """Bollinger Bandwidth - measures volatility spread.
    High bandwidth = high volatility, Low bandwidth = squeeze."""
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


def detect_regime(candles):
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


def get_full_analysis(candles=None):
    """Returns full analysis with RSI, ATR, ADX, regime.

    Args:
        candles: pre-fetched candles (from WebSocket). If None, fetches via HTTP.

    Returns:
        direction, confidence, details
    """
    if candles is None:
        candles = get_klines(interval="1m", limit=20)
    direction, confidence, details = analyze_trend(candles)

    details['rsi'] = compute_rsi(candles)
    details['atr'] = compute_atr(candles)
    details['candles_raw'] = candles

    # Regime detection
    regime, adx = detect_regime(candles)
    details['regime'] = regime
    details['adx'] = adx

    return direction, confidence, details


def analyze_trend(candles):
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


def get_btc_trend():
    """
    Main function: fetches klines and returns trend analysis.

    Returns:
        direction: "up", "down" or "neutral"
        confidence: float 0.0 to 1.0
        details: dict with metrics
    """
    candles = get_klines(interval="1m", limit=10)
    return analyze_trend(candles)
