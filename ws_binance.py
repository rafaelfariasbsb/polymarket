#!/usr/bin/env python3
"""
Binance WebSocket client for real-time BTC/USDT kline data.
Maintains a candle buffer in memory with auto-reconnect.
Falls back to HTTP polling if WebSocket is unavailable.
"""

import json
import threading
import time

try:
    import websocket
    HAS_WS = True
except ImportError:
    HAS_WS = False

from binance_api import get_klines


# Binance WebSocket endpoints (try in order)
WS_ENDPOINTS = [
    "wss://stream.binance.com:9443/ws/btcusdt@kline_1m",
    "wss://stream.binance.com:443/ws/btcusdt@kline_1m",
]

MAX_CANDLES = 30
RECONNECT_DELAY_BASE = 2
RECONNECT_DELAY_MAX = 30


class BinanceWS:
    """Real-time Binance kline WebSocket with auto-reconnect and HTTP fallback."""

    def __init__(self):
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

    @property
    def is_connected(self):
        return self._connected

    @property
    def last_update(self):
        return self._last_update

    def start(self):
        """Start WebSocket connection in background thread."""
        if not HAS_WS:
            return False

        if self._running:
            return True

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Stop WebSocket connection."""
        self._running = False
        self._connected = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def get_candles(self, limit=20):
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

        # Use WS data if we have enough candles and data is fresh (< 10s old)
        if len(all_candles) >= 5 and (time.time() - self._last_update) < 10:
            return all_candles[-limit:], 'ws'

        # Fallback to HTTP
        try:
            candles = get_klines(interval="1m", limit=limit)
            # Seed the buffer with HTTP data if empty
            if not self._candles:
                with self._lock:
                    self._candles = candles[:-1]  # all except last (still forming)
                    if candles:
                        self._current = candles[-1]
            return candles, 'http'
        except Exception:
            # Return whatever we have
            if all_candles:
                return all_candles[-limit:], 'ws'
            return [], 'http'

    def _run_loop(self):
        """Main reconnection loop."""
        # Seed initial data via HTTP
        try:
            candles = get_klines(interval="1m", limit=MAX_CANDLES)
            if candles:
                with self._lock:
                    self._candles = candles[:-1]
                    self._current = candles[-1]
                    self._last_update = time.time()
        except Exception:
            pass

        while self._running:
            url = WS_ENDPOINTS[self._endpoint_idx % len(WS_ENDPOINTS)]
            try:
                self._connect(url)
            except Exception:
                pass

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

    def _on_close(self, ws, close_status_code, close_msg):
        self._connected = False

    def _on_error(self, ws, error):
        self._connected = False

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

        except Exception:
            pass
