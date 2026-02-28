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

from __future__ import annotations

import sys
import os
import time
import logging
import platform
import shutil
import requests
from datetime import datetime
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    # Enable ANSI escape codes on Windows 10+
    os.system("")
else:
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from market_config import MarketConfig
from binance_api import get_full_analysis, get_price_at_timestamp
from polymarket_api import (
    create_client, find_current_market, get_balance, CLOB,
)
from logger import RadarLogger
from ws_binance import BinanceWS, HAS_WS
from colors import G, R, Y, C, W, B, D, M, BL, X
from signal_engine import compute_signal, get_market_phase, TP_MAX_PRICE, SL_MIN_PRICE
from ui_panel import draw_panel, format_scrolling_line, HEADER_LINES
from trade_executor import (
    handle_buy, execute_close_market, close_all_positions, monitor_tp_sl,
    sync_positions,
)
from input_handler import wait_for_key, sleep_with_key
from session_stats import print_session_summary

# Configuration
PRICE_ALERT = float(os.getenv('PRICE_ALERT', '0.80'))
PRICE_ALERT_ENABLED = os.getenv('PRICE_ALERT_ENABLED', '1').lower() in ('1', 'true', 'yes')
SIGNAL_STRENGTH_BEEP = int(os.getenv('SIGNAL_STRENGTH_BEEP', '50'))
SIGNAL_ENABLED = os.getenv('SIGNAL_ENABLED', '1').lower() in ('1', 'true', 'yes')
TRADE_AMOUNT = float(os.getenv('TRADE_AMOUNT', '4'))
PRICE_BEAT_ALERT = float(os.getenv('PRICE_BEAT_ALERT', '80'))
HISTORY_MAXLEN = 60
MARKET_REFRESH_INTERVAL = 60  # seconds between market slug checks

# Persistent HTTP session (reuses TCP connections via keep-alive)
_session = requests.Session()

# Persistent thread pool (avoid recreating every cycle)
_executor = ThreadPoolExecutor(max_workers=2)


class PriceCache:
    """TTL-based cache for get_price() to avoid duplicate HTTP calls."""

    def __init__(self, ttl_sec=0.5):
        self._cache = {}
        self._ttl = ttl_sec

    def get(self, token_id: str, side: str) -> float:
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
            self._cache[key] = (price, now)  # only cache successful fetches
            return price
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.debug("PriceCache fetch error for %s/%s: %s", token_id[:8], side, e)
            return 0.0

    def invalidate(self):
        self._cache.clear()


_price_cache = PriceCache(ttl_sec=0.5)


def get_price(token_id, side):
    return _price_cache.get(token_id, side)


class TradingSession:
    """Encapsulates all mutable state for a trading session."""

    def __init__(self):
        # Market state
        self.market_slug = ""
        self.token_up = ""
        self.token_down = ""
        self.price_to_beat = 0.0
        self.base_time = 0.0

        # Trading state
        self.positions = []
        self.balance = 0.0
        self.session_pnl = 0.0
        self.trade_count = 0
        self.trade_history = []
        self.current_signal = None

        # Alert state
        self.alert_active = False
        self.alert_side = ""
        self.alert_price = 0.0

        # UI state
        self.status_msg = ""
        self.status_clear_at = 0
        self.last_action = ""
        self.poly_latency_ms = 0

        # Timing
        self.last_beep = 0
        self.last_market_check = 0
        self.last_phase = ""

        # Data history
        self.history = deque(maxlen=HISTORY_MAXLEN)

        # Error tracking for exponential backoff
        self.binance_errors = 0
        self.market_refresh_errors = 0

    def set_status(self, msg, duration=3):
        self.status_msg = msg
        self.status_clear_at = time.time() + duration

    def clear_expired_status(self):
        if self.status_msg and time.time() >= self.status_clear_at:
            self.status_msg = ""

    def update_alert(self, up_buy, down_buy):
        if not PRICE_ALERT_ENABLED:
            return
        max_price = max(up_buy, down_buy)
        if max_price >= PRICE_ALERT:
            if not self.alert_active:
                self.alert_active = True
                self.alert_side = "UP" if up_buy >= down_buy else "DOWN"
                self.alert_price = max_price
            else:
                self.alert_price = max_price
        else:
            self.alert_active = False
            self.alert_side = ""
            self.alert_price = 0.0


# --- Main ------------------------------------------------------------------------

def main():
    trade_amount = TRADE_AMOUNT
    if len(sys.argv) > 1:
        try:
            trade_amount = float(sys.argv[1])
        except ValueError:
            pass

    # -- Market config --
    try:
        config = MarketConfig()
    except ValueError as e:
        print(f"\033[91m{e}\033[0m")
        return

    # -- Logger --
    radar_logger = RadarLogger()
    session_start = time.time()
    session_start_str = datetime.now().strftime("%H:%M:%S")

    # -- Session state --
    session = TradingSession()

    # -- Clear screen and donation banner --
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    DONATION_WALLET = "0xa27Bf6B2B26594f8A1BF6Ab50B00Ae0e503d71F6"
    print()
    print(f"  {C}{B}{'═' * 62}{X}")
    print(f"  {C}{B}  POLYMARKET CRYPTO SCALPING RADAR{X}")
    print(f"  {C}{'─' * 62}{X}")
    print(f"  {W}  Real-time scalping tool for Polymarket updown markets.{X}")
    print(f"  {W}  Monitors Binance price + 6 indicators (RSI, MACD, VWAP,{X}")
    print(f"  {W}  Bollinger, S/R, ADX) to generate UP/DOWN signals with{X}")
    print(f"  {W}  regime detection and phase-aware thresholds.{X}")
    print(f"  {D}  Asset: {G}{config.display_name}{D} │ Window: {G}{config.window_min}m{D} │ Trade: {G}${trade_amount:.0f}{X}")
    print(f"  {C}{'═' * 62}{X}")
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
    print(f"\n{C}{B}RADAR POLYMARKET - {config.display_name} {config.window_min}m - Connecting...{X}")

    print(f"   Connecting to Polymarket...", end="", flush=True)
    try:
        client, limit = create_client()
        session.balance = get_balance(client)
        print(f" {G}✓{X} Balance: ${session.balance:.2f}")
    except Exception as e:
        print(f" {R}✗{X} {e}")
        return

    print(f"   Finding {config.display_name} {config.window_min}m market...", end="", flush=True)
    try:
        event, market, session.token_up, session.token_down, time_remaining = find_current_market(config)
        session.market_slug = event.get("slug", "")
        print(f" {G}✓{X} {session.market_slug}")
    except Exception as e:
        print(f" {R}✗{X} {e}")
        return

    # Get Price to Beat (asset price at window start)
    try:
        window_ts = int(session.market_slug.split('-')[-1])
        session.price_to_beat = get_price_at_timestamp(window_ts, symbol=config.binance_symbol)
        if session.price_to_beat > 0:
            print(f"   Price to Beat: {G}${session.price_to_beat:,.2f}{X}")
    except (ValueError, IndexError, requests.RequestException) as e:
        logger.debug("Price to beat fetch error: %s", e)

    # Sync existing positions (bought directly on Polymarket platform)
    print(f"   Checking existing positions...", end="", flush=True)
    changes = sync_positions(client, session.token_up, session.token_down,
                             session.positions, get_price)
    if changes:
        print(f" {G}✓{X} Found {len(changes)} position(s):")
        for direction, shares, price, action in changes:
            d_color = G if direction == 'up' else R
            print(f"      {d_color}● {direction.upper()}{X} {shares:.0f}sh @ ${price:.2f} (from platform)")
    else:
        print(f" {D}─{X} No existing positions")

    # Start Binance WebSocket
    binance_ws = BinanceWS(symbol=config.ws_symbol)
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

        session.last_market_check = time.time()
        session.base_time = time_remaining

        # Draw initial panel
        now_str = datetime.now().strftime("%H:%M:%S")
        draw_panel(now_str, session.balance, 0, '─', 0, {'rsi': 50, 'score': 0},
                   session.market_slug, time_remaining, 0, 0, session.positions, None, trade_amount,
                   session_pnl=session.session_pnl, trade_count=session.trade_count,
                   price_to_beat=session.price_to_beat, trade_history=session.trade_history,
                   last_action=session.last_action, asset_name=config.display_name)

        print(f"   {D}Collecting initial data...{X}")

        while True:
            try:
                now = time.time()

                # Auto-clear status message
                session.clear_expired_status()

                # Refresh market (with exponential backoff on errors)
                refresh_interval = min(
                    MARKET_REFRESH_INTERVAL * (2 ** session.market_refresh_errors),
                    300,
                )
                if now - session.last_market_check > refresh_interval:
                    try:
                        event, market, new_token_up, new_token_down, time_remaining = find_current_market(config)
                        new_slug = event.get("slug", "")
                        session.market_refresh_errors = 0  # reset on success
                        # Detect market transition (new window)
                        if new_slug != session.market_slug:
                            if session.positions:
                                print(f"   {Y}{B}MARKET CHANGED → {new_slug} — clearing {len(session.positions)} old position(s){X}")
                                total_pnl, cnt, session.session_pnl, pnl_list = close_all_positions(
                                    session.positions, session.token_up, session.token_down,
                                    radar_logger, "market_expired",
                                    session.session_pnl, session.trade_history, get_price)
                                session.trade_count += cnt
                                for d, sh, ep, xp, pnl in pnl_list:
                                    pnl_color = G if pnl >= 0 else R
                                    print(f"   {Y}  expired {d.upper()} {sh:.0f}sh @ ${ep:.2f} → ${xp:.2f} {pnl_color}P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}{X}")
                            session.history.clear()
                            # Fetch new Price to Beat
                            try:
                                window_ts = int(new_slug.split('-')[-1])
                                session.price_to_beat = get_price_at_timestamp(window_ts, symbol=config.binance_symbol)
                            except (ValueError, IndexError, requests.RequestException) as e:
                                logger.debug("Price to beat fetch error on market switch: %s", e)
                                session.price_to_beat = 0.0
                            session.set_status(f"{Y}MARKET SWITCHED → {new_slug}{X}", duration=5)
                        session.market_slug = new_slug
                        session.token_up = new_token_up
                        session.token_down = new_token_down
                        session.base_time = time_remaining
                        session.last_market_check = now

                        # Sync positions with platform (detect buys/sells made outside the radar)
                        try:
                            changes = sync_positions(
                                client, session.token_up, session.token_down,
                                session.positions, get_price)
                            if changes:
                                for direction, shares, price, action in changes:
                                    d_color = G if direction == 'up' else R
                                    if action == 'added':
                                        print(f"   {C}{B}SYNC{X} {d_color}● {direction.upper()}{X} +{shares:.0f}sh @ ${price:.2f} {D}(detected on platform){X}")
                                    else:
                                        print(f"   {C}{B}SYNC{X} {d_color}● {direction.upper()}{X} -{shares:.0f}sh {D}(sold on platform){X}")
                        except Exception as e:
                            logger.debug("Position sync error: %s", e)

                        # Re-sync balance with platform
                        try:
                            session.balance = get_balance(client)
                        except Exception as e:
                            logger.debug("Balance sync error: %s", e)

                    except (requests.RequestException, KeyError, ValueError) as e:
                        session.market_refresh_errors += 1
                        logger.debug("Market refresh error (attempt %d): %s",
                                     session.market_refresh_errors, e)
                        session.last_market_check = now

                # Calculate decreasing time remaining
                elapsed = (now - session.last_market_check) / 60
                current_time = max(0, session.base_time - elapsed)

                # Auto-recover WS if not running
                if not binance_ws._running and HAS_WS:
                    binance_ws.start()

                # Collect data (WS candles if available, else HTTP)
                try:
                    ws_candles, data_source = binance_ws.get_candles(limit=20)
                    if ws_candles and len(ws_candles) >= 5:
                        bin_direction, confidence, details = get_full_analysis(candles=ws_candles, symbol=config.binance_symbol)
                    else:
                        bin_direction, confidence, details = get_full_analysis(symbol=config.binance_symbol)
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
                    session.binance_errors = 0  # reset on success
                except Exception as e:
                    session.binance_errors += 1
                    delay = min(2 * (2 ** (session.binance_errors - 1)), 30)
                    now_str = datetime.now().strftime("%H:%M:%S")
                    print(f"   {D}{now_str}{X} │ {Y}Binance error (retry {session.binance_errors}, wait {delay:.0f}s): {e}{X}")
                    draw_panel(now_str, session.balance, 0, '─', 0, {'rsi': 50, 'score': 0},
                               session.market_slug, current_time, 0, 0, session.positions, None, trade_amount,
                               session_pnl=session.session_pnl, trade_count=session.trade_count,
                               status_msg=f"{Y}Binance error — retrying in {delay:.0f}s...{X}",
                               price_to_beat=session.price_to_beat, trade_history=session.trade_history,
                               last_action=session.last_action, asset_name=config.display_name)
                    key = sleep_with_key(delay)
                    if key == 'q':
                        raise KeyboardInterrupt
                    continue

                _poly_t0 = time.time()
                fut_up = _executor.submit(get_price, session.token_up, "BUY")
                fut_dn = _executor.submit(get_price, session.token_down, "BUY")
                up_buy = fut_up.result()
                down_buy = fut_dn.result()
                session.poly_latency_ms = (time.time() - _poly_t0) * 1000
                if up_buy <= 0:
                    now_str = datetime.now().strftime("%H:%M:%S")
                    print(f"   {Y}Token price unavailable (UP=${up_buy:.2f} DN=${down_buy:.2f}) — retrying...{X}")
                    draw_panel(now_str, session.balance, btc_price, bin_direction, confidence,
                               binance_data, session.market_slug, current_time, up_buy,
                               down_buy, session.positions, None, trade_amount,
                               session_pnl=session.session_pnl, trade_count=session.trade_count,
                               regime=current_regime, data_source=data_source,
                               status_msg=f"{Y}Token prices unavailable — retrying...{X}",
                               ws_status=binance_ws.status,
                               price_to_beat=session.price_to_beat, trade_history=session.trade_history,
                               last_action=session.last_action, asset_name=config.display_name,
                               poly_latency_ms=session.poly_latency_ms)
                    key = sleep_with_key(2)
                    if key == 'q':
                        raise KeyboardInterrupt
                    continue

                # Market phase
                current_phase, phase_threshold = get_market_phase(current_time, config.window_min)

                session.last_phase = current_phase

                # Update history for signal computation
                session.history.append({
                    'ts': time.time(), 'up': up_buy, 'down': down_buy, 'btc': btc_price,
                })

                # Compute signal (regime + phase aware)
                session.current_signal = compute_signal(
                    up_buy, down_buy, btc_price, binance_data,
                    session.history, regime=current_regime, phase=current_phase)
                if not session.current_signal:
                    key = sleep_with_key(2)
                    if key == 'q':
                        raise KeyboardInterrupt
                    continue

                # Log signal snapshot
                radar_logger.log_signal(btc_price, up_buy, down_buy, session.current_signal,
                                        binance_data, regime=current_regime, phase=current_phase)

                now_str = datetime.now().strftime("%H:%M:%S")

                # -- UPDATE STATIC PANEL --
                draw_panel(now_str, session.balance, btc_price, bin_direction, confidence,
                           binance_data, session.market_slug, current_time, up_buy,
                           down_buy, session.positions, session.current_signal, trade_amount,
                           session.alert_active, session.alert_side, session.alert_price,
                           session.session_pnl, session.trade_count,
                           regime=current_regime, phase=current_phase,
                           data_source=data_source, status_msg=session.status_msg,
                           ws_status=binance_ws.status,
                           price_to_beat=session.price_to_beat, trade_history=session.trade_history,
                           last_action=session.last_action, asset_name=config.display_name,
                           poly_latency_ms=session.poly_latency_ms)

                # -- SCROLLING LOG --
                s_dir = session.current_signal['direction']
                strength = session.current_signal['strength']
                sug = session.current_signal.get('suggestion')
                trend = session.current_signal.get('trend', 0)
                sr_raw = session.current_signal.get('sr_raw', 0)
                sr_adj = session.current_signal.get('sr_adj', 0)
                if s_dir == 'UP': color, sym = G, '▲'
                elif s_dir == 'DOWN': color, sym = R, '▼'
                else: color, sym = D, '─'

                print(format_scrolling_line(now_str, btc_price, up_buy, down_buy,
                                            session.current_signal, session.positions,
                                            current_regime, asset_name=config.display_name))

                # --- MEAN REVERSION ALERT (MID + RSI extreme + BB touch + token cheap) ---
                if current_phase == 'MID' and (now - session.last_beep) > 30:
                    rsi = binance_data.get('rsi', 50)
                    bb = binance_data.get('bb_pos', 0.5)
                    mr_direction = None
                    if rsi <= 15 and bb <= 0.10:
                        mr_direction = 'UP'     # oversold → expect reversal up
                    elif rsi >= 85 and bb >= 0.90:
                        mr_direction = 'DOWN'   # overbought → expect reversal down

                    if mr_direction:
                        token_price = up_buy if mr_direction == 'UP' else down_buy
                        if token_price < 0.70:
                            sys.stdout.write('\a\a\a')
                            sys.stdout.flush()
                            mr_color = G if mr_direction == 'UP' else R
                            print(f"   {mr_color}{B}{'═' * 55}{X}")
                            print(f"   {mr_color}{B}  MEAN REVERSION → {mr_direction} │ RSI={rsi:.0f} BB={bb:.2f} │ ${token_price:.2f}{X}")
                            print(f"   {W}  Token cheap + RSI extreme + Bollinger touch{X}")
                            print(f"   {W}  Press {mr_color}{B}{mr_direction[0]}{X}{W} to buy or wait...{X}")
                            print(f"   {mr_color}{B}{'═' * 55}{X}")
                            session.last_beep = now

                # --- PRICE TO BEAT ALERT (MID phase + token still cheap) ---
                elif current_phase == 'MID' and session.price_to_beat > 0 and PRICE_BEAT_ALERT > 0:
                    price_diff = btc_price - session.price_to_beat
                    token_price = up_buy if price_diff > 0 else down_buy
                    if abs(price_diff) >= PRICE_BEAT_ALERT and token_price < 0.70 and (now - session.last_beep) > 30:
                        beat_dir = 'UP' if price_diff > 0 else 'DOWN'
                        beat_color = G if beat_dir == 'UP' else R
                        print(f"   {beat_color}{B}  PRICE BEAT → {beat_dir} │ BTC ${abs(price_diff):.0f} from PTB │ ${token_price:.2f}{X}")
                        session.last_beep = now

                # --- POSITION MONITOR (TP/SL alert for open positions) ---
                if session.positions:
                    for pos in session.positions:
                        cur_price = up_buy if pos['direction'] == 'up' else down_buy
                        entry = pos['price']
                        pnl_pct = (cur_price - entry) / entry if entry > 0 else 0
                        tp_target = min(entry + 0.20, 0.55)
                        sl_target = max(entry - 0.15, 0.05)
                        d_color = G if pos['direction'] == 'up' else R
                        if cur_price >= tp_target and (now - session.last_beep) > 15:
                            sys.stdout.write('\a\a')
                            sys.stdout.flush()
                            print(f"   {G}{B}  TP HIT │ {pos['direction'].upper()} ${entry:.2f} → ${cur_price:.2f} (+{pnl_pct:+.0%}) │ Press C to close{X}")
                            session.last_beep = now
                        elif cur_price <= sl_target and (now - session.last_beep) > 15:
                            sys.stdout.write('\a')
                            sys.stdout.flush()
                            print(f"   {R}{B}  SL HIT │ {pos['direction'].upper()} ${entry:.2f} → ${cur_price:.2f} ({pnl_pct:+.0%}) │ Press C to close{X}")
                            session.last_beep = now

                # --- OPPORTUNITY DETECTED ---
                # Use phase-dependent threshold (CLOSING phase = 999, blocks all)
                effective_threshold = max(SIGNAL_STRENGTH_BEEP, phase_threshold)
                if SIGNAL_ENABLED and strength >= effective_threshold and s_dir != 'NEUTRAL' and sug:
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
                        info, session.balance, session.last_action = handle_buy(
                            client, trade_dir, trade_amount, session.token_up, session.token_down,
                            session.positions, session.balance, radar_logger,
                            session.session_pnl, get_price, _executor, reason="signal")
                        if info:
                            real_entry = info['price']
                            tp = min(real_entry + (sug['tp'] - sug['entry']), TP_MAX_PRICE)
                            sl = max(real_entry - (sug['entry'] - sug['sl']), SL_MIN_PRICE)
                            token_id = session.token_up if trade_dir == 'up' else session.token_down
                            tp_above = tp > real_entry
                            sl_above = sl < real_entry

                            print(f"   {M}{B}⏳ Monitoring TP ${tp:.2f} / SL ${sl:.2f}...{X}")
                            print()
                            reason, exit_price = monitor_tp_sl(
                                token_id, tp, sl, tp_above, sl_above,
                                get_price, _executor)

                            print()
                            if reason == 'TP':
                                exit_color = G
                            elif reason == 'CANCEL':
                                exit_color = Y
                            else:
                                exit_color = R
                            print(f"   {exit_color}{B}⚡ {reason} @ ${exit_price:.2f}! Closing...{X}")
                            close_msg = execute_close_market(
                                client, session.token_up, session.token_down,
                                get_price, _executor)
                            print(f"   {close_msg}")
                            pnl = (exit_price - real_entry) * info['shares']
                            session.session_pnl += pnl
                            session.trade_count += 1
                            session.trade_history.append(pnl)
                            radar_logger.log_trade("CLOSE", trade_dir, info['shares'], exit_price,
                                                   info['shares'] * exit_price, reason.lower(),
                                                   pnl, session.session_pnl)
                            pnl_color = G if pnl >= 0 else R
                            session.last_action = f"{exit_color}{B}{reason}{X} @ ${exit_price:.2f} │ {pnl_color}P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}{X}"
                            print(f"   {pnl_color}{B}P&L: {'+' if pnl >= 0 else ''}${pnl:.2f} │ Session: {'+' if session.session_pnl >= 0 else ''}${session.session_pnl:.2f} ({session.trade_count} trades){X}")
                            session.balance += exit_price * info['shares']
                            session.positions.clear()
                            print(f"   {D}Returning to radar...{X}")
                            print()
                        else:
                            session.last_action = f"{R}✗ BUY {trade_dir.upper()} FAILED{X}"

                        session.last_beep = time.time()
                    elif key in ('u', 'd'):
                        manual_dir = 'up' if key == 'u' else 'down'
                        info, session.balance, session.last_action = handle_buy(
                            client, manual_dir, trade_amount, session.token_up, session.token_down,
                            session.positions, session.balance, radar_logger,
                            session.session_pnl, get_price, _executor, reason="manual")
                        draw_panel(now_str, session.balance, btc_price, bin_direction, confidence,
                                   binance_data, session.market_slug, current_time, up_buy,
                                   down_buy, session.positions, session.current_signal, trade_amount,
                                   session.alert_active, session.alert_side, session.alert_price,
                                   session.session_pnl, session.trade_count,
                                   regime=current_regime, phase=current_phase,
                                   data_source=data_source, ws_status=binance_ws.status,
                                   price_to_beat=session.price_to_beat,
                                   trade_history=session.trade_history,
                                   last_action=session.last_action, asset_name=config.display_name,
                                   poly_latency_ms=session.poly_latency_ms)
                    else:
                        print(f"   {D}Ignored.{X}")
                        print()
                        session.last_beep = time.time()

                # Price alert
                session.update_alert(up_buy, down_buy)

                # --- CHECK HOTKEYS DURING SLEEP ---
                cycle_time = 0.5 if data_source == 'ws' else 2
                key = sleep_with_key(cycle_time)
                if key in ('u', 'd'):
                    buy_dir = 'up' if key == 'u' else 'down'
                    _, session.balance, session.last_action = handle_buy(
                        client, buy_dir, trade_amount, session.token_up, session.token_down,
                        session.positions, session.balance, radar_logger,
                        session.session_pnl, get_price, _executor, reason="manual")
                    draw_panel(now_str, session.balance, btc_price, bin_direction, confidence,
                               binance_data, session.market_slug, current_time, up_buy,
                               down_buy, session.positions, session.current_signal, trade_amount,
                               session.alert_active, session.alert_side, session.alert_price,
                               session.session_pnl, session.trade_count,
                               regime=current_regime, phase=current_phase,
                               data_source=data_source, ws_status=binance_ws.status,
                               price_to_beat=session.price_to_beat,
                               trade_history=session.trade_history,
                               last_action=session.last_action, asset_name=config.display_name,
                               poly_latency_ms=session.poly_latency_ms)
                elif key == 'c':
                    # Show closing status in static panel
                    session.set_status(f"{Y}{B}EMERGENCY CLOSE...{X}", duration=5)
                    session.last_action = f"{R}{B}EMERGENCY CLOSE{X}"
                    draw_panel(now_str, session.balance, btc_price, bin_direction, confidence,
                               binance_data, session.market_slug, current_time, up_buy,
                               down_buy, session.positions, session.current_signal, trade_amount,
                               session.alert_active, session.alert_side, session.alert_price,
                               session.session_pnl, session.trade_count,
                               regime=current_regime, phase=current_phase,
                               data_source=data_source, status_msg=session.status_msg,
                               ws_status=binance_ws.status,
                               price_to_beat=session.price_to_beat,
                               trade_history=session.trade_history,
                               last_action=session.last_action, asset_name=config.display_name,
                               poly_latency_ms=session.poly_latency_ms)
                    msg = execute_close_market(client, session.token_up, session.token_down,
                                              get_price, _executor)
                    if session.positions:
                        total_pnl, cnt, session.session_pnl, pnl_list = close_all_positions(
                            session.positions, session.token_up, session.token_down,
                            radar_logger, "emergency",
                            session.session_pnl, session.trade_history, get_price)
                        session.trade_count += cnt
                        for d, sh, ep, xp, pnl in pnl_list:
                            session.balance += xp * sh
                    # Show result in static panel
                    pnl_color = G if session.session_pnl >= 0 else R
                    session.set_status(
                        f"{G}✓ Closed{X} │ {pnl_color}{B}P&L: {'+' if session.session_pnl >= 0 else ''}${session.session_pnl:.2f}{X} {D}({session.trade_count} trades){X}",
                        duration=5)
                    session.last_action = f"{G}✓ CLOSED{X} │ {pnl_color}P&L: {'+' if session.session_pnl >= 0 else ''}${session.session_pnl:.2f}{X}"
                    draw_panel(now_str, session.balance, btc_price, bin_direction, confidence,
                               binance_data, session.market_slug, current_time, up_buy,
                               down_buy, session.positions, session.current_signal, trade_amount,
                               session.alert_active, session.alert_side, session.alert_price,
                               session.session_pnl, session.trade_count,
                               regime=current_regime, phase=current_phase,
                               data_source=data_source, status_msg=session.status_msg,
                               ws_status=binance_ws.status,
                               price_to_beat=session.price_to_beat,
                               trade_history=session.trade_history,
                               last_action=session.last_action, asset_name=config.display_name,
                               poly_latency_ms=session.poly_latency_ms)
                elif key == 'q':
                    raise KeyboardInterrupt

            except KeyboardInterrupt:
                # Reset scroll region, clear screen
                sys.stdout.write("\033[r")
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.flush()
                if session.positions:
                    print(f"{Y}Positions kept open (not closed on exit){X}")

                # Session summary
                duration_min = (time.time() - session_start) / 60
                stats = print_session_summary(duration_min, session.trade_count,
                                              session.session_pnl, session.trade_history)

                # Log session to CSV
                radar_logger.log_session_summary({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "start_time": session_start_str,
                    "end_time": datetime.now().strftime("%H:%M:%S"),
                    "duration_min": duration_min,
                    "total_trades": session.trade_count,
                    "wins": stats['wins'], "losses": stats['losses'],
                    "win_rate": stats['win_rate'],
                    "total_pnl": session.session_pnl,
                    "best_trade": stats['best'], "worst_trade": stats['worst'],
                    "profit_factor": stats['profit_factor'],
                    "max_drawdown": stats['max_drawdown'],
                })

                print(f"{Y}Radar terminated{X}")
                break
            except Exception as e:
                print(f"   {R}Error: {e}{X}")
                key = sleep_with_key(2)
                if key == 'q':
                    raise KeyboardInterrupt

    finally:
        # Stop WebSocket
        binance_ws.stop()
        # Shutdown thread pool (wait=True to prevent resource leaks)
        _executor.shutdown(wait=True)
        # Restore terminal
        sys.stdout.write("\033[r")  # reset scroll region
        sys.stdout.flush()
        if not IS_WINDOWS and old_settings:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        radar_logger.close()


if __name__ == "__main__":
    main()
