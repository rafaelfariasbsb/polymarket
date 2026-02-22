#!/usr/bin/env python3
"""
Binance WebSocket client for real-time BTC/USDT kline data.
Maintains a candle buffer in memory with auto-reconnect.
Falls back to HTTP polling if WebSocket is unavailable.
"""
from __future__ import annotations

import json
import logging
import threading
import time

try:
    import websocket
    HAS_WS = True
except ImportError:
    HAS_WS = False

from binance_api import get_klines

logger = logging.getLogger(__name__)

MAX_CANDLES = 30
RECONNECT_DELAY_BASE = 2
RECONNECT_DELAY_MAX = 30


def _build_ws_endpoints(symbol="btcusdt", interval="1m"):
    """Build WebSocket endpoint URLs for a given symbol."""
    return [
        f"wss://stream.binance.com:9443/ws/{symbol}@kline_{interval}",
        f"wss://stream.binance.com:443/ws/{symbol}@kline_{interval}",
    ]


class BinanceWS:
    """Real-time Binance kline WebSocket with auto-reconnect and HTTP fallback."""

    def __init__(self, symbol="btcusdt", interval="1m"):
        self._symbol = symbol.lower()
        self._interval = interval
        self._binance_symbol = symbol.upper()  # e.g. BTCUSDT for HTTP fallback
        self._ws_endpoints = _build_ws_endpoints(self._symbol, self._interval)
        self._candles = []        # completed candles buffer
        self._current = None      # candle still forming (live)
        self._lock = threading.Lock()
        self._ws = None
        self._thread = None
        self._running = False
        self._connected = False
        self._reconnect_count = 0
        self._last_update = 0
        self._endpoint_idx = 0
        self._last_error = ""
        self._msg_count = 0
        self._connect_count = 0

    @property
    def is_connected(self):
        return self._connected

    @property
    def last_update(self):
        return self._last_update

    @property
    def status(self):
        """Diagnostic status string."""
        if not self._running:
            return "OFF:no-ws" if not HAS_WS else "OFF:stopped"
        if self._connected:
            return f"WS (msgs:{self._msg_count})"
        # Thread died unexpectedly — restart it
        with self._lock:
            if self._thread and not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run_loop, daemon=True)
                self._thread.start()
                return "RESTART"
        if self._last_error:
            return f"ERR: {self._last_error[:50]}"
        if self._connect_count > 0:
            return f"RECONN #{self._connect_count}"
        return "CONNECTING"

    def start(self) -> bool:
        """Start WebSocket connection in background thread."""
        if not HAS_WS:
            return False

        if self._running:
            return True

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop WebSocket connection."""
        self._running = False
        self._connected = False
        if self._ws:
            try:
                self._ws.close()
            except Exception as e:
                logger.debug("WS close error: %s", e)

    def get_candles(self, limit: int = 20) -> tuple[list[dict], str]:
        """Get candles from WS buffer. Falls back to HTTP if WS has no data.

        Returns:
            candles: list of candle dicts
            source: 'ws' or 'http'
        """
        with self._lock:
            # Include completed candles + current forming candle
            all_candles = list(self._candles)
            if self._current:
                all_candles.append(self._current)

        # Use WS data if connected and we have enough candles
        if self._connected and len(all_candles) >= 5 and (time.time() - self._last_update) < 10:
            return all_candles[-limit:], 'ws'

        # Fallback to HTTP
        try:
            candles = get_klines(symbol=self._binance_symbol, interval="1m", limit=limit)
            # Always refresh buffer with HTTP data (keeps buffer fresh for WS recovery)
            with self._lock:
                self._candles = candles[:-1]  # all except last (still forming)
                if candles:
                    self._current = candles[-1]
                self._last_update = time.time()
            return candles, 'http'
        except Exception as e:
            logger.debug("WS HTTP fallback error: %s", e)
            # Return whatever we have
            if all_candles:
                return all_candles[-limit:], 'ws'
            return [], 'http'

    def _run_loop(self):
        """Main reconnection loop."""
        # Seed initial data via HTTP
        try:
            candles = get_klines(symbol=self._binance_symbol, interval="1m", limit=MAX_CANDLES)
            if candles:
                with self._lock:
                    self._candles = candles[:-1]
                    self._current = candles[-1]
                    self._last_update = time.time()
        except Exception as e:
            logger.debug("WS initial seed error: %s", e)

        while self._running:
            url = self._ws_endpoints[self._endpoint_idx % len(self._ws_endpoints)]
            try:
                self._connect(url)
            except Exception as e:
                self._last_error = str(e)[:100]
                logger.debug("WS connect error: %s", e)

            if not self._running:
                break

            # Reconnect with exponential backoff
            delay = min(RECONNECT_DELAY_BASE * (2 ** self._reconnect_count),
                        RECONNECT_DELAY_MAX)
            self._reconnect_count += 1
            self._endpoint_idx += 1
            self._connected = False

            for _ in range(int(delay * 10)):
                if not self._running:
                    return
                time.sleep(0.1)

    def _connect(self, url):
        """Establish WebSocket connection."""
        self._ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error,
        )
        self._ws.run_forever(ping_interval=30, ping_timeout=10)

    def _on_open(self, ws):
        self._connected = True
        self._reconnect_count = 0
        self._connect_count += 1
        self._last_error = ""

    def _on_close(self, ws, close_status_code, close_msg):
        self._connected = False
        if close_status_code:
            self._last_error = f"closed:{close_status_code}"

    def _on_error(self, ws, error):
        self._connected = False
        self._last_error = str(error)[:100]

    def _on_message(self, ws, message):
        """Process incoming kline message."""
        try:
            data = json.loads(message)
            k = data.get("k")
            if not k:
                return

            candle = {
                "timestamp": k["t"],
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
            }

            is_closed = k.get("x", False)

            with self._lock:
                if is_closed:
                    # Candle is complete — add to buffer
                    self._candles.append(candle)
                    # Trim buffer
                    if len(self._candles) > MAX_CANDLES:
                        self._candles = self._candles[-MAX_CANDLES:]
                    self._current = None
                else:
                    # Candle still forming — update live candle
                    self._current = candle

                self._last_update = time.time()
                self._msg_count += 1

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.debug("WS message parse error: %s", e)
