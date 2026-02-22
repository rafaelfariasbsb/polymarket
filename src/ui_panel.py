"""Terminal UI: static panel and scrolling log formatter."""

from __future__ import annotations

import os
import sys
import io
import shutil

from colors import G, R, Y, C, W, B, D, M, BL, X
from signal_engine import detect_scenario

PRICE_ALERT = float(os.getenv('PRICE_ALERT', '0.80'))
HEADER_LINES = 15


def draw_panel(time_str, balance, btc_price, bin_direction, confidence, binance_data,
               market_slug, time_remaining, up_buy, down_buy, positions, signal,
               trade_amount, alert_active=False, alert_side="", alert_price=0.0,
               session_pnl=0.0, trade_count=0, regime="", phase="",
               data_source="http", status_msg="", price_to_beat=0.0, ws_status="",
               trade_history=None, last_action="", asset_name="BTC",
               poly_latency_ms=0):
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
    buf.write(f"\033[4;1H\033[K {C}BINANCE {X}│ {asset_name}: {W}${btc_price:>8,.2f}{X} │ {bin_color}{B}{bin_direction}{X} (score:{score_bin:+.2f} conf:{confidence:.0f}%) │ RSI:{rsi_val:.0f} │ Vol:{vol_str} │ {reg_str} │ {src_str}")

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
    poly_lat_str = f" │ Poly:{Y}{poly_latency_ms:.0f}ms{X}" if poly_latency_ms > 0 else ""
    buf.write(f"\033[5;1H\033[K {Y}MARKET  {X}│ {market_slug} │ Closes in: {time_color}{time_remaining:.1f}min{X} │ {phase_str}{ptb_str}{poly_lat_str}")

    # Line 6: Polymarket
    buf.write(f"\033[6;1H\033[K {G}POLY    {X}│ {asset_name}: {W}${btc_price:>8,.2f}{X} │ UP: {G}${up_buy:.2f}{X}/{G}${1.0 - down_buy:.2f}{X} ({G}{up_buy * 100:.0f}%{X}) │ DOWN: {R}${down_buy:.2f}{X}/{R}${1.0 - up_buy:.2f}{X} ({R}{down_buy * 100:.0f}%{X})")

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

    # Line 10: Alert / Scenario
    scenario = detect_scenario(signal, regime, phase)
    buf.write(f"\033[10;1H\033[K")
    if status_msg:
        buf.write(f" {Y}{B}STATUS  {X}│ {status_msg}")
    elif alert_active:
        alert_color = G if alert_side == "UP" else R
        scenario_str = ""
        if scenario:
            sc_name, sc_color, sc_warn = scenario
            scenario_str = f" │ {sc_color}{BL}{B}{sc_name}{X}"
        buf.write(f" {Y}{B}ALERT   {X}│ {alert_color}{B}{alert_side} @ ${alert_price:.2f}{X} (>= ${PRICE_ALERT:.2f}){scenario_str}")
    elif scenario:
        sc_name, sc_color, sc_warn = scenario
        if sc_warn:
            buf.write(f" {Y}ALERT   {X}│ {sc_color}{BL}{B}⚠ {sc_name}{X}")
        else:
            buf.write(f" {G}ALERT   {X}│ {sc_color}{BL}{B}● {sc_name}{X}")
    else:
        buf.write(f" {D}ALERT   {X}│ {D}─{X}")

    # Line 11: separator
    buf.write(f"\033[11;1H\033[K {'─' * (w - 2)}")

    # Line 12: Hotkeys
    buf.write(f"\033[12;1H\033[K {W}{B}U{X}{D}=buy UP{X} │ {W}{B}D{X}{D}=buy DOWN{X} │ {W}{B}C{X}{D}=close all{X} │ {W}{B}S{X}{D}=accept signal{X} │ {W}{B}Q{X}{D}=exit{X}")

    # Line 13: bottom separator
    buf.write(f"\033[13;1H\033[K {C}{B}{'═' * (w - 2)}{X}")

    # Line 14: column headers
    buf.write(f"\033[14;1H\033[K   {D}{'UP':>8s} {'DN':>8s} │ {'RSI':>7s} │ {'STRENGTH':>15s} │ {'VOL':4s} │ {'TREND':>7s} │ {'MACD':>6s} │ {'VWAP':>6s} │ {'BB':>6s} │ {'S/R':>13s} │ {'REGIME':6s}{X}")

    # Line 15: blank
    buf.write(f"\033[15;1H\033[K")

    buf.write("\033[u")  # restore cursor

    # Single write + flush
    sys.stdout.write(buf.getvalue())
    sys.stdout.flush()


def format_scrolling_line(now_str, btc_price, up_buy, down_buy, signal, positions, regime, asset_name="BTC"):
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

    col_up     = f"UP:{G}${up_buy:.2f}{X}"
    col_dn     = f"DN:{R}${down_buy:.2f}{X}"
    rsi_c = G if rsi_val < 40 else R if rsi_val > 60 else D
    col_rsi    = f"{rsi_c}RSI:{rsi_val:>3.0f}{rsi_arrow}{X}"
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

    return f"   {col_up} {col_dn} │ {col_rsi} │ {col_signal} │ {col_vol} │ {col_trend} │ {col_macd} │ {col_vwap} │ {col_bb} │ {col_sr} │ {col_regime}{pos_str}"
