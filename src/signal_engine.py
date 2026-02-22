"""Signal computation engine: RSI, MACD, VWAP, Bollinger, S/R, regime detection."""

from __future__ import annotations

import os

from colors import G, R, Y, D, M

# Signal weights
W_MOMENTUM = float(os.getenv('W_MOMENTUM', '0.30'))
W_DIVERGENCE = float(os.getenv('W_DIVERGENCE', '0.20'))
W_SR = float(os.getenv('W_SUPPORT_RESISTANCE', '0.10'))
W_MACD = float(os.getenv('W_MACD', '0.15'))
W_VWAP = float(os.getenv('W_VWAP', '0.15'))
W_BB = float(os.getenv('W_BOLLINGER', '0.10'))

# Volatility
VOL_THRESHOLD = float(os.getenv('VOL_THRESHOLD', '0.03'))
VOL_AMPLIFIER = float(os.getenv('VOL_AMPLIFIER', '1.3'))

# Regime multipliers
REGIME_CHOP_MULT = float(os.getenv('REGIME_CHOP_MULT', '0.50'))
REGIME_TREND_BOOST = float(os.getenv('REGIME_TREND_BOOST', '1.15'))
REGIME_COUNTER_MULT = float(os.getenv('REGIME_COUNTER_MULT', '0.70'))

# Phase thresholds
PHASE_EARLY_THRESHOLD = int(os.getenv('PHASE_EARLY_THRESHOLD', '50'))
PHASE_MID_THRESHOLD = int(os.getenv('PHASE_MID_THRESHOLD', '30'))
PHASE_LATE_THRESHOLD = int(os.getenv('PHASE_LATE_THRESHOLD', '70'))
PHASE_CLOSING_THRESHOLD = 999

# Signal computation thresholds
SIGNAL_NEUTRAL_ZONE = 0.10
DIVERGENCE_LOOKBACK = 6
SR_LOOKBACK = 20

# TP/SL defaults (used for signal suggestions)
TP_BASE_SPREAD = 0.05
TP_STRENGTH_SCALE = 0.10
TP_MAX_PRICE = 0.95
SL_DEFAULT = 0.06
SL_MIN_PRICE = 0.03


def _ema(values, period):
    """Compute simple EMA from a list of floats."""
    if not values:
        return 0.0
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def get_market_phase(time_remaining, window_min=15):
    """Determine market phase based on time remaining.
    Thresholds are proportional to window size.
    Returns (phase_name, min_strength_threshold)."""
    pct = time_remaining / window_min if window_min > 0 else 0
    if pct > 0.66:
        return 'EARLY', PHASE_EARLY_THRESHOLD
    elif pct > 0.33:
        return 'MID', PHASE_MID_THRESHOLD
    elif pct > 0.06:
        return 'LATE', PHASE_LATE_THRESHOLD
    else:
        return 'CLOSING', PHASE_CLOSING_THRESHOLD


def compute_signal(up_buy, down_buy, btc_price, binance, history, regime='RANGE', phase='MID'):
    """Compute scalp signal v3 - Trend-Following with MACD, VWAP, Bollinger.

    Note: caller must append to history before calling this function.
    """
    if up_buy <= 0 or btc_price <= 0 or not binance:
        return None

    score = 0.0
    rsi = binance.get('rsi', 50)
    bin_score = binance.get('score', 0)

    # TREND FILTER (EMA of UP price)
    trend_strength = 0.0
    if len(history) >= 12:
        up_prices = [h['up'] for h in list(history)[-20:] if h['up'] > 0]
        if len(up_prices) >= 12:
            fast_ema = _ema(up_prices, 5)
            slow_ema = _ema(up_prices, 12)
            ema_diff = (fast_ema - slow_ema) / slow_ema if slow_ema > 0 else 0
            trend_strength = max(-1.0, min(1.0, ema_diff / 0.02))

    # 1. BTC MOMENTUM (30%) — RSI + candle score
    if rsi < 25: rsi_c = 1.0
    elif rsi < 35: rsi_c = 0.6
    elif rsi < 45: rsi_c = 0.2
    elif rsi > 75: rsi_c = -1.0
    elif rsi > 65: rsi_c = -0.6
    elif rsi > 55: rsi_c = -0.2
    else: rsi_c = 0.0

    momentum = rsi_c * 0.4 + min(max(bin_score / 0.5, -1), 1) * 0.6
    score += momentum * W_MOMENTUM

    # 2. DIVERGENCE (20%) — BTC vs Polymarket
    div_score = 0.0
    btc_var = 0
    if len(history) >= DIVERGENCE_LOOKBACK:
        h_old, h_new = history[-DIVERGENCE_LOOKBACK], history[-1]
        if h_old['btc'] > 0 and h_old['up'] > 0:
            btc_var = (h_new['btc'] - h_old['btc']) / h_old['btc'] * 100
            poly_var = h_new['up'] - h_old['up']
            if btc_var > 0.01 and poly_var < 0.02:
                div_score = min(btc_var * 8, 1.0)
            elif btc_var < -0.01 and poly_var > -0.02:
                div_score = max(btc_var * 8, -1.0)
    score += div_score * W_DIVERGENCE

    # 3. SUPPORT/RESISTANCE (10%) + TREND FILTER
    sr_score = 0.0
    sr_raw = 0.0
    if len(history) >= 10:
        ups = [h['up'] for h in history if h['up'] > 0]
        if len(ups) >= 10:
            up_min, up_max = min(ups[-SR_LOOKBACK:]), max(ups[-SR_LOOKBACK:])
            range_ = up_max - up_min
            if range_ > 0.03:
                pos = (up_buy - up_min) / range_
                if pos < 0.20: sr_raw = 0.8
                elif pos < 0.35: sr_raw = 0.4
                elif pos > 0.80: sr_raw = -0.8
                elif pos > 0.65: sr_raw = -0.4

    if abs(trend_strength) > 0.3:
        if (trend_strength > 0 and sr_raw < 0) or (trend_strength < 0 and sr_raw > 0):
            reduction = min(abs(trend_strength) * 2, 1.0)
            sr_score = sr_raw * (1.0 - reduction)
        else:
            sr_score = sr_raw
    else:
        sr_score = sr_raw
    score += sr_score * W_SR

    # 4. MACD HISTOGRAM DELTA (15%) — momentum acceleration
    macd_hist = binance.get('macd_hist', 0)
    macd_hist_delta = binance.get('macd_hist_delta', 0)
    macd_score = 0.0
    if abs(macd_hist_delta) > 0.5:
        # Strong acceleration
        macd_score = 1.0 if macd_hist_delta > 0 else -1.0
    elif abs(macd_hist_delta) > 0.1:
        macd_score = 0.5 if macd_hist_delta > 0 else -0.5
    # Boost if histogram and delta agree
    if macd_hist > 0 and macd_hist_delta > 0:
        macd_score = min(macd_score * 1.2, 1.0)
    elif macd_hist < 0 and macd_hist_delta < 0:
        macd_score = max(macd_score * 1.2, -1.0)
    score += macd_score * W_MACD

    # 5. VWAP POSITION + SLOPE (15%)
    vwap_pos = binance.get('vwap_pos', 0)
    vwap_slope = binance.get('vwap_slope', 0)
    vwap_score = 0.0
    # Price vs VWAP
    if vwap_pos > 0.02:
        vwap_score += 0.5   # above VWAP = bullish
    elif vwap_pos < -0.02:
        vwap_score -= 0.5   # below VWAP = bearish
    # VWAP slope direction
    if vwap_slope > 0.2:
        vwap_score += 0.5
    elif vwap_slope < -0.2:
        vwap_score -= 0.5
    vwap_score = max(-1.0, min(1.0, vwap_score))
    score += vwap_score * W_VWAP

    # 6. BOLLINGER POSITION (10%)
    bb_pos = binance.get('bb_pos', 0.5)
    bb_squeeze = binance.get('bb_squeeze', False)
    bb_score = 0.0
    if bb_pos < 0.15:
        bb_score = 0.8   # near lower band = oversold, likely UP
    elif bb_pos < 0.30:
        bb_score = 0.4
    elif bb_pos > 0.85:
        bb_score = -0.8  # near upper band = overbought, likely DOWN
    elif bb_pos > 0.70:
        bb_score = -0.4
    # Squeeze amplifier: signal is stronger when breaking out of squeeze
    if bb_squeeze:
        bb_score *= 1.5
        bb_score = max(-1.0, min(1.0, bb_score))
    score += bb_score * W_BB

    # VOLATILITY (amplifier)
    atr = binance.get('atr', 0)
    vol_pct = (atr / btc_price * 100) if btc_price > 0 else 0
    high_vol = vol_pct > VOL_THRESHOLD
    if high_vol:
        score *= VOL_AMPLIFIER

    # REGIME ADJUSTMENT
    if regime == 'CHOP':
        score *= REGIME_CHOP_MULT
    elif regime in ('TREND_UP', 'TREND_DOWN'):
        trend_dir = 1.0 if regime == 'TREND_UP' else -1.0
        if (score > 0 and trend_dir > 0) or (score < 0 and trend_dir < 0):
            score *= REGIME_TREND_BOOST
        else:
            score *= REGIME_COUNTER_MULT

    score = max(-1.0, min(1.0, score))
    if score > SIGNAL_NEUTRAL_ZONE: direction = 'UP'
    elif score < -SIGNAL_NEUTRAL_ZONE: direction = 'DOWN'
    else: direction = 'NEUTRAL'
    strength = int(abs(score) * 100)

    suggestion = None
    if strength >= 30:
        if direction == 'UP':
            entry = up_buy
        else:
            entry = down_buy
        spread = TP_BASE_SPREAD + (strength / 100) * TP_STRENGTH_SCALE
        tp = min(entry + spread, TP_MAX_PRICE)
        sl = max(entry - SL_DEFAULT, SL_MIN_PRICE)
        suggestion = {'entry': entry, 'tp': tp, 'sl': sl}

    return {
        'direction': direction, 'strength': strength, 'score': score,
        'rsi': rsi, 'btc_var': btc_var, 'high_vol': high_vol, 'divergence': div_score,
        'suggestion': suggestion,
        'trend': trend_strength, 'sr_raw': sr_raw, 'sr_adj': sr_score,
        'vol_pct': vol_pct,
        'macd_hist': macd_hist, 'macd_hist_delta': macd_hist_delta,
        'vwap_pos': vwap_pos, 'vwap_slope': vwap_slope,
        'bb_pos': bb_pos, 'bb_squeeze': bb_squeeze,
        'regime': regime, 'phase': phase,
    }


def detect_scenario(signal, regime, phase):
    """Detect active trading scenario based on current indicators.
    Returns (scenario_name, color, is_warning) or None."""
    if not signal:
        return None

    rsi = signal.get('rsi', 50)
    bb_pos = signal.get('bb_pos', 0.5)
    bb_squeeze = signal.get('bb_squeeze', False)
    vwap_pos = signal.get('vwap_pos', 0)
    macd_hist_delta = signal.get('macd_hist_delta', 0)
    high_vol = signal.get('high_vol', False)
    strength = signal.get('strength', 0)
    direction = signal.get('direction', 'NEUTRAL')
    macd_hist = signal.get('macd_hist', 0)

    # --- Warning scenarios (section 4.5) ---
    if phase == 'CLOSING':
        return ('CLOSING - DO NOT TRADE', R, True)
    if regime == 'CHOP':
        return ('CHOP - AVOID TRADING', Y, True)
    if strength < 30 and direction != 'NEUTRAL':
        return ('WEAK SIGNAL', D, True)
    if 45 <= rsi <= 55 and abs(macd_hist) < 0.1:
        return ('NEUTRAL - NO MOMENTUM', D, True)

    # --- Positive scenarios (section 4.4) ---
    # Scenario 1: Support Bounce
    if rsi < 30 and bb_pos < 0.15 and vwap_pos > 0 and regime == 'TREND_UP':
        return ('SUPPORT BOUNCE', G, False)
    # Scenario 1 (inverse): Resistance Bounce
    if rsi > 70 and bb_pos > 0.85 and vwap_pos < 0 and regime == 'TREND_DOWN':
        return ('RESISTANCE BOUNCE', R, False)

    # Scenario 2: MACD Breakout
    if abs(macd_hist_delta) > 0.3 and bb_squeeze and high_vol and strength > 70:
        return ('BREAKOUT MACD', M, False)

    # Scenario 3: Divergence + Trend
    div_score = signal.get('divergence', 0)
    if abs(div_score) > 0.3 and regime in ('TREND_UP', 'TREND_DOWN') and strength >= 40:
        if div_score > 0:
            return ('DIVERGENCE UP', G, False)
        else:
            return ('DIVERGENCE DN', R, False)

    # Relaxed scenarios for moderate signals
    if rsi < 35 and bb_pos < 0.25 and regime in ('TREND_UP', 'RANGE'):
        return ('MODERATE SUPPORT', G, False)
    if rsi > 65 and bb_pos > 0.75 and regime in ('TREND_DOWN', 'RANGE'):
        return ('MODERATE RESISTANCE', R, False)
    if abs(macd_hist_delta) > 0.2 and strength > 50:
        dir_label = 'UP' if macd_hist_delta > 0 else 'DN'
        color = G if macd_hist_delta > 0 else R
        return (f'MOMENTUM {dir_label}', color, False)

    return None
