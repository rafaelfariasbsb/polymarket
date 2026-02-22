#!/usr/bin/env python3
"""
Logging module for Polymarket Scalp Radar.
Writes signal snapshots, trade events, and session summaries to CSV files.
"""

import csv
import os
import time
from datetime import datetime

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")

SIGNAL_COLUMNS = [
    "timestamp", "btc_price", "up_buy", "down_buy",
    "rsi", "atr", "trend_strength",
    "signal_direction", "signal_strength", "score",
    "sr_raw", "sr_adj", "vol_pct", "high_vol",
    "macd_hist", "vwap_pos", "bb_pos",
    "regime", "phase",
]

TRADE_COLUMNS = [
    "timestamp", "action", "direction", "shares", "price",
    "amount_usd", "reason", "pnl", "session_pnl",
]

SESSION_COLUMNS = [
    "date", "start_time", "end_time", "duration_min",
    "total_trades", "wins", "losses",
    "win_rate", "total_pnl",
    "best_trade", "worst_trade",
    "profit_factor", "max_drawdown",
]


class RadarLogger:
    """Handles CSV logging for signals, trades, and sessions."""

    def __init__(self):
        os.makedirs(LOGS_DIR, exist_ok=True)
        self._signal_writer = None
        self._signal_file = None
        self._trade_writer = None
        self._trade_file = None
        self._signal_count = 0
        self._current_date = None

    def _ensure_files(self):
        """Open or rotate CSV files based on current date."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today == self._current_date:
            return

        self._close_files()
        self._current_date = today

        # Signal log
        sig_path = os.path.join(LOGS_DIR, f"signals_{today}.csv")
        sig_exists = os.path.exists(sig_path) and os.path.getsize(sig_path) > 0
        self._signal_file = open(sig_path, "a", newline="")
        self._signal_writer = csv.writer(self._signal_file)
        if not sig_exists:
            self._signal_writer.writerow(SIGNAL_COLUMNS)

        # Trade log
        trade_path = os.path.join(LOGS_DIR, f"trades_{today}.csv")
        trade_exists = os.path.exists(trade_path) and os.path.getsize(trade_path) > 0
        self._trade_file = open(trade_path, "a", newline="")
        self._trade_writer = csv.writer(self._trade_file)
        if not trade_exists:
            self._trade_writer.writerow(TRADE_COLUMNS)

        self._signal_count = 0

    def _close_files(self):
        for f in (self._signal_file, self._trade_file):
            if f:
                try:
                    f.close()
                except Exception:
                    pass
        self._signal_file = None
        self._trade_file = None
        self._signal_writer = None
        self._trade_writer = None

    def log_signal(self, btc_price, up_buy, down_buy, signal, binance_data,
                   regime="", phase=""):
        """Log one signal snapshot (called every radar cycle ~2s)."""
        try:
            self._ensure_files()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            rsi = binance_data.get("rsi", 0)
            atr = binance_data.get("atr", 0)

            if signal:
                row = [
                    now, f"{btc_price:.2f}", f"{up_buy:.4f}", f"{down_buy:.4f}",
                    f"{rsi:.1f}", f"{atr:.2f}", f"{signal.get('trend', 0):.3f}",
                    signal.get("direction", ""), signal.get("strength", 0),
                    f"{signal.get('score', 0):.4f}",
                    f"{signal.get('sr_raw', 0):.3f}", f"{signal.get('sr_adj', 0):.3f}",
                    f"{signal.get('vol_pct', 0):.4f}", signal.get("high_vol", False),
                    f"{signal.get('macd_hist', 0):.4f}",
                    f"{signal.get('vwap_pos', 0):.4f}",
                    f"{signal.get('bb_pos', 0):.4f}",
                    regime, phase,
                ]
            else:
                row = [now, f"{btc_price:.2f}", f"{up_buy:.4f}", f"{down_buy:.4f}",
                       f"{rsi:.1f}", f"{atr:.2f}", "", "", "", "", "", "", "", "",
                       "", "", "", regime, phase]

            self._signal_writer.writerow(row)
            self._signal_count += 1

            # Flush every 10 rows for performance
            if self._signal_count % 10 == 0:
                self._signal_file.flush()
        except Exception:
            pass

    def log_trade(self, action, direction, shares, price, amount_usd,
                  reason, pnl=0.0, session_pnl=0.0):
        """Log a trade event (BUY, SELL, CLOSE)."""
        try:
            self._ensure_files()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [
                now, action, direction, f"{shares:.2f}", f"{price:.4f}",
                f"{amount_usd:.2f}", reason, f"{pnl:.2f}", f"{session_pnl:.2f}",
            ]
            self._trade_writer.writerow(row)
            self._trade_file.flush()
        except Exception:
            pass

    def log_session_summary(self, stats):
        """Append session summary to sessions.csv."""
        try:
            path = os.path.join(LOGS_DIR, "sessions.csv")
            exists = os.path.exists(path) and os.path.getsize(path) > 0
            with open(path, "a", newline="") as f:
                writer = csv.writer(f)
                if not exists:
                    writer.writerow(SESSION_COLUMNS)
                writer.writerow([
                    stats.get("date", ""),
                    stats.get("start_time", ""),
                    stats.get("end_time", ""),
                    f"{stats.get('duration_min', 0):.1f}",
                    stats.get("total_trades", 0),
                    stats.get("wins", 0),
                    stats.get("losses", 0),
                    f"{stats.get('win_rate', 0):.1f}",
                    f"{stats.get('total_pnl', 0):.2f}",
                    f"{stats.get('best_trade', 0):.2f}",
                    f"{stats.get('worst_trade', 0):.2f}",
                    f"{stats.get('profit_factor', 0):.2f}",
                    f"{stats.get('max_drawdown', 0):.2f}",
                ])
        except Exception:
            pass

    def close(self):
        """Close all open files."""
        self._close_files()
