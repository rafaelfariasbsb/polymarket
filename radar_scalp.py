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
  python radar_scalp.py              # Uses TRADE_AMOUNT from .env ($4)
  python radar_scalp.py 10           # $10 per trade
"""

import sys
import os
import time
import platform
import shutil
import requests
from datetime import datetime
from collections import deque
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

# Force unbuffered output (avoid display delay)
sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.path.dirname(__file__))
from binance_api import get_full_analysis
from polymarket_api import (
    create_client, find_current_market, get_token_position,
    get_balance, monitor_order, CLOB,
)
from logger import RadarLogger

PRICE_ALERT = float(os.getenv('PRICE_ALERT', '0.80'))
SIGNAL_STRENGTH_BEEP = int(os.getenv('SIGNAL_STRENGTH_BEEP', '50'))
TRADE_AMOUNT = float(os.getenv('TRADE_AMOUNT', '4'))

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

HEADER_LINES = 14  # static panel lines


def get_price(token_id, side):
    try:
        resp = requests.get(
            f"{CLOB}/price",
            params={"token_id": token_id, "side": side},
            timeout=5,
        )
        return float(resp.json()["price"])
    except Exception:
        return 0.0


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
        return 'EARLY', 50     # 0-5min elapsed: conservative, need strong signal
    elif time_remaining > 5:
        return 'MID', 30       # 5-10min elapsed: normal operation
    elif time_remaining > 1:
        return 'LATE', 70      # 10-14min elapsed: only very strong signals
    else:
        return 'CLOSING', 999  # last minute: NO trading


def compute_signal(up_buy, down_buy, btc_price, binance, regime='RANGE', phase='MID'):
    """Compute scalp signal v2 - Trend-Following with regime awareness."""
    if up_buy <= 0 or btc_price <= 0 or not binance:
        return None

    history.append({
        'ts': time.time(), 'up': up_buy, 'down': down_buy, 'btc': btc_price,
    })

    score = 0.0
    rsi = binance.get('rsi', 50)
    bin_score = binance.get('score', 0)
    hist = list(history)

    # TREND FILTER (EMA of UP price)
    trend_strength = 0.0
    if len(hist) >= 12:
        up_prices = [h['up'] for h in hist[-20:] if h['up'] > 0]
        if len(up_prices) >= 12:
            fast_ema = _ema(up_prices, 5)
            slow_ema = _ema(up_prices, 12)
            ema_diff = (fast_ema - slow_ema) / slow_ema if slow_ema > 0 else 0
            trend_strength = max(-1.0, min(1.0, ema_diff / 0.02))

    # 1. BTC MOMENTUM (40%)
    if rsi < 25: rsi_c = 1.0
    elif rsi < 35: rsi_c = 0.6
    elif rsi < 45: rsi_c = 0.2
    elif rsi > 75: rsi_c = -1.0
    elif rsi > 65: rsi_c = -0.6
    elif rsi > 55: rsi_c = -0.2
    else: rsi_c = 0.0

    momentum = rsi_c * 0.4 + min(max(bin_score / 0.5, -1), 1) * 0.6
    score += momentum * 0.40

    # 2. DIVERGENCE (30%)
    div_score = 0.0
    btc_var = 0
    if len(hist) >= 6:
        h_old, h_new = hist[-6], hist[-1]
        if h_old['btc'] > 0 and h_old['up'] > 0:
            btc_var = (h_new['btc'] - h_old['btc']) / h_old['btc'] * 100
            poly_var = h_new['up'] - h_old['up']
            if btc_var > 0.01 and poly_var < 0.02:
                div_score = min(btc_var * 8, 1.0)
            elif btc_var < -0.01 and poly_var > -0.02:
                div_score = max(btc_var * 8, -1.0)
    score += div_score * 0.30

    # 3. SUPPORT/RESISTANCE (15%) + TREND FILTER
    sr_score = 0.0
    sr_raw = 0.0
    if len(hist) >= 10:
        ups = [h['up'] for h in hist if h['up'] > 0]
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

    score += sr_score * 0.15

    # 4. VOLATILITY (amplifier)
    atr = binance.get('atr', 0)
    vol_pct = (atr / btc_price * 100) if btc_price > 0 else 0
    high_vol = vol_pct > 0.03
    if high_vol:
        score *= 1.3

    # REGIME ADJUSTMENT
    # In CHOP regime, dampen signal (unreliable direction)
    if regime == 'CHOP':
        score *= 0.5
    # In strong trend, boost signals that align with trend direction
    elif regime in ('TREND_UP', 'TREND_DOWN'):
        trend_dir = 1.0 if regime == 'TREND_UP' else -1.0
        if (score > 0 and trend_dir > 0) or (score < 0 and trend_dir < 0):
            score *= 1.15  # aligned with regime
        else:
            score *= 0.7   # counter-trend, reduce confidence

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


# --- Static panel ----------------------------------------------------------------

def draw_panel(time_str, balance, btc_price, bin_direction, confidence, binance_data,
               market_slug, time_remaining, up_buy, down_buy, positions, signal,
               trade_amount, alert_active=False, alert_side="", alert_price=0.0,
               session_pnl=0.0, trade_count=0, regime="", phase=""):
    """Redraws the static panel at the top (HEADER_LINES lines)."""
    w = shutil.get_terminal_size().columns

    sys.stdout.write("\033[s")  # save cursor

    # Line 1: title bar
    sys.stdout.write(f"\033[1;1H\033[K")
    sys.stdout.write(f" {C}{B}{'═' * (w - 2)}{X}")

    # Line 2: header with time and balance
    sys.stdout.write(f"\033[2;1H\033[K")
    sys.stdout.write(f" {C}{B}SCALP RADAR{X} │ {W}{time_str}{X} │ Balance: {G}${balance:.2f}{X} │ Trade: {W}${trade_amount:.0f}{X}")

    # Line 3: separator
    sys.stdout.write(f"\033[3;1H\033[K")
    sys.stdout.write(f" {C}{'═' * (w - 2)}{X}")

    # Line 4: Binance
    bin_color = G if bin_direction == 'UP' else R if bin_direction == 'DOWN' else D
    rsi_val = binance_data.get('rsi', 50)
    score_bin = binance_data.get('score', 0)
    vol_pct = signal.get('vol_pct', 0) if signal else 0
    vol_str = f"{Y}HIGH{X}" if (signal and signal.get('high_vol')) else f"{D}normal{X}"
    sys.stdout.write(f"\033[4;1H\033[K")
    # Regime indicator
    if regime == 'TREND_UP':
        reg_str = f"{G}{B}TREND▲{X}"
    elif regime == 'TREND_DOWN':
        reg_str = f"{R}{B}TREND▼{X}"
    elif regime == 'CHOP':
        reg_str = f"{Y}{B}CHOP{X}"
    else:
        reg_str = f"{D}RANGE{X}"
    sys.stdout.write(f" {C}BINANCE {X}│ BTC: {W}${btc_price:>8,.2f}{X} │ {bin_color}{B}{bin_direction}{X} (score:{score_bin:+.2f} conf:{confidence:.0f}%) │ RSI:{rsi_val:.0f} │ Vol:{vol_str} │ {reg_str}")

    # Line 5: Market
    sys.stdout.write(f"\033[5;1H\033[K")
    time_color = R if time_remaining < 2 else Y if time_remaining < 5 else G
    # Phase indicator
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
    sys.stdout.write(f" {Y}MARKET  {X}│ {market_slug} │ Closes in: {time_color}{time_remaining:.1f}min{X} │ {phase_str}")

    # Line 6: Polymarket
    sys.stdout.write(f"\033[6;1H\033[K")
    sys.stdout.write(f" {G}POLY    {X}│ UP: {G}${up_buy:.2f}{X}/{G}${1.0 - down_buy:.2f}{X} ({G}{up_buy * 100:.0f}%{X}) │ DOWN: {R}${down_buy:.2f}{X}/{R}${1.0 - up_buy:.2f}{X} ({R}{down_buy * 100:.0f}%{X})")

    # Line 7: Positions + Session P&L
    sys.stdout.write(f"\033[7;1H\033[K")
    pnl_color = G if session_pnl >= 0 else R
    pnl_str = f"{pnl_color}{B}P&L: {'+' if session_pnl >= 0 else ''}${session_pnl:.2f}{X} {D}({trade_count} trades){X}"
    if positions:
        parts = []
        for p in positions:
            p_color = G if p['direction'] == 'up' else R
            parts.append(f"{p_color}{p['direction'].upper()} {p['shares']:.0f}sh @ ${p['price']:.2f}{X}")
        sys.stdout.write(f" {M}POSITION{X}│ {' │ '.join(parts)} │ {pnl_str}")
    else:
        sys.stdout.write(f" {M}POSITION{X}│ {D}None{X} │ {pnl_str}")

    # Line 8: Signal
    sys.stdout.write(f"\033[8;1H\033[K")
    if signal:
        s_dir = signal['direction']
        strength = signal['strength']
        blocks = strength // 10
        bar_s = '█' * blocks + '░' * (10 - blocks)
        if s_dir == 'UP': s_color, s_sym = G, '▲'
        elif s_dir == 'DOWN': s_color, s_sym = R, '▼'
        else: s_color, s_sym = D, '─'
        trend = signal.get('trend', 0)
        sr_raw = signal.get('sr_raw', 0)
        sr_adj = signal.get('sr_adj', 0)
        rsi_s = signal.get('rsi', 50)
        rsi_arrow = '↑' if rsi_s < 45 else '↓' if rsi_s > 55 else '─'
        t_str = f"T:{trend:+.1f}" if abs(trend) > 0.3 else f"{D}T:0.0{X}"
        sr_str = f"SR:{sr_raw:+.1f}→{sr_adj:+.1f}" if sr_raw != 0 else f"{D}SR:0.0{X}"
        sys.stdout.write(f" {W}SIGNAL  {X}│ {s_color}{B}{s_sym} {s_dir:<7s} {strength:>3d}%{X} [{bar_s}] │ RSI:{rsi_s:.0f}{rsi_arrow} │ {t_str} │ {sr_str}")
    else:
        sys.stdout.write(f" {W}SIGNAL  {X}│ {D}Waiting for data...{X}")

    # Line 9: Alert
    sys.stdout.write(f"\033[9;1H\033[K")
    if alert_active:
        sys.stdout.write(f" {Y}{B}ALERT   {X}│ {Y}{B}{alert_side} @ ${alert_price:.2f} (>= ${PRICE_ALERT:.2f}){X}")
    else:
        sys.stdout.write(f" {D}ALERT   {X}│ {D}─{X}")

    # Line 10: separator
    sys.stdout.write(f"\033[10;1H\033[K")
    sys.stdout.write(f" {'─' * (w - 2)}")

    # Line 11: Hotkeys
    sys.stdout.write(f"\033[11;1H\033[K")
    sys.stdout.write(f" {W}{B}U{X}{D}=buy UP{X} │ {W}{B}D{X}{D}=buy DOWN{X} │ {W}{B}C{X}{D}=close all{X} │ {W}{B}S{X}{D}=accept signal{X} │ {W}{B}Q{X}{D}=exit{X}")

    # Line 12: bottom separator (full width)
    sys.stdout.write(f"\033[12;1H\033[K")
    sys.stdout.write(f" {C}{B}{'═' * (w - 2)}{X}")

    # Line 13: column headers
    sys.stdout.write(f"\033[13;1H\033[K")
    sys.stdout.write(f"   {D}{'TIME':8s} │ {'BTC':>12s} │ {'UP':>8s} {'DN':>8s} │ {'RSI':>6s} │ {'SIGNAL  ─  STRENGTH':>27s} │ {'VOL':4s} │ {'TREND':>7s} │ {'S/R':>13s} │ {'RG':2s}{X}")

    # Line 14: blank (space before log)
    sys.stdout.write(f"\033[14;1H\033[K")

    sys.stdout.write("\033[u")  # restore cursor
    sys.stdout.flush()


# --- Trade execution -------------------------------------------------------------

def execute_buy_market(client, direction, amount_usd, token_up, token_down):
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

    status, details = monitor_order(client, order_id, interval=2, timeout_sec=30)

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
    """Monitor price every 0.5s until TP or SL is hit. Returns 'TP' or 'SL'."""
    while True:
        price = get_price(token_id, "BUY")
        if price <= 0:
            time.sleep(0.5)
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
        sys.stdout.write(f"\r   {D}{now}{X} | ${price:.2f} | SL ${sl:.2f} [{bar}] TP ${tp:.2f}   ")
        sys.stdout.flush()

        time.sleep(0.5)


# --- Hotkey buy ------------------------------------------------------------------

def execute_hotkey(client, direction, trade_amount, token_up, token_down):
    """Execute manual buy via hotkey (u/d). Returns buy info or None."""
    color = G if direction == 'up' else R
    name = 'UP' if direction == 'up' else 'DOWN'
    print()
    print(f"   {color}{B}⚡ MANUAL BUY {name} ${trade_amount:.0f}...{X}")

    result, msg = execute_buy_market(client, direction, trade_amount, token_up, token_down)
    exec_time = datetime.now().strftime("%H:%M:%S")
    print(f"   [{exec_time}] {msg}")

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
        print(f"   {R}Buy failed{X}")
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

    # -- Connection (before clearing screen) --
    print(f"\n{C}{B}SCALP RADAR - Connecting...{X}")

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

        # Draw initial panel
        now_str = datetime.now().strftime("%H:%M:%S")
        draw_panel(now_str, balance, 0, '─', 0, {'rsi': 50, 'score': 0},
                   market_slug, time_remaining, 0, 0, positions, None, trade_amount,
                   session_pnl=session_pnl, trade_count=trade_count)

        print(f"   {D}Collecting initial data...{X}")

        while True:
            try:
                now = time.time()

                # Refresh market every 60s
                if now - last_market_check > 60:
                    try:
                        event, market, token_up, token_down, time_remaining = find_current_market()
                        market_slug = event.get("slug", "")
                        base_time = time_remaining
                        last_market_check = now
                    except Exception:
                        pass

                # Calculate decreasing time remaining
                elapsed = (now - last_market_check) / 60
                current_time = max(0, base_time - elapsed)

                # Collect data
                try:
                    bin_direction, confidence, details = get_full_analysis()
                    btc_price = details.get('btc_price', 0)
                    binance_data = {
                        'score': details.get('score', 0),
                        'rsi': details.get('rsi', 50),
                        'atr': details.get('atr', 0),
                    }
                    current_regime = details.get('regime', 'RANGE')
                except Exception:
                    key = sleep_with_key(2)
                    if key:
                        pass
                    continue

                up_buy = get_price(token_up, "BUY")
                down_buy = get_price(token_down, "BUY")
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
                           regime=current_regime, phase=current_phase)

                # -- SCROLLING LOG --
                s_dir = current_signal['direction']
                strength = current_signal['strength']
                rsi_val = current_signal['rsi']
                sug = current_signal.get('suggestion')
                trend = current_signal.get('trend', 0)
                sr_raw = current_signal.get('sr_raw', 0)
                sr_adj = current_signal.get('sr_adj', 0)

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
                col_rsi    = f"RSI:{rsi_val:>2.0f}{rsi_arrow}"
                col_signal = f"{color}{B}{sym} {s_dir:<7s} {strength:>3d}%{X}"
                col_bar    = f"[{bar}]"
                col_vol    = f"{Y}VOL↑{X}" if current_signal['high_vol'] else "    "
                if abs(trend) > 0.3:
                    t_sym = '⬆' if trend > 0 else '⬇'
                    t_color = G if trend > 0 else R
                    t_text = f"T:{trend:+.1f}{t_sym}"
                    col_trend = f"{t_color}{t_text:<7s}{X}"
                else:
                    col_trend = f"{D}{'T: 0.0':<7s}{X}"
                if sr_raw != 0:
                    sr_text = f"SR:{sr_raw:+.1f}→{sr_adj:+.1f}"
                    col_sr = f"{M}{sr_text:<13s}{X}"
                else:
                    col_sr = f"{D}{'SR: 0.0':<13s}{X}"

                pos_str = ""
                if positions:
                    total_shares = sum(p['shares'] for p in positions)
                    dirs = set(p['direction'] for p in positions)
                    d_str = '/'.join(d.upper() for d in dirs)
                    pos_str = f" {M}{B}[{d_str} {total_shares:.0f}sh]{X}"

                # Regime tag in scrolling log
                if current_regime == 'TREND_UP':
                    col_regime = f"{G}T▲{X}"
                elif current_regime == 'TREND_DOWN':
                    col_regime = f"{R}T▼{X}"
                elif current_regime == 'CHOP':
                    col_regime = f"{Y}CH{X}"
                else:
                    col_regime = f"{D}RG{X}"

                line = f"   {col_time} │ {col_btc} │ {col_up} {col_dn} │ {col_rsi} │ {col_signal} {col_bar} │ {col_vol} │ {col_trend} │ {col_sr} │ {col_regime}{pos_str}"
                print(line)

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
                        info = execute_hotkey(client, trade_dir, trade_amount, token_up, token_down)
                        if info:
                            positions.append(info)
                            balance -= info['price'] * info['shares']
                            logger.log_trade("BUY", trade_dir, info['shares'], info['price'],
                                             info['shares'] * info['price'], "signal", 0, session_pnl)
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
                            exit_color = G if reason == 'TP' else R
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
                            print(f"   {pnl_color}{B}P&L: {'+' if pnl >= 0 else ''}${pnl:.2f} │ Session: {'+' if session_pnl >= 0 else ''}${session_pnl:.2f} ({trade_count} trades){X}")
                            balance += exit_price * info['shares']
                            positions.clear()
                            print(f"   {D}Returning to radar...{X}")
                            print()

                        last_beep = time.time()
                    elif key in ('u', 'd'):
                        manual_dir = 'up' if key == 'u' else 'down'
                        info = execute_hotkey(client, manual_dir, trade_amount, token_up, token_down)
                        if info:
                            positions.append(info)
                            balance -= info['price'] * info['shares']
                            logger.log_trade("BUY", manual_dir, info['shares'], info['price'],
                                             info['shares'] * info['price'], "manual", 0, session_pnl)
                        print()
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
                key = sleep_with_key(2)
                if key == 'u':
                    info = execute_hotkey(client, 'up', trade_amount, token_up, token_down)
                    if info:
                        positions.append(info)
                        balance -= info['price'] * info['shares']
                        logger.log_trade("BUY", "up", info['shares'], info['price'],
                                         info['shares'] * info['price'], "manual", 0, session_pnl)
                    print()
                elif key == 'd':
                    info = execute_hotkey(client, 'down', trade_amount, token_up, token_down)
                    if info:
                        positions.append(info)
                        balance -= info['price'] * info['shares']
                        logger.log_trade("BUY", "down", info['shares'], info['price'],
                                         info['shares'] * info['price'], "manual", 0, session_pnl)
                    print()
                elif key == 'c':
                    print()
                    print(f"   {Y}{B}EMERGENCY CLOSE...{X}")
                    msg = execute_close_market(client, token_up, token_down)
                    exec_time = datetime.now().strftime("%H:%M:%S")
                    print(f"   [{exec_time}] {msg}")
                    if positions:
                        for p in positions:
                            token_id = token_up if p['direction'] == 'up' else token_down
                            current_price = get_price(token_id, "SELL")
                            pnl = (current_price - p['price']) * p['shares']
                            session_pnl += pnl
                            trade_count += 1
                            trade_history.append(pnl)
                            logger.log_trade("CLOSE", p['direction'], p['shares'], current_price,
                                             p['shares'] * current_price, "emergency", pnl, session_pnl)
                            pnl_color = G if pnl >= 0 else R
                            balance += current_price * p['shares']
                            print(f"   {pnl_color}  {p['direction'].upper()} {p['shares']:.0f}sh @ ${p['price']:.2f} → ${current_price:.2f} = {'+' if pnl >= 0 else ''}${pnl:.2f}{X}")
                        pnl_color = G if session_pnl >= 0 else R
                        print(f"   {pnl_color}{B}Session: {'+' if session_pnl >= 0 else ''}${session_pnl:.2f} ({trade_count} trades){X}")
                        positions.clear()
                    print()
                elif key == 'q':
                    raise KeyboardInterrupt

            except KeyboardInterrupt:
                # Reset scroll region before exit
                sys.stdout.write("\033[r")
                sys.stdout.flush()
                print()
                if positions:
                    print(f"{Y}Closing positions before exit...{X}")
                    msg = execute_close_market(client, token_up, token_down)
                    print(f"   {msg}")
                    for p in positions:
                        token_id = token_up if p['direction'] == 'up' else token_down
                        current_price = get_price(token_id, "SELL")
                        pnl = (current_price - p['price']) * p['shares']
                        session_pnl += pnl
                        trade_count += 1
                        trade_history.append(pnl)
                        logger.log_trade("CLOSE", p['direction'], p['shares'], current_price,
                                         p['shares'] * current_price, "exit", pnl, session_pnl)
                    positions.clear()

                # Session summary
                duration_min = (time.time() - session_start) / 60
                wins = sum(1 for t in trade_history if t > 0)
                losses = sum(1 for t in trade_history if t <= 0)
                win_rate = (wins / len(trade_history) * 100) if trade_history else 0
                best = max(trade_history) if trade_history else 0
                worst = min(trade_history) if trade_history else 0
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

                print()
                print(f" {C}{B}{'═' * 45}{X}")
                print(f" {C}{B} SESSION SUMMARY{X}")
                print(f" {D}{'─' * 45}{X}")
                print(f"  Duration:       {duration_min:.0f} min")
                print(f"  Total Trades:   {trade_count}")
                if trade_history:
                    wr_color = G if win_rate >= 50 else R
                    print(f"  Win Rate:       {wr_color}{win_rate:.0f}%{X} ({G}{wins}W{X} / {R}{losses}L{X})")
                    pnl_c = G if session_pnl >= 0 else R
                    print(f"  Total P&L:      {pnl_c}{'+' if session_pnl >= 0 else ''}${session_pnl:.2f}{X}")
                    print(f"  Best Trade:     {G}+${best:.2f}{X}")
                    print(f"  Worst Trade:    {R}${worst:.2f}{X}")
                    print(f"  Profit Factor:  {W}{profit_factor:.2f}{X}")
                    print(f"  Max Drawdown:   {R}-${max_dd:.2f}{X}")
                else:
                    print(f"  {D}No trades this session{X}")
                print(f" {C}{B}{'═' * 45}{X}")
                print()

                # Log session to CSV
                logger.log_session_summary({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "start_time": session_start_str,
                    "end_time": datetime.now().strftime("%H:%M:%S"),
                    "duration_min": duration_min,
                    "total_trades": trade_count,
                    "wins": wins, "losses": losses,
                    "win_rate": win_rate,
                    "total_pnl": session_pnl,
                    "best_trade": best, "worst_trade": worst,
                    "profit_factor": profit_factor,
                    "max_drawdown": max_dd,
                })

                print(f"{Y}Radar terminated{X}")
                break
            except Exception as e:
                print(f"   {R}Error: {e}{X}")
                sleep_with_key(2)

    finally:
        # Restore terminal
        sys.stdout.write("\033[r")  # reset scroll region
        sys.stdout.flush()
        if not IS_WINDOWS and old_settings:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        logger.close()


if __name__ == "__main__":
    main()
