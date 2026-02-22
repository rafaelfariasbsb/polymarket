#!/usr/bin/env python3
"""
Scalp Radar - Trend-Following + Split Screen

Split screen layout:
  ┌─────────────────────────────────────────────────┐
  │  STATIC PANEL (updates in place)                │
  │  Binance, Market, Polymarket, Position, Signal  │
  ├─────────────────────────────────────────────────┤
  │  SCROLLING LOG (continuous scroll)              │
  │  Time │ BTC │ UP DN │ RSI │ Signal │ ...       │
  └─────────────────────────────────────────────────┘

Hotkeys:
  U = buy UP  │  D = buy DOWN  │  C = close all
  S = accept auto signal  │  Ctrl+C = exit

Usage:
  python radar_poly.py              # Uses TRADE_AMOUNT from .env ($4)
  python radar_poly.py 10           # $10 per trade
"""

import sys
import os
import io
import time
import platform
import shutil
import requests
from datetime import datetime
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from py_clob_client.clob_types import (
    OrderArgs, PartialCreateOrderOptions, OrderType,
    AssetType, BalanceAllowanceParams,
)

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import msvcrt
    # Enable ANSI escape codes on Windows 10+
    os.system("")
else:
    import select
    import termios
    import tty

load_dotenv()

# Check if running inside venv
if sys.prefix == sys.base_prefix:
    print("\033[1;33m⚠  WARNING: venv not activated!\033[0m")
    print("   Run: \033[1msource venv/bin/activate\033[0m")
    print("   Without venv, WebSocket and other features may not work.\n")
    try:
        input("   Press ENTER to continue anyway, or Ctrl+C to exit...")
    except KeyboardInterrupt:
        print()
        sys.exit(1)

# Force unbuffered output (avoid display delay)
sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.path.dirname(__file__))
from binance_api import get_full_analysis, get_price_at_timestamp
from polymarket_api import (
    create_client, find_current_market, get_token_position,
    get_balance, monitor_order, CLOB,
)
from logger import RadarLogger
from ws_binance import BinanceWS, HAS_WS

PRICE_ALERT = float(os.getenv('PRICE_ALERT', '0.80'))
SIGNAL_STRENGTH_BEEP = int(os.getenv('SIGNAL_STRENGTH_BEEP', '50'))
TRADE_AMOUNT = float(os.getenv('TRADE_AMOUNT', '4'))

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

# History for divergence and S/R
history = deque(maxlen=60)

# Colors
G = '\033[92m'
R = '\033[91m'
Y = '\033[93m'
C = '\033[96m'
W = '\033[97m'
B = '\033[1m'
D = '\033[90m'
M = '\033[95m'
X = '\033[0m'

HEADER_LINES = 15  # static panel lines

# Persistent HTTP session (reuses TCP connections via keep-alive)
_session = requests.Session()

# Persistent thread pool (avoid recreating every cycle)
_executor = ThreadPoolExecutor(max_workers=2)


class PriceCache:
    """TTL-based cache for get_price() to avoid duplicate HTTP calls."""

    def __init__(self, ttl_sec=0.5):
        self._cache = {}
        self._ttl = ttl_sec

    def get(self, token_id, side):
        now = time.time()
        key = (token_id, side)
        if key in self._cache:
            price, ts = self._cache[key]
            if now - ts < self._ttl:
                return price
        try:
            resp = _session.get(
                f"{CLOB}/price",
                params={"token_id": token_id, "side": side},
                timeout=5,
            )
            price = float(resp.json()["price"])
        except Exception:
            price = 0.0
        self._cache[key] = (price, now)
        return price

    def invalidate(self):
        self._cache.clear()


_price_cache = PriceCache(ttl_sec=0.5)


def get_price(token_id, side):
    return _price_cache.get(token_id, side)


def _ema(values, period):
    """Compute simple EMA from a list of floats."""
    if not values:
        return 0.0
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def get_market_phase(time_remaining):
    """Determine market phase based on time remaining in 15-min window.
    Returns (phase_name, min_strength_threshold)."""
    if time_remaining > 10:
        return 'EARLY', PHASE_EARLY_THRESHOLD
    elif time_remaining > 5:
        return 'MID', PHASE_MID_THRESHOLD
    elif time_remaining > 1:
        return 'LATE', PHASE_LATE_THRESHOLD
    else:
        return 'CLOSING', 999  # last minute: NO trading


def compute_signal(up_buy, down_buy, btc_price, binance, regime='RANGE', phase='MID'):
    """Compute scalp signal v3 - Trend-Following with MACD, VWAP, Bollinger."""
    if up_buy <= 0 or btc_price <= 0 or not binance:
        return None

    history.append({
        'ts': time.time(), 'up': up_buy, 'down': down_buy, 'btc': btc_price,
    })

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
    if len(history) >= 6:
        h_old, h_new = history[-6], history[-1]
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
            up_min, up_max = min(ups[-20:]), max(ups[-20:])
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
    if score > 0.10: direction = 'UP'
    elif score < -0.10: direction = 'DOWN'
    else: direction = 'NEUTRAL'
    strength = int(abs(score) * 100)

    suggestion = None
    if strength >= 30:
        if direction == 'UP':
            entry = up_buy
        else:
            entry = down_buy
        spread = 0.05 + (strength / 100) * 0.10
        tp = min(entry + spread, 0.95)
        sl = max(entry - 0.06, 0.03)
        suggestion = {'entry': entry, 'tp': tp, 'sl': sl}

    return {
        'direction': direction, 'strength': strength, 'score': score,
        'rsi': rsi, 'btc_var': btc_var, 'high_vol': high_vol,
        'suggestion': suggestion,
        'trend': trend_strength, 'sr_raw': sr_raw, 'sr_adj': sr_score,
        'vol_pct': vol_pct,
        'macd_hist': macd_hist, 'macd_hist_delta': macd_hist_delta,
        'vwap_pos': vwap_pos, 'vwap_slope': vwap_slope,
        'bb_pos': bb_pos, 'bb_squeeze': bb_squeeze,
        'regime': regime, 'phase': phase,
    }


# --- Non-blocking key reading ---------------------------------------------------

def read_key_nb():
    """Read key without blocking. Returns char or None."""
    if IS_WINDOWS:
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            try:
                return ch.decode('utf-8').lower()
            except Exception:
                return None
        return None
    else:
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1).lower()
        return None


def wait_for_key(timeout_sec=10):
    """Wait for key press up to timeout_sec."""
    start = time.time()
    while time.time() - start < timeout_sec:
        remaining = timeout_sec - (time.time() - start)
        sys.stdout.write(f"\r   {Y}{B}>>> S=execute U=UP D=DOWN | wait {int(remaining)}s to ignore <<<{X}  ")
        sys.stdout.flush()
        if IS_WINDOWS:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                sys.stdout.write("\r" + " " * 80 + "\r")
                sys.stdout.flush()
                try:
                    return ch.decode('utf-8').lower()
                except Exception:
                    continue
            time.sleep(0.1)
        else:
            if select.select([sys.stdin], [], [], 0.5)[0]:
                ch = sys.stdin.read(1)
                sys.stdout.write("\r" + " " * 80 + "\r")
                sys.stdout.flush()
                return ch.lower()
    sys.stdout.write("\r" + " " * 80 + "\r")
    sys.stdout.flush()
    return None


def sleep_with_key(seconds):
    """Sleep for N seconds but returns key if pressed."""
    steps = int(seconds / 0.1)
    for _ in range(steps):
        key = read_key_nb()
        if key:
            return key
        time.sleep(0.1)
    return None


# --- Scrolling log formatter -----------------------------------------------------

def format_scrolling_line(now_str, btc_price, up_buy, down_buy, signal, positions, regime):
    """Format one line for the scrolling log area. Returns formatted string."""
    s_dir = signal['direction']
    strength = signal['strength']
    rsi_val = signal['rsi']
    trend = signal.get('trend', 0)
    sr_raw = signal.get('sr_raw', 0)
    sr_adj = signal.get('sr_adj', 0)

    blocks = strength // 10
    bar = '█' * blocks + '░' * (10 - blocks)
    if s_dir == 'UP': color, sym = G, '▲'
    elif s_dir == 'DOWN': color, sym = R, '▼'
    else: color, sym = D, '─'
    rsi_arrow = '↑' if rsi_val < 45 else '↓' if rsi_val > 55 else '─'

    col_time   = f"{D}{now_str}{X}"
    col_btc    = f"BTC:{W}${btc_price:>7,.0f}{X}"
    col_up     = f"UP:{G}${up_buy:.2f}{X}"
    col_dn     = f"DN:{R}${down_buy:.2f}{X}"
    rsi_c = G if rsi_val < 40 else R if rsi_val > 60 else D
    col_rsi    = f"{rsi_c}RSI:{rsi_val:>2.0f}{rsi_arrow}{X}"
    col_signal = f"{color}{B}{sym} {s_dir:<7s} {strength:>3d}%{X}"
    col_bar    = f"{color}[{bar}]{X}"
    col_vol    = f"{Y}VOL↑{X}" if signal['high_vol'] else "    "

    if abs(trend) > 0.3:
        t_sym = '⬆' if trend > 0 else '⬇'
        t_color = G if trend > 0 else R
        t_text = f"T:{trend:+.1f}{t_sym}"
        col_trend = f"{t_color}{t_text:<7s}{X}"
    else:
        col_trend = f"{D}{'T: 0.0':<7s}{X}"

    if sr_raw != 0:
        sr_text = f"SR:{sr_raw:+.1f}→{sr_adj:+.1f}"
        sr_color = G if sr_raw > 0 else R
        col_sr = f"{sr_color}{sr_text:<13s}{X}"
    else:
        col_sr = f"{D}{'SR: 0.0':<13s}{X}"

    # MACD column
    macd_h = signal.get('macd_hist', 0)
    macd_d = signal.get('macd_hist_delta', 0)
    if macd_h > 0:
        m_arrow = '▲' if macd_d > 0 else '▼' if macd_d < 0 else '─'
        col_macd = f"{G}{macd_h:>+5.1f}{m_arrow}{X}"
    elif macd_h < 0:
        m_arrow = '▼' if macd_d < 0 else '▲' if macd_d > 0 else '─'
        col_macd = f"{R}{macd_h:>+5.1f}{m_arrow}{X}"
    else:
        col_macd = f"{D}  0.0─{X}"

    # VWAP column
    v_pos = signal.get('vwap_pos', 0)
    if v_pos > 0.02:
        col_vwap = f"{G}{v_pos:>+5.2f}↑{X}"
    elif v_pos < -0.02:
        col_vwap = f"{R}{v_pos:>+5.2f}↓{X}"
    else:
        col_vwap = f"{D} 0.00─{X}"

    # Bollinger position column
    bb_p = signal.get('bb_pos', 0.5)
    bb_sq = signal.get('bb_squeeze', False)
    bb_pct = f"{int(bb_p * 100):>3d}%"
    if bb_p > 0.80:
        col_bb = f"{G}{'SQ' if bb_sq else 'HI'}{bb_pct}{X}"
    elif bb_p < 0.20:
        col_bb = f"{R}{'SQ' if bb_sq else 'LO'}{bb_pct}{X}"
    else:
        col_bb = f"{D}{'SQ' if bb_sq else 'MD'}{bb_pct}{X}"

    # Position tag
    pos_str = ""
    if positions:
        total_shares = sum(p['shares'] for p in positions)
        dirs = set(p['direction'] for p in positions)
        d_str = '/'.join(d.upper() for d in dirs)
        pos_str = f" {M}{B}[{d_str} {total_shares:.0f}sh]{X}"

    # Regime tag
    if regime == 'TREND_UP':
        col_regime = f"{G}T▲{X}"
    elif regime == 'TREND_DOWN':
        col_regime = f"{R}T▼{X}"
    elif regime == 'CHOP':
        col_regime = f"{Y}CH{X}"
    else:
        col_regime = f"{D}RG{X}"

    return f"   {col_time} │ {col_btc} │ {col_up} {col_dn} │ {col_rsi} │ {col_signal} {col_bar} │ {col_vol} │ {col_trend} │ {col_macd} │ {col_vwap} │ {col_bb} │ {col_sr} │ {col_regime}{pos_str}"


# --- Session stats ---------------------------------------------------------------

def calculate_session_stats(trade_history):
    """Calculate session statistics from trade history.

    Returns dict with: wins, losses, win_rate, best, worst,
    gross_wins, gross_losses, profit_factor, max_drawdown.
    """
    if not trade_history:
        return {
            'wins': 0, 'losses': 0, 'win_rate': 0, 'best': 0, 'worst': 0,
            'gross_wins': 0, 'gross_losses': 0, 'profit_factor': 0, 'max_drawdown': 0,
        }
    wins = sum(1 for t in trade_history if t > 0)
    losses = sum(1 for t in trade_history if t <= 0)
    win_rate = (wins / len(trade_history) * 100) if trade_history else 0
    best = max(trade_history)
    worst = min(trade_history)
    gross_wins = sum(t for t in trade_history if t > 0)
    gross_losses = abs(sum(t for t in trade_history if t < 0))
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else gross_wins
    # Max drawdown
    max_dd = 0.0
    peak = 0.0
    cumul = 0.0
    for t in trade_history:
        cumul += t
        if cumul > peak:
            peak = cumul
        dd = peak - cumul
        if dd > max_dd:
            max_dd = dd
    return {
        'wins': wins, 'losses': losses, 'win_rate': win_rate,
        'best': best, 'worst': worst,
        'gross_wins': gross_wins, 'gross_losses': gross_losses,
        'profit_factor': profit_factor, 'max_drawdown': max_dd,
    }


def print_session_summary(duration_min, trade_count, session_pnl, trade_history):
    """Print formatted session summary to terminal."""
    stats = calculate_session_stats(trade_history)
    print()
    print(f" {C}{B}{'═' * 45}{X}")
    print(f" {C}{B} SESSION SUMMARY{X}")
    print(f" {D}{'─' * 45}{X}")
    print(f"  Duration:       {duration_min:.0f} min")
    print(f"  Total Trades:   {trade_count}")
    if trade_history:
        wr_color = G if stats['win_rate'] >= 50 else R
        print(f"  Win Rate:       {wr_color}{stats['win_rate']:.0f}%{X} ({G}{stats['wins']}W{X} / {R}{stats['losses']}L{X})")
        pnl_c = G if session_pnl >= 0 else R
        print(f"  Total P&L:      {pnl_c}{'+' if session_pnl >= 0 else ''}${session_pnl:.2f}{X}")
        print(f"  Best Trade:     {G}+${stats['best']:.2f}{X}")
        print(f"  Worst Trade:    {R}${stats['worst']:.2f}{X}")
        print(f"  Profit Factor:  {W}{stats['profit_factor']:.2f}{X}")
        print(f"  Max Drawdown:   {R}-${stats['max_drawdown']:.2f}{X}")
    else:
        print(f"  {D}No trades this session{X}")
    print(f" {C}{B}{'═' * 45}{X}")
    print()
    return stats


# --- Static panel ----------------------------------------------------------------

def draw_panel(time_str, balance, btc_price, bin_direction, confidence, binance_data,
               market_slug, time_remaining, up_buy, down_buy, positions, signal,
               trade_amount, alert_active=False, alert_side="", alert_price=0.0,
               session_pnl=0.0, trade_count=0, regime="", phase="",
               data_source="http", status_msg="", price_to_beat=0.0, ws_status="",
               trade_history=None, last_action=""):
    """Redraws the static panel at the top (HEADER_LINES lines).
    Uses StringIO buffer for single write+flush (reduces terminal I/O)."""
    w = shutil.get_terminal_size().columns
    buf = io.StringIO()

    buf.write("\033[s")  # save cursor

    # Line 1: title bar
    buf.write(f"\033[1;1H\033[K {C}{B}{'═' * (w - 2)}{X}")

    # Line 2: header with time and balance
    buf.write(f"\033[2;1H\033[K {C}{B}RADAR POLYMARKET{X} │ {W}{time_str}{X} │ Balance: {G}${balance:.2f}{X} │ Trade: {W}${trade_amount:.0f}{X}")

    # Line 3: separator
    buf.write(f"\033[3;1H\033[K {C}{'═' * (w - 2)}{X}")

    # Line 4: Binance
    bin_color = G if bin_direction == 'UP' else R if bin_direction == 'DOWN' else D
    rsi_val = binance_data.get('rsi', 50)
    score_bin = binance_data.get('score', 0)
    vol_str = f"{Y}HIGH{X}" if (signal and signal.get('high_vol')) else f"{D}normal{X}"
    # Regime indicator
    if regime == 'TREND_UP':
        reg_str = f"{G}{B}TREND▲{X}"
    elif regime == 'TREND_DOWN':
        reg_str = f"{R}{B}TREND▼{X}"
    elif regime == 'CHOP':
        reg_str = f"{Y}{B}CHOP{X}"
    else:
        reg_str = f"{D}RANGE{X}"
    if data_source == 'ws':
        src_str = f"{G}{B}WebSocket{X}"
    elif ws_status:
        src_str = f"{D}HTTP{X} {Y}{ws_status}{X}"
    else:
        src_str = f"{D}HTTP{X}"
    buf.write(f"\033[4;1H\033[K {C}BINANCE {X}│ BTC: {W}${btc_price:>8,.2f}{X} │ {bin_color}{B}{bin_direction}{X} (score:{score_bin:+.2f} conf:{confidence:.0f}%) │ RSI:{rsi_val:.0f} │ Vol:{vol_str} │ {reg_str} │ {src_str}")

    # Line 5: Market
    time_color = R if time_remaining < 2 else Y if time_remaining < 5 else G
    if phase == 'EARLY':
        phase_str = f"{C}EARLY{X}"
    elif phase == 'MID':
        phase_str = f"{G}MID{X}"
    elif phase == 'LATE':
        phase_str = f"{Y}{B}LATE{X}"
    elif phase == 'CLOSING':
        phase_str = f"{R}{B}CLOSING{X}"
    else:
        phase_str = f"{D}─{X}"
    ptb_str = ""
    if price_to_beat > 0 and btc_price > 0:
        diff = btc_price - price_to_beat
        diff_color = G if diff >= 0 else R
        ptb_str = f" │ Beat: {W}${price_to_beat:,.2f}{X} ({diff_color}{diff:+,.2f}{X})"
    buf.write(f"\033[5;1H\033[K {Y}MARKET  {X}│ {market_slug} │ Closes in: {time_color}{time_remaining:.1f}min{X} │ {phase_str}{ptb_str}")

    # Line 6: Polymarket
    buf.write(f"\033[6;1H\033[K {G}POLY    {X}│ UP: {G}${up_buy:.2f}{X}/{G}${1.0 - down_buy:.2f}{X} ({G}{up_buy * 100:.0f}%{X}) │ DOWN: {R}${down_buy:.2f}{X}/{R}${1.0 - up_buy:.2f}{X} ({R}{down_buy * 100:.0f}%{X})")

    # Line 7: Positions + Session P&L
    pnl_color = G if session_pnl >= 0 else R
    th = trade_history or []
    stats_str = ""
    if th:
        wins = sum(1 for t in th if t > 0)
        losses = len(th) - wins
        wr = (wins / len(th) * 100) if th else 0
        wr_color = G if wr >= 50 else R
        gw = sum(t for t in th if t > 0)
        gl = abs(sum(t for t in th if t < 0))
        pf = (gw / gl) if gl > 0 else gw
        stats_str = f" │ {wr_color}WR:{wr:.0f}%{X}({G}{wins}W{X}/{R}{losses}L{X}) │ {W}PF:{pf:.1f}{X}"
    pnl_str = f"{pnl_color}{B}P&L: {'+' if session_pnl >= 0 else ''}${session_pnl:.2f}{X} {D}({trade_count} trades){X}{stats_str}"
    if positions:
        agg = {}
        for p in positions:
            d = p['direction']
            if d not in agg:
                agg[d] = {'shares': 0, 'cost': 0.0}
            agg[d]['shares'] += p['shares']
            agg[d]['cost'] += p['shares'] * p['price']
        parts = []
        for d in agg:
            total_sh = agg[d]['shares']
            avg_price = agg[d]['cost'] / total_sh if total_sh > 0 else 0
            p_color = G if d == 'up' else R
            parts.append(f"{p_color}{d.upper()} {total_sh:.0f}sh @ ${avg_price:.2f}{X}")
        buf.write(f"\033[7;1H\033[K {M}POSITION{X}│ {' │ '.join(parts)} │ {pnl_str}")
    else:
        buf.write(f"\033[7;1H\033[K {M}POSITION{X}│ {D}None{X} │ {pnl_str}")

    # Line 8: Last action
    if last_action:
        buf.write(f"\033[8;1H\033[K {W}ACTION  {X}│ {last_action}")
    else:
        buf.write(f"\033[8;1H\033[K {D}ACTION  {X}│ {D}─{X}")

    # Line 9: Signal
    buf.write(f"\033[9;1H\033[K")
    if signal:
        s_dir = signal['direction']
        strength = signal['strength']
        blocks = strength // 10
        bar_s = '█' * blocks + '░' * (10 - blocks)
        if s_dir == 'UP': s_color, s_sym = G, '▲'
        elif s_dir == 'DOWN': s_color, s_sym = R, '▼'
        else: s_color, s_sym = D, '─'
        trend = signal.get('trend', 0)
        rsi_s = signal.get('rsi', 50)
        rsi_arrow = '↑' if rsi_s < 45 else '↓' if rsi_s > 55 else '─'
        rsi_color = G if rsi_s < 40 else R if rsi_s > 60 else D
        t_str = f"{G}T:{trend:+.1f}{X}" if trend > 0.3 else f"{R}T:{trend:+.1f}{X}" if trend < -0.3 else f"{D}T:0.0{X}"
        macd_h = signal.get('macd_hist', 0)
        macd_color = G if macd_h > 0.1 else R if macd_h < -0.1 else D
        macd_str = f"{macd_color}MACD:{macd_h:+.1f}{X}" if abs(macd_h) > 0.1 else f"{D}MACD:0{X}"
        vwap_p = signal.get('vwap_pos', 0)
        vwap_color = G if vwap_p > 0.01 else R if vwap_p < -0.01 else D
        vwap_str = f"{vwap_color}VW:{vwap_p:+.2f}{X}" if abs(vwap_p) > 0.01 else f"{D}VW:0{X}"
        bb_p = signal.get('bb_pos', 0.5)
        bb_color = G if bb_p > 0.80 else R if bb_p < 0.20 else D
        bb_str = f"{bb_color}BB:{bb_p:.0%}{X}"
        buf.write(f" {W}SIGNAL  {X}│ {s_color}{B}{s_sym} {s_dir:<7s} {strength:>3d}%{X} [{bar_s}] │ {rsi_color}RSI:{rsi_s:.0f}{rsi_arrow}{X} │ {t_str} │ {macd_str} │ {vwap_str} │ {bb_str}")
    else:
        buf.write(f" {W}SIGNAL  {X}│ {D}Waiting for data...{X}")

    # Line 10: Alert / Status message
    buf.write(f"\033[10;1H\033[K")
    if status_msg:
        buf.write(f" {Y}{B}STATUS  {X}│ {status_msg}")
    elif alert_active:
        alert_color = G if alert_side == "UP" else R
        buf.write(f" {Y}{B}ALERT   {X}│ {alert_color}{B}{alert_side} @ ${alert_price:.2f}{X} (>= ${PRICE_ALERT:.2f})")
    else:
        buf.write(f" {D}ALERT   {X}│ {D}─{X}")

    # Line 11: separator
    buf.write(f"\033[11;1H\033[K {'─' * (w - 2)}")

    # Line 12: Hotkeys
    buf.write(f"\033[12;1H\033[K {W}{B}U{X}{D}=buy UP{X} │ {W}{B}D{X}{D}=buy DOWN{X} │ {W}{B}C{X}{D}=close all{X} │ {W}{B}S{X}{D}=accept signal{X} │ {W}{B}Q{X}{D}=exit{X}")

    # Line 13: bottom separator
    buf.write(f"\033[13;1H\033[K {C}{B}{'═' * (w - 2)}{X}")

    # Line 14: column headers
    buf.write(f"\033[14;1H\033[K   {D}{'TIME':8s} │ {'BTC':>12s} │ {'UP':>8s} {'DN':>8s} │ {'RSI':>7s} │ {'SIGNAL  ─  STRENGTH':>27s} │ {'VOL':4s} │ {'TREND':>7s} │ {'MACD':>6s} │ {'VWAP':>6s} │ {'BB':>6s} │ {'S/R':>13s} │ {'REGIME':6s}{X}")

    # Line 15: blank
    buf.write(f"\033[15;1H\033[K")

    buf.write("\033[u")  # restore cursor

    # Single write + flush
    sys.stdout.write(buf.getvalue())
    sys.stdout.flush()


# --- Trade helpers ---------------------------------------------------------------

def close_all_positions(positions, token_up, token_down, logger, reason, session_pnl, trade_history):
    """Close all positions and calculate P&L for each.

    Args:
        positions: list of position dicts
        token_up/token_down: token IDs
        logger: RadarLogger instance
        reason: str — 'market_expired', 'emergency', 'exit', 'tp', 'sl', 'cancel'
        session_pnl: current cumulative P&L
        trade_history: list of individual trade P&L values

    Returns:
        (total_pnl, count, updated_session_pnl, pnl_list)
        pnl_list: list of (direction, shares, entry_price, exit_price, pnl) per position
    """
    total_pnl = 0.0
    count = 0
    pnl_list = []

    for p in positions:
        token_id = token_up if p['direction'] == 'up' else token_down
        try:
            exit_price = get_price(token_id, "SELL")
        except Exception:
            exit_price = 0
        pnl = (exit_price - p['price']) * p['shares'] if exit_price > 0 else 0
        total_pnl += pnl
        count += 1
        session_pnl += pnl
        trade_history.append(pnl)
        pnl_list.append((p['direction'], p['shares'], p['price'], exit_price, pnl))
        logger.log_trade("CLOSE", p['direction'], p['shares'], exit_price,
                         p['shares'] * exit_price, reason, pnl, session_pnl)

    positions.clear()
    return total_pnl, count, session_pnl, pnl_list


def handle_buy(client, direction, trade_amount, token_up, token_down,
               positions, balance, logger, session_pnl, reason="manual"):
    """Execute buy and update state. Returns (info, balance, last_action).

    Args:
        direction: 'up' or 'down'
        reason: 'signal' or 'manual'

    Returns:
        (info_dict_or_None, updated_balance, last_action_str)
    """
    info = execute_hotkey(client, direction, trade_amount, token_up, token_down)
    if info:
        d_color = G if direction == 'up' else R
        last_action = f"{d_color}{B}BUY {direction.upper()}{X} {info['shares']:.0f}sh @ ${info['price']:.2f} │ {D}{reason}{X}"
        positions.append(info)
        balance -= info['price'] * info['shares']
        logger.log_trade("BUY", direction, info['shares'], info['price'],
                         info['shares'] * info['price'], reason, 0, session_pnl)
    else:
        last_action = f"{R}✗ BUY {direction.upper()} FAILED{X}"
    return info, balance, last_action


# --- Trade execution -------------------------------------------------------------

def execute_buy_market(client, direction, amount_usd, token_up, token_down, quiet=False):
    """Execute aggressive market buy order."""
    token_id = token_up if direction == "up" else token_down

    base_price = get_price(token_id, "BUY")
    if base_price <= 0:
        return None, f"{R}✗ Error getting price{X}"

    price = min(base_price + 0.02, 0.99)
    shares = round(amount_usd / price, 2)
    if shares < 5:
        return None, f"{R}✗ Minimum 5 shares (increase amount){X}"

    try:
        tick_size = client.get_tick_size(token_id)
        neg_risk = client.get_neg_risk(token_id)
        order = client.create_order(
            OrderArgs(token_id=token_id, price=price, size=shares, side="BUY"),
            options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
        )
        resp = client.post_order(order, orderType=OrderType.GTC)
    except Exception as e:
        return None, f"{R}✗ Error submitting: {e}{X}"

    order_id = resp.get("orderID") or resp.get("id") if isinstance(resp, dict) else None
    if not order_id:
        return None, f"{R}✗ No order ID{X}"

    status, details = monitor_order(client, order_id, interval=2, timeout_sec=30, quiet=quiet)

    if status == "FILLED":
        sm = float(details.get("size_matched", 0)) if details else 0
        p = float(details.get("price", 0)) if details else price
        return {'shares': sm, 'price': p}, f"{G}✓ BUY MKT {direction.upper()} | {sm:.2f} @ ${p:.4f} = ${sm * p:.2f}{X}"
    else:
        return None, f"{Y}✗ Order not filled ({status}){X}"


def execute_close_market(client, token_up, token_down):
    """Close all positions."""
    results = []
    total_value = 0.0

    for _ in range(3):
        shares_up = get_token_position(client, token_up)
        shares_down = get_token_position(client, token_down)

        if shares_up < 0.01 and shares_down < 0.01:
            if results:
                return f"{G}✓ CLOSED! {', '.join(results)} | Total: ${total_value:.2f}{X}"
            return f"{G}✓ No positions{X}"

        for token_id, shares, name in [(token_up, shares_up, "UP"), (token_down, shares_down, "DOWN")]:
            if shares < 0.01:
                continue

            base_price = get_price(token_id, "SELL")
            market_price = max(base_price - 0.05, 0.01)

            try:
                client.update_balance_allowance(
                    params=BalanceAllowanceParams(
                        asset_type=AssetType.CONDITIONAL, token_id=token_id, signature_type=1,
                    )
                )
            except Exception:
                pass

            try:
                tick_size = client.get_tick_size(token_id)
                neg_risk = client.get_neg_risk(token_id)
                order = client.create_order(
                    OrderArgs(token_id=token_id, price=market_price, size=shares, side="SELL"),
                    options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
                )
                resp = client.post_order(order, orderType=OrderType.GTC)
                order_id = resp.get("orderID") or resp.get("id") if isinstance(resp, dict) else None
                if order_id:
                    status, details = monitor_order(client, order_id, interval=1, timeout_sec=15)
                    if status == "FILLED":
                        sm = float(details.get("size_matched", 0)) if details else 0
                        p = float(details.get("price", 0)) if details else market_price
                        value = sm * p
                        total_value += value
                        results.append(f"{name}: {sm:.2f} @ ${p:.2f} = ${value:.2f}")
            except Exception:
                pass

        time.sleep(1)

    return f"{G}✓ {', '.join(results)} | ${total_value:.2f}{X}" if results else f"{Y}⚠ Could not close{X}"


# --- TP/SL monitoring ------------------------------------------------------------

def monitor_tp_sl(token_id, tp, sl, tp_above, sl_above):
    """Monitor price until TP, SL, or manual cancel (C key).
    Uses concurrent price fetch + key checking for lower latency."""
    price = 0.0
    while True:
        # Fetch price concurrently while checking keys
        fut_price = _executor.submit(get_price, token_id, "BUY")

        # Check keys while waiting for price (5 × 0.1s = 0.5s)
        for _ in range(5):
            key = read_key_nb()
            if key == 'c':
                fut_price.result()  # don't leak the future
                return 'CANCEL', price if price > 0 else get_price(token_id, "BUY")
            time.sleep(0.1)

        price = fut_price.result()
        if price <= 0:
            continue

        now = datetime.now().strftime("%H:%M:%S")

        if tp_above and price >= tp:
            return 'TP', price
        if not tp_above and price <= tp:
            return 'TP', price

        if sl_above and price <= sl:
            return 'SL', price
        if not sl_above and price >= sl:
            return 'SL', price

        dist_tp = abs(tp - price)
        dist_sl = abs(sl - price)
        bar_pos = 10 - int(dist_tp / (dist_tp + dist_sl) * 10) if (dist_tp + dist_sl) > 0 else 5
        bar = f"{G}{'█' * bar_pos}{X}{R}{'█' * (10 - bar_pos)}{X}"
        sys.stdout.write(f"\r   {D}{now}{X} | ${price:.2f} | SL ${sl:.2f} [{bar}] TP ${tp:.2f} │ {D}C=close{X}   ")
        sys.stdout.flush()


# --- Hotkey buy ------------------------------------------------------------------

def execute_hotkey(client, direction, trade_amount, token_up, token_down):
    """Execute manual buy via hotkey (u/d). Returns buy info or None."""
    result, msg = execute_buy_market(client, direction, trade_amount, token_up, token_down, quiet=True)
    exec_time = datetime.now().strftime("%H:%M:%S")

    if result:
        sys.stdout.write('\a')
        sys.stdout.flush()
        return {
            'direction': direction,
            'price': result['price'],
            'shares': result['shares'],
            'time': exec_time,
        }
    else:
        return None


# --- Main ------------------------------------------------------------------------

def main():
    trade_amount = TRADE_AMOUNT
    if len(sys.argv) > 1:
        try:
            trade_amount = float(sys.argv[1])
        except ValueError:
            pass

    # -- Logger --
    logger = RadarLogger()
    session_start = time.time()
    session_start_str = datetime.now().strftime("%H:%M:%S")
    trade_history = []  # list of individual trade P&L values

    # -- Clear screen and donation banner --
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    DONATION_WALLET = "0xa27Bf6B2B26594f8A1BF6Ab50B00Ae0e503d71F6"
    print()
    print(f"  {Y}{B}{'═' * 62}{X}")
    print(f"  {Y}{B}  If this tool helps you trade, consider supporting the dev!  {X}")
    print(f"  {Y}{B}{'═' * 62}{X}")
    print(f"  {D}  Built by a freelance developer in his spare time.{X}")
    print(f"  {D}  Any amount helps keep this project alive and improving.{X}")
    print(f"  {D}  Thank you for your support!{X}")
    print(f"  {Y}{'─' * 62}{X}")
    DONATION_URL = f"https://polymarket.com/profile/{DONATION_WALLET}"
    print(f"  {W}Send a tip on Polymarket:{X}")
    print(f"  {G}{DONATION_URL}{X}")
    print(f"  {Y}{B}{'═' * 62}{X}")
    for i in range(20, 0, -1):
        print(f"\r  {D}Starting in {i}s...{X}", end="", flush=True)
        time.sleep(1)
    print(f"\r  {G}Let's go!        {X}")
    print()

    # -- Connection (before clearing screen) --
    print(f"\n{C}{B}RADAR POLYMARKET - Connecting...{X}")

    print(f"   Connecting to Polymarket...", end="", flush=True)
    try:
        client, limit = create_client()
        balance = get_balance(client)
        print(f" {G}✓{X} Balance: ${balance:.2f}")
    except Exception as e:
        print(f" {R}✗{X} {e}")
        return

    print(f"   Finding market...", end="", flush=True)
    try:
        event, market, token_up, token_down, time_remaining = find_current_market()
        market_slug = event.get("slug", "")
        print(f" {G}✓{X} {market_slug}")
    except Exception as e:
        print(f" {R}✗{X} {e}")
        return

    # Get Price to Beat (BTC price at window start)
    price_to_beat = 0.0
    try:
        window_ts = int(market_slug.split('-')[-1])
        price_to_beat = get_price_at_timestamp(window_ts)
        if price_to_beat > 0:
            print(f"   Price to Beat: {G}${price_to_beat:,.2f}{X}")
    except Exception:
        pass

    # Start Binance WebSocket
    binance_ws = BinanceWS()
    print(f"   Connecting to Binance WS...", end="", flush=True)
    ws_started = binance_ws.start()
    if ws_started:
        # Wait briefly for initial connection
        for _ in range(20):
            if binance_ws.is_connected:
                break
            time.sleep(0.1)
        if binance_ws.is_connected:
            print(f" {G}✓{X} WebSocket connected")
        else:
            print(f" {Y}~{X} WebSocket connecting (HTTP fallback active)")
    else:
        print(f" {D}─{X} websocket-client not installed (HTTP only)")

    print(f"   {G}Ready! Starting in 2s...{X}")
    time.sleep(2)

    # -- Configure terminal --
    old_settings = None
    if not IS_WINDOWS:
        fd = sys.stdin.fileno()
        is_tty = os.isatty(fd)
        old_settings = termios.tcgetattr(fd) if is_tty else None
        if is_tty:
            tty.setcbreak(fd)

    try:
        # Clear screen and configure scroll region
        sys.stdout.write("\033[2J")       # clear screen
        sys.stdout.write("\033[H")        # cursor home
        # Scroll region: from HEADER_LINES+1 to end of terminal
        term_h = shutil.get_terminal_size().lines
        sys.stdout.write(f"\033[{HEADER_LINES + 1};{term_h}r")
        # Position cursor at start of scroll region
        sys.stdout.write(f"\033[{HEADER_LINES + 1};1H")
        sys.stdout.flush()

        last_beep = 0
        last_market_check = time.time()
        base_time = time_remaining
        positions = []
        current_signal = None
        alert_active = False  # True = already beeped, resets when price drops
        alert_side = ""
        alert_price = 0.0
        session_pnl = 0.0
        trade_count = 0
        status_msg = ""
        status_clear_at = 0  # timestamp to clear status_msg
        last_action = ""

        # Draw initial panel
        now_str = datetime.now().strftime("%H:%M:%S")
        draw_panel(now_str, balance, 0, '─', 0, {'rsi': 50, 'score': 0},
                   market_slug, time_remaining, 0, 0, positions, None, trade_amount,
                   session_pnl=session_pnl, trade_count=trade_count,
                   price_to_beat=price_to_beat, trade_history=trade_history,
                   last_action=last_action)

        print(f"   {D}Collecting initial data...{X}")

        while True:
            try:
                now = time.time()

                # Auto-clear status message after 3s
                if status_msg and now >= status_clear_at:
                    status_msg = ""

                # Refresh market every 60s
                if now - last_market_check > 60:
                    try:
                        event, market, new_token_up, new_token_down, time_remaining = find_current_market()
                        new_slug = event.get("slug", "")
                        # Detect market transition (new 15-min window)
                        if new_slug != market_slug:
                            if positions:
                                print(f"   {Y}{B}MARKET CHANGED → {new_slug} — clearing {len(positions)} old position(s){X}")
                                total_pnl, cnt, session_pnl, pnl_list = close_all_positions(
                                    positions, token_up, token_down, logger, "market_expired",
                                    session_pnl, trade_history)
                                trade_count += cnt
                                for d, sh, ep, xp, pnl in pnl_list:
                                    pnl_color = G if pnl >= 0 else R
                                    print(f"   {Y}  expired {d.upper()} {sh:.0f}sh @ ${ep:.2f} → ${xp:.2f} {pnl_color}P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}{X}")
                            history.clear()
                            # Fetch new Price to Beat
                            try:
                                window_ts = int(new_slug.split('-')[-1])
                                price_to_beat = get_price_at_timestamp(window_ts)
                            except Exception:
                                price_to_beat = 0.0
                            status_msg = f"{Y}MARKET SWITCHED → {new_slug}{X}"
                            status_clear_at = time.time() + 5
                        market_slug = new_slug
                        token_up = new_token_up
                        token_down = new_token_down
                        base_time = time_remaining
                        last_market_check = now
                    except Exception:
                        pass

                # Calculate decreasing time remaining
                elapsed = (now - last_market_check) / 60
                current_time = max(0, base_time - elapsed)

                # Auto-recover WS if not running
                if not binance_ws._running and HAS_WS:
                    binance_ws.start()

                # Collect data (WS candles if available, else HTTP)
                try:
                    ws_candles, data_source = binance_ws.get_candles(limit=20)
                    if ws_candles and len(ws_candles) >= 5:
                        bin_direction, confidence, details = get_full_analysis(candles=ws_candles)
                    else:
                        bin_direction, confidence, details = get_full_analysis()
                        data_source = 'http'
                    btc_price = details.get('btc_price', 0)
                    binance_data = {
                        'score': details.get('score', 0),
                        'rsi': details.get('rsi', 50),
                        'atr': details.get('atr', 0),
                        'macd_hist': details.get('macd_hist', 0),
                        'macd_hist_delta': details.get('macd_hist_delta', 0),
                        'vwap_pos': details.get('vwap_pos', 0),
                        'vwap_slope': details.get('vwap_slope', 0),
                        'bb_pos': details.get('bb_pos', 0.5),
                        'bb_squeeze': details.get('bb_squeeze', False),
                    }
                    current_regime = details.get('regime', 'RANGE')
                except Exception:
                    key = sleep_with_key(2)
                    if key:
                        pass
                    continue

                fut_up = _executor.submit(get_price, token_up, "BUY")
                fut_dn = _executor.submit(get_price, token_down, "BUY")
                up_buy = fut_up.result()
                down_buy = fut_dn.result()
                if up_buy <= 0:
                    sleep_with_key(2)
                    continue

                # Market phase
                current_phase, phase_threshold = get_market_phase(current_time)

                # Compute signal v2 (regime + phase aware)
                current_signal = compute_signal(up_buy, down_buy, btc_price, binance_data,
                                                regime=current_regime, phase=current_phase)
                if not current_signal:
                    sleep_with_key(2)
                    continue

                # Log signal snapshot
                logger.log_signal(btc_price, up_buy, down_buy, current_signal, binance_data,
                                  regime=current_regime, phase=current_phase)

                now_str = datetime.now().strftime("%H:%M:%S")

                # -- UPDATE STATIC PANEL --
                draw_panel(now_str, balance, btc_price, bin_direction, confidence,
                           binance_data, market_slug, current_time, up_buy,
                           down_buy, positions, current_signal, trade_amount,
                           alert_active, alert_side, alert_price,
                           session_pnl, trade_count,
                           regime=current_regime, phase=current_phase,
                           data_source=data_source, status_msg=status_msg, ws_status=binance_ws.status,
                           price_to_beat=price_to_beat, trade_history=trade_history,
                           last_action=last_action)

                # -- SCROLLING LOG --
                s_dir = current_signal['direction']
                strength = current_signal['strength']
                sug = current_signal.get('suggestion')
                trend = current_signal.get('trend', 0)
                sr_raw = current_signal.get('sr_raw', 0)

                print(format_scrolling_line(now_str, btc_price, up_buy, down_buy,
                                            current_signal, positions, current_regime))

                # --- OPPORTUNITY DETECTED ---
                # Use phase-dependent threshold (CLOSING phase = 999, blocks all)
                effective_threshold = max(SIGNAL_STRENGTH_BEEP, phase_threshold)
                if strength >= effective_threshold and s_dir != 'NEUTRAL' and sug:
                    sys.stdout.write('\a\a\a')
                    sys.stdout.flush()

                    phase_info = f" │ Phase: {current_phase}" if current_phase != 'MID' else ""
                    regime_info = f" │ Regime: {current_regime}" if current_regime != 'RANGE' else ""
                    print()
                    print(f"   {color}{B}{'═' * 55}{X}")
                    print(f"   {color}{B}OPPORTUNITY! {sym} {s_dir} {strength}%{X}")
                    print(f"   {W}   Entry: ${sug['entry']:.2f} → TP: ${sug['tp']:.2f} (+${sug['tp'] - sug['entry']:.2f}) / SL: ${sug['sl']:.2f} (-${sug['entry'] - sug['sl']:.2f}){X}")
                    print(f"   {W}   Amount: ${trade_amount:.0f} │ Trend: {trend:+.2f} │ SR: {sr_raw:+.1f}→{sr_adj:+.1f}{regime_info}{phase_info}{X}")
                    print(f"   {color}{B}{'═' * 55}{X}")

                    key = wait_for_key(timeout_sec=10)

                    if key == 's':
                        trade_dir = 'up' if s_dir == 'UP' else 'down'
                        info, balance, last_action = handle_buy(
                            client, trade_dir, trade_amount, token_up, token_down,
                            positions, balance, logger, session_pnl, reason="signal")
                        if info:
                            real_entry = info['price']
                            tp = min(real_entry + (sug['tp'] - sug['entry']), 0.95)
                            sl = max(real_entry - (sug['entry'] - sug['sl']), 0.03)
                            token_id = token_up if trade_dir == 'up' else token_down
                            tp_above = tp > real_entry
                            sl_above = sl < real_entry

                            print(f"   {M}{B}⏳ Monitoring TP ${tp:.2f} / SL ${sl:.2f}...{X}")
                            print()
                            reason, exit_price = monitor_tp_sl(token_id, tp, sl, tp_above, sl_above)

                            print()
                            if reason == 'TP':
                                exit_color = G
                            elif reason == 'CANCEL':
                                exit_color = Y
                            else:
                                exit_color = R
                            print(f"   {exit_color}{B}⚡ {reason} @ ${exit_price:.2f}! Closing...{X}")
                            close_msg = execute_close_market(client, token_up, token_down)
                            print(f"   {close_msg}")
                            pnl = (exit_price - real_entry) * info['shares']
                            session_pnl += pnl
                            trade_count += 1
                            trade_history.append(pnl)
                            logger.log_trade("CLOSE", trade_dir, info['shares'], exit_price,
                                             info['shares'] * exit_price, reason.lower(), pnl, session_pnl)
                            pnl_color = G if pnl >= 0 else R
                            last_action = f"{exit_color}{B}{reason}{X} @ ${exit_price:.2f} │ {pnl_color}P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}{X}"
                            print(f"   {pnl_color}{B}P&L: {'+' if pnl >= 0 else ''}${pnl:.2f} │ Session: {'+' if session_pnl >= 0 else ''}${session_pnl:.2f} ({trade_count} trades){X}")
                            balance += exit_price * info['shares']
                            positions.clear()
                            print(f"   {D}Returning to radar...{X}")
                            print()
                        else:
                            last_action = f"{R}✗ BUY {trade_dir.upper()} FAILED{X}"

                        last_beep = time.time()
                    elif key in ('u', 'd'):
                        manual_dir = 'up' if key == 'u' else 'down'
                        info, balance, last_action = handle_buy(
                            client, manual_dir, trade_amount, token_up, token_down,
                            positions, balance, logger, session_pnl, reason="manual")
                    else:
                        print(f"   {D}Ignored.{X}")
                        print()
                        last_beep = time.time()

                # Price alert (beeps once, resets when price drops)
                max_price = max(up_buy, down_buy)
                if max_price >= PRICE_ALERT:
                    if not alert_active:
                        alert_active = True
                        alert_side = "UP" if up_buy >= down_buy else "DOWN"
                        alert_price = max_price
                        sys.stdout.write('\a\a')
                        sys.stdout.flush()
                    else:
                        alert_price = max_price
                else:
                    alert_active = False
                    alert_side = ""
                    alert_price = 0.0

                # --- CHECK HOTKEYS DURING SLEEP ---
                cycle_time = 0.5 if data_source == 'ws' else 2
                key = sleep_with_key(cycle_time)
                if key in ('u', 'd'):
                    buy_dir = 'up' if key == 'u' else 'down'
                    _, balance, last_action = handle_buy(
                        client, buy_dir, trade_amount, token_up, token_down,
                        positions, balance, logger, session_pnl, reason="manual")
                elif key == 'c':
                    # Show closing status in static panel
                    status_msg = f"{Y}{B}EMERGENCY CLOSE...{X}"
                    last_action = f"{R}{B}EMERGENCY CLOSE{X}"
                    draw_panel(now_str, balance, btc_price, bin_direction, confidence,
                               binance_data, market_slug, current_time, up_buy,
                               down_buy, positions, current_signal, trade_amount,
                               alert_active, alert_side, alert_price,
                               session_pnl, trade_count,
                               regime=current_regime, phase=current_phase,
                               data_source=data_source, status_msg=status_msg, ws_status=binance_ws.status,
                               price_to_beat=price_to_beat, trade_history=trade_history,
                               last_action=last_action)
                    msg = execute_close_market(client, token_up, token_down)
                    if positions:
                        total_pnl, cnt, session_pnl, pnl_list = close_all_positions(
                            positions, token_up, token_down, logger, "emergency",
                            session_pnl, trade_history)
                        trade_count += cnt
                        for d, sh, ep, xp, pnl in pnl_list:
                            balance += xp * sh
                    # Show result in static panel
                    pnl_color = G if session_pnl >= 0 else R
                    status_msg = f"{G}✓ Closed{X} │ {pnl_color}{B}P&L: {'+' if session_pnl >= 0 else ''}${session_pnl:.2f}{X} {D}({trade_count} trades){X}"
                    last_action = f"{G}✓ CLOSED{X} │ {pnl_color}P&L: {'+' if session_pnl >= 0 else ''}${session_pnl:.2f}{X}"
                    draw_panel(now_str, balance, btc_price, bin_direction, confidence,
                               binance_data, market_slug, current_time, up_buy,
                               down_buy, positions, current_signal, trade_amount,
                               alert_active, alert_side, alert_price,
                               session_pnl, trade_count,
                               regime=current_regime, phase=current_phase,
                               data_source=data_source, status_msg=status_msg, ws_status=binance_ws.status,
                               price_to_beat=price_to_beat, trade_history=trade_history,
                               last_action=last_action)
                    status_clear_at = time.time() + 5
                elif key == 'q':
                    raise KeyboardInterrupt

            except KeyboardInterrupt:
                # Reset scroll region, clear screen
                sys.stdout.write("\033[r")
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.flush()
                if positions:
                    print(f"{Y}Closing positions before exit...{X}")
                    msg = execute_close_market(client, token_up, token_down)
                    print(f"   {msg}")
                    total_pnl, cnt, session_pnl, pnl_list = close_all_positions(
                        positions, token_up, token_down, logger, "exit",
                        session_pnl, trade_history)
                    trade_count += cnt

                # Session summary
                duration_min = (time.time() - session_start) / 60
                stats = print_session_summary(duration_min, trade_count, session_pnl, trade_history)

                # Log session to CSV
                logger.log_session_summary({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "start_time": session_start_str,
                    "end_time": datetime.now().strftime("%H:%M:%S"),
                    "duration_min": duration_min,
                    "total_trades": trade_count,
                    "wins": stats['wins'], "losses": stats['losses'],
                    "win_rate": stats['win_rate'],
                    "total_pnl": session_pnl,
                    "best_trade": stats['best'], "worst_trade": stats['worst'],
                    "profit_factor": stats['profit_factor'],
                    "max_drawdown": stats['max_drawdown'],
                })

                print(f"{Y}Radar terminated{X}")
                break
            except Exception as e:
                print(f"   {R}Error: {e}{X}")
                sleep_with_key(2)

    finally:
        # Stop WebSocket
        binance_ws.stop()
        # Shutdown thread pool
        _executor.shutdown(wait=False)
        # Restore terminal
        sys.stdout.write("\033[r")  # reset scroll region
        sys.stdout.flush()
        if not IS_WINDOWS and old_settings:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        logger.close()


if __name__ == "__main__":
    main()
