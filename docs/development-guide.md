# Development Guide

Technical reference for the Polymarket Crypto Scalping Radar codebase. Covers architecture, module internals, data flow, concurrency model, and extension points.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Module Reference](#2-module-reference)
   - [src/market_config.py](#21-srcmarket_configpy)
   - [src/binance_api.py](#22-srcbinance_apipy)
   - [src/ws_binance.py](#23-srcws_binancepy)
   - [src/polymarket_api.py](#24-srcpolymarket_apipy)
   - [src/logger.py](#25-srcloggerpy)
   - [src/colors.py](#26-srccolorspy)
   - [src/input_handler.py](#27-srcinput_handlerpy)
   - [src/signal_engine.py](#28-srcsignal_enginepy)
   - [src/session_stats.py](#29-srcsession_statspy)
   - [src/ui_panel.py](#210-srcui_panelpy)
   - [src/trade_executor.py](#211-srctrade_executorpy)
   - [radar_poly.py](#212-radar_polypy)
3. [Data Flow](#3-data-flow)
4. [Signal Engine Internals](#4-signal-engine-internals)
5. [Concurrency Model](#5-concurrency-model)
6. [Terminal UI Architecture](#6-terminal-ui-architecture)
7. [Order Execution Pipeline](#7-order-execution-pipeline)
8. [Configuration System](#8-configuration-system)
9. [Setup Scripts](#9-setup-scripts)
10. [Dependencies](#10-dependencies)
11. [Key Algorithms](#11-key-algorithms)
12. [Extension Points](#12-extension-points)

---

## 1. Architecture Overview

```
                    ┌─────────────────────┐
                    │ src/market_config.py │
                    │  (asset, window,     │
                    │   slug, symbols)     │
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────────┐
         │                     │                         │
┌────────▼────────┐  ┌────────▼─────────┐    ┌─────────▼─────────┐
│ src/binance_api  │  │src/polymarket_api │    │   src/logger.py   │
│  (indicators,    │  │ (auth, orders,    │    │  (CSV logging)    │
│   regime, trend) │  │  market discovery)│    │                   │
└────────┬────────┘  └────────┬─────────┘    └─────────┬─────────┘
         │                    │                         │
┌────────▼────────┐           │                         │
│src/ws_binance.py │           │                         │
│  (WebSocket,     │           │                         │
│   candle buffer) │           │                         │
└────────┬────────┘           │                         │
         │                    │                         │
         └──────────┬─────────┘                         │
                    │                                   │
           ┌────────▼────────┐                          │
           │  radar_poly.py   │◄─────────────────────────┘
           │  (TradingSession,│
           │   main loop,     │
           │   orchestration) │
           └───────┬──────────┘
                   │ imports
     ┌─────────────┼──────────────┬──────────────┐
     │             │              │              │
┌────▼─────┐ ┌────▼──────┐ ┌────▼──────┐ ┌────▼──────────┐
│src/signal │ │src/ui_panel│ │src/trade_ │ │src/input_     │
│_engine.py │ │.py         │ │executor.py│ │handler.py     │
│(compute,  │ │(draw_panel,│ │(buy, sell,│ │(read_key_nb,  │
│ phase,    │ │ scrolling  │ │ close,    │ │ wait_for_key, │
│ scenario) │ │ log)       │ │ TP/SL)    │ │ sleep_w_key)  │
└─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └──────────────┘
      │             │              │
      └──────┬──────┘              │
             │                     │
      ┌──────▼──────┐      ┌──────▼──────┐
      │src/colors.py │      │src/session_ │
      │(ANSI codes)  │      │stats.py     │
      └──────────────┘      └─────────────┘
```

The system follows a **modular pipeline architecture**:

1. **Data Collection** — Binance (WS/HTTP) + Polymarket (HTTP) prices fetched in parallel
2. **Analysis** — 6 weighted indicators computed from candle data (`src/binance_api.py`)
3. **Signal Generation** — Weighted score → regime adjustment → phase filtering → direction + strength (`src/signal_engine.py`)
4. **Presentation** — Split-screen terminal UI with static panel + scrolling log (`src/ui_panel.py`)
5. **Execution** — Hotkey-driven order submission via CLOB API (`src/trade_executor.py`)
6. **Logging** — Every cycle snapshot + trade events + session summaries to CSV (`src/logger.py`)

### Import Dependency Chain

```
src/colors.py (leaf — no imports)
    ↑
src/input_handler.py ← src/signal_engine.py ← src/session_stats.py
    ↑                         ↑                       ↑
src/ui_panel.py          src/trade_executor.py         │
    ↑                         ↑                       │
    └───────────── radar_poly.py ◄────────────────────┘
```

No circular imports — the chain flows strictly upward.

---

## 2. Module Reference

### 2.1 src/market_config.py

**Purpose:** Centralized market configuration. Single source of truth for asset/window-dependent values.

**Class: `MarketConfig`**

```python
MarketConfig(asset=None, window_min=None)
```

| Property | Type | Example | Description |
|---|---|---|---|
| `asset` | `str` | `"btc"` | Lowercase asset ticker. Read from `MARKET_ASSET` env var |
| `window_min` | `int` | `15` | Window duration in minutes. Read from `MARKET_WINDOW` env var |
| `slug_prefix` | `str` | `"btc-updown-15m"` | Polymarket event slug prefix (property) |
| `binance_symbol` | `str` | `"BTCUSDT"` | Uppercase Binance trading pair (property) |
| `ws_symbol` | `str` | `"btcusdt"` | Lowercase symbol for WebSocket stream (property) |
| `window_seconds` | `int` | `900` | Window duration in seconds (property) |
| `display_name` | `str` | `"BTC"` | Uppercase asset name for UI (property) |

**Validation:** Raises `ValueError` if asset not in `{btc, eth, sol, xrp}` or window not in `{5, 15}`.

**Design decisions:**
- All derived values are `@property` — computed lazily, no stale state
- Constructor accepts overrides for testing (`MarketConfig(asset="eth", window_min=5)`)
- Calls `load_dotenv()` at module level, so env vars are available at import time

---

### 2.2 src/binance_api.py

**Purpose:** Binance public API wrapper. Computes all technical indicators from candle data. No authentication required.

**Module-level state:**
- `_session = requests.Session()` — persistent HTTP connection pool (TCP keep-alive)
- `RSI_PERIOD`, `MACD_FAST`, `MACD_SLOW`, `MACD_SIGNAL`, `BB_PERIOD`, `BB_STD`, `ADX_PERIOD` — configurable via `.env`

#### Functions

**`get_btc_price(symbol="BTCUSDT") -> float`**
- Endpoint: `GET /api/v3/ticker/price`
- Returns current spot price
- Timeout: 10s

**`get_price_at_timestamp(timestamp_sec, symbol="BTCUSDT") -> float`**
- Endpoint: `GET /api/v3/klines` with `startTime` and `limit=1`
- Returns the open price of the 1m candle at the given Unix timestamp
- Used to compute "Price to Beat" (the price at the start of a Polymarket window)
- Returns `0.0` on error

**`get_klines(symbol, interval="1m", limit=15) -> list[dict]`**
- Endpoint: `GET /api/v3/klines`
- Returns candle dicts with keys: `timestamp`, `open`, `high`, `low`, `close`, `volume`
- Binance returns arrays of arrays; this function normalizes to named dicts

**`compute_rsi(candles, period=RSI_PERIOD) -> float`**
- Standard RSI formula: `100 - (100 / (1 + RS))`
- RS = average gain / average loss over `period` candles
- Returns `50.0` (neutral) when insufficient data or when gains and losses are both zero
- Returns `100.0` when there are no losses (pure uptrend)
- Uses SMA smoothing (not Wilder's for RSI — keeps it simpler for short periods)

**`compute_atr(candles) -> float`**
- True Range = max(high-low, |high-prev_close|, |low-prev_close|)
- Returns simple average of all TRs (not exponentially smoothed)

**`compute_adx(candles, period=ADX_PERIOD) -> float`**
- Full Wilder's ADX implementation:
  1. Compute +DM and -DM for each candle
  2. Apply mutual exclusion rule (only the larger DM survives)
  3. Smooth with Wilder's method: `smoothed = (prev * (period-1) + current) / period`
  4. Compute +DI and -DI: `(smoothed_DM / smoothed_TR) * 100`
  5. DX = `|+DI - -DI| / (+DI + -DI) * 100`
  6. ADX = SMA of last `period` DX values
- Returns `25.0` (neutral) when insufficient data

**`compute_macd(candles, fast, slow, signal_period) -> (macd_line, signal_line, histogram, hist_delta)`**
- Uses `_ema_list()` helper for EMA computation over full series
- MACD line = fast EMA - slow EMA
- Signal line = EMA of MACD values (starting from index `slow-1`)
- Histogram = MACD - Signal
- Histogram delta = current histogram - previous histogram (acceleration metric)
- Default periods (5/10/4) are tuned for 1m scalping (much faster than traditional 12/26/9)

**`compute_vwap(candles) -> (vwap, price_vs_vwap, vwap_slope)`**
- Cumulative VWAP: `sum(typical_price * volume) / sum(volume)`
- Typical price = `(high + low + close) / 3`
- `price_vs_vwap`: percentage deviation of current close from VWAP
- `vwap_slope`: computed from last 5 VWAP values, normalized to `[-1.0, +1.0]`
- Normalization factor: `slope * 50`, clamped

**`compute_bollinger(candles, period, num_std) -> (upper, middle, lower, bandwidth, position, squeeze)`**
- Middle = SMA of closes over `period`
- Std dev = population standard deviation (divides by N, not N-1)
- Upper/Lower = middle +/- `num_std` * std_dev
- Position = `(close - lower) / (upper - lower)`, clamped to `[0, 1]`
- Squeeze detection: if current bandwidth < 50% of previous period's bandwidth → `squeeze = True`
- Requires `period * 2` candles for squeeze detection

**`detect_regime(candles) -> (regime, adx)`**
- Combines ADX + Bollinger bandwidth + SMA direction + candle consistency
- Decision tree:
  - ADX >= 25 → trending: above SMA + >=4/7 greens = `TREND_UP`, below SMA + <=3/7 greens = `TREND_DOWN`, else `RANGE`
  - ADX < 18 → weak: wide Bollinger = `CHOP`, narrow = `RANGE`
  - ADX 18-25 → `RANGE`

**`get_full_analysis(candles=None, symbol="BTCUSDT") -> (direction, confidence, details)`**
- Orchestrator function that calls all indicator functions
- Accepts pre-fetched candles (from WebSocket) or fetches via HTTP
- `details` dict contains all indicator values keyed by standard names
- Calls `analyze_trend()` for base direction/confidence, then enriches with all indicators

**`analyze_trend(candles) -> (direction, confidence, details)`**
- Score-based candle pattern analysis (-1 to +1)
- Components: total price change (35%), momentum (35%), green/red ratio (15%), volume ratio (15%)
- Score > 0.10 → "up", score < -0.10 → "down", else "neutral"

**Helper: `_ema_list(values, period) -> list[float]`**
- Returns full EMA series (same length as input)
- Multiplier: `k = 2 / (period + 1)`
- First value initialized to `values[0]` (no SMA seeding)

---

### 2.3 src/ws_binance.py

**Purpose:** Real-time Binance kline data via WebSocket with auto-reconnect. Falls back to HTTP polling when unavailable.

**Module-level state:**
- `HAS_WS: bool` — `True` if `websocket-client` is installed
- `MAX_CANDLES = 30` — completed candles buffer size
- `RECONNECT_DELAY_BASE = 2`, `RECONNECT_DELAY_MAX = 30` — exponential backoff bounds

**Class: `BinanceWS`**

```python
BinanceWS(symbol="btcusdt", interval="1m")
```

**Internal state:**
| Field | Type | Description |
|---|---|---|
| `_candles` | `list[dict]` | Completed candles buffer (max 30) |
| `_current` | `dict \| None` | Currently forming candle (live) |
| `_lock` | `threading.Lock` | Thread safety for candle access |
| `_ws` | `WebSocketApp` | Active WebSocket connection |
| `_thread` | `Thread` | Background reconnection loop |
| `_running` | `bool` | Master switch for the loop |
| `_connected` | `bool` | Current connection status |
| `_reconnect_count` | `int` | Current backoff exponent |
| `_endpoint_idx` | `int` | Round-robin endpoint selector |
| `_msg_count` | `int` | Total messages received (diagnostics) |
| `_connect_count` | `int` | Total connections established |

**Connection strategy:**
1. Two endpoints alternate on reconnect:
   - `wss://stream.binance.com:9443/ws/{symbol}@kline_1m`
   - `wss://stream.binance.com:443/ws/{symbol}@kline_1m`
2. Exponential backoff: `delay = min(2 * 2^count, 30)` seconds
3. Backoff resets to 0 on successful connection
4. Thread loop sleeps in 0.1s increments (allows clean shutdown)

**`start() -> bool`**
- Returns `False` if `websocket-client` not installed
- Seeds initial candle buffer via HTTP (`get_klines(limit=30)`)
- Starts daemon thread with `_run_loop()`

**`stop() -> None`**
- Sets `_running = False`, calls `ws.close()`

**`get_candles(limit=20) -> (candles, source)`**
- Returns `('ws', candles)` if: connected AND >= 5 candles AND last update < 10s ago
- Otherwise falls back to HTTP: calls `get_klines()` and refreshes internal buffer
- Always returns completed candles + current forming candle

**`_on_message(ws, message)`**
- Parses Binance kline JSON: `data["k"]` contains candle fields
- Checks `k["x"]` (is_closed flag):
  - `True` → appends to `_candles`, trims to `MAX_CANDLES`, clears `_current`
  - `False` → updates `_current` (live candle)
- All buffer operations are under `_lock`

**`status` property**
- Diagnostic string for the UI panel
- Detects dead threads and auto-restarts them
- Shows message count, error info, or reconnection state

---

### 2.4 src/polymarket_api.py

**Purpose:** Polymarket CLOB API authentication, market discovery, position tracking, and order management.

**Module-level state:**
- `GAMMA = "https://gamma-api.polymarket.com"` — event metadata API
- `CLOB = "https://clob.polymarket.com"` — order book API
- `_session = requests.Session()` — persistent HTTP connections
- `PROXY_FACTORY`, `PROXY_INIT_CODE_HASH` — Polymarket proxy wallet constants (Polygon chain)
- `UTC`, `ET`, `BRASILIA` — timezone offsets

#### Authentication Flow

```
Private Key (0x...)
    │
    ├─► Account.from_key(key) → EOA address
    │
    ├─► derive_proxy_address(eoa) → Proxy wallet (CREATE2)
    │      │
    │      └─► keccak256(0xff + factory + salt + init_code_hash)[12:]
    │
    └─► ClobClient(key, chain_id=POLYGON, signature_type=1, funder=proxy)
           │
           └─► create_or_derive_api_creds() → API credentials (Level 2)
```

**`derive_proxy_address(eoa_address) -> str`**
- CREATE2 address derivation (EIP-1014)
- Salt = `keccak256(eoa_bytes)`
- Returns checksummed proxy address

**`create_client() -> (client, limit)`**
- Full auth pipeline: load key → derive EOA → derive proxy → create ClobClient → derive API creds
- `signature_type=1` = POLY_PROXY (exported wallet)
- `funder=proxy_address` tells the client where funds live

**`find_current_market(config) -> (event, market, token_up, token_down, time_remaining)`**
- Market discovery algorithm:
  1. Get current time in ET (Eastern Time, market reference)
  2. Round down to nearest window boundary (e.g., minute 37 in 15m window → minute 30)
  3. Convert to UTC timestamp, round to nearest `window_seconds`
  4. Try 4 candidate timestamps: `[rounded, raw, rounded-window, rounded+window]`
  5. For each, construct slug (`{prefix}-{timestamp}`) and query Gamma API
  6. Accept if event start time is within 120s of expected window start
  7. **Exponential backoff** on API errors: `sleep(min(0.2 * 2^attempt, 2.0))`
- Extracts `token_up` and `token_down` from `clobTokenIds` (matched via `outcomes` array)
- Returns time remaining in minutes

**`get_balance(client) -> float`**
- Queries `COLLATERAL` balance allowance
- Raw value is in 1e6 units (USDC has 6 decimals on Polygon) → divides by 1e6
- Deducts value locked in open BUY orders: `remaining_size * price`

**`get_token_position(client, token_id) -> float`**
- Queries `CONDITIONAL` balance allowance
- Returns share count (also divided by 1e6)

**`monitor_order(client, order_id, interval, timeout_sec, cancel_fn, quiet) -> (status, details)`**
- Polling loop: checks order status every `interval` seconds
- Handles API race condition: if status is `MATCHED` but `size_matched == 0`, waits 2s and re-queries
- Terminal statuses: `FILLED` (MATCHED), `CANCELLED`, `TIMEOUT`
- Displays progress bar when `quiet=False`

**`coerce_list(maybe_list)`**
- Safely handles Polymarket API returning either a JSON list or a JSON string containing a list
- Returns `[]` on any parse failure

---

### 2.5 src/logger.py

**Purpose:** CSV logging with daily rotation and buffered writes.

**Class: `RadarLogger`**

**File structure:**
```
logs/
├── signals_2025-01-15.csv    # every radar cycle (~0.5-2s)
├── signals_2025-01-16.csv    # auto-rotated daily
├── trades_2025-01-15.csv     # trade events (BUY, CLOSE)
├── sessions.csv              # session summaries (appended)
```

**`_ensure_files()`**
- Checks if date has changed → closes old files, opens new ones
- Creates files with headers if they don't exist (checks file size > 0 to avoid duplicate headers on empty files)
- Uses `open(..., "a")` append mode

**`log_signal(btc_price, up_buy, down_buy, signal, binance_data, regime, phase)`**
- Writes 19-column row every radar cycle
- Flushes to disk every 10 rows (performance trade-off)

**`log_trade(action, direction, shares, price, amount_usd, reason, pnl, session_pnl)`**
- Writes 9-column row on every trade event
- Flushes immediately (trades are critical data)

**`log_session_summary(stats)`**
- Appends 13-column row to `sessions.csv`
- Opens/closes file each time (called once at exit)

---

### 2.6 src/colors.py

**Purpose:** Shared ANSI color constants used by all modules. Eliminates duplication of color definitions.

**Constants:**

| Variable | Code | Usage |
|---|---|---|
| `G` | `\033[92m` | Green (UP, bullish, positive) |
| `R` | `\033[91m` | Red (DOWN, bearish, negative) |
| `Y` | `\033[93m` | Yellow (warnings, volatile) |
| `C` | `\033[96m` | Cyan (headers, decorative) |
| `W` | `\033[97m` | White (emphasis, values) |
| `B` | `\033[1m` | Bold (combined with colors) |
| `D` | `\033[90m` | Dim/gray (neutral, inactive) |
| `M` | `\033[95m` | Magenta (positions, TP/SL) |
| `BL` | `\033[5m` | Blink (active alerts, scenarios) |
| `X` | `\033[0m` | Reset all formatting |

This is a leaf module with no imports — it is imported by all other `src/` modules.

---

### 2.7 src/input_handler.py

**Purpose:** Cross-platform non-blocking keyboard input. Abstracts Windows (`msvcrt`) and Unix (`select`) differences.

**Functions:**

**`read_key_nb() -> str | None`**
- Non-blocking key read. Returns lowercase char or `None` if no key pressed.
- Windows: `msvcrt.kbhit()` + `msvcrt.getch()`
- Unix: `select.select([sys.stdin], [], [], 0)` + `sys.stdin.read(1)`

**`wait_for_key(timeout_sec=10) -> str | None`**
- Blocking wait with countdown display. Shows `>>> S=execute U=UP D=DOWN | wait Ns to ignore <<<`
- Returns lowercase char on keypress, `None` on timeout.
- Used during opportunity windows when a signal is detected.

**`sleep_with_key(seconds) -> str | None`**
- Sleeps in 0.1s increments, checking for keys between each.
- Returns key immediately if pressed, `None` after full duration.
- Used for the main loop sleep cycle (WS: 0.5s, HTTP: 2s).

---

### 2.8 src/signal_engine.py

**Purpose:** Core signal computation engine. Computes weighted signal scores from 6 indicators, with regime adjustment and phase-aware filtering.

**Module-level config (from `.env`):**

| Category | Constants |
|---|---|
| Signal weights | `W_MOMENTUM`, `W_DIVERGENCE`, `W_SR`, `W_MACD`, `W_VWAP`, `W_BB` |
| Volatility | `VOL_THRESHOLD`, `VOL_AMPLIFIER` |
| Regime multipliers | `REGIME_CHOP_MULT`, `REGIME_TREND_BOOST`, `REGIME_COUNTER_MULT` |
| Phase thresholds | `PHASE_EARLY_THRESHOLD`, `PHASE_MID_THRESHOLD`, `PHASE_LATE_THRESHOLD`, `PHASE_CLOSING_THRESHOLD` |
| Signal constants | `SIGNAL_NEUTRAL_ZONE`, `DIVERGENCE_LOOKBACK`, `SR_LOOKBACK` |
| TP/SL defaults | `TP_BASE_SPREAD`, `TP_STRENGTH_SCALE`, `TP_MAX_PRICE`, `SL_DEFAULT`, `SL_MIN_PRICE` |

**Functions:**

**`_ema(values, period) -> float`**
- Computes a single final EMA value from a list of floats.
- Used for the trend filter in S/R computation.

**`get_market_phase(time_remaining, window_min) -> (phase, threshold)`**
- Classifies market into EARLY/MID/LATE/CLOSING based on time remaining.
- Returns the phase name and the minimum signal strength threshold for that phase.
- Thresholds scale proportionally to window size.

**`compute_signal(up_buy, down_buy, btc_price, binance, history, regime='RANGE', phase='MID') -> dict`**
- The core signal engine. Takes `history` as a parameter (no globals).
- Computes 6 weighted components → volatility amplifier → regime adjustment → direction + strength.
- Returns dict with: `direction`, `strength`, `score`, `suggestion`, `tp`, `sl`, component details.
- See [Section 4](#4-signal-engine-internals) for detailed breakdown.

**`detect_scenario(signal, regime, phase, binance_data) -> tuple | None`**
- Pattern matcher that identifies named trading scenarios from current indicators.
- Returns `(scenario_name, ansi_color, is_warning)` or `None`.
- See [Section 4](#4-signal-engine-internals) for scenario list.

---

### 2.9 src/session_stats.py

**Purpose:** Session statistics calculation and formatted terminal display.

**Functions:**

**`calculate_session_stats(trade_history) -> dict`**
- Computes from a list of individual trade P&L values:
  - `wins`, `losses`, `win_rate` (percentage)
  - `best` (max P&L), `worst` (min P&L)
  - `gross_wins`, `gross_losses`, `profit_factor`
  - `max_drawdown` (peak-to-trough)

**`print_session_summary(duration_min, trade_count, session_pnl, trade_history) -> dict`**
- Prints a formatted summary box to terminal on exit.
- Returns the stats dict (also used by `RadarLogger.log_session_summary()`).

---

### 2.10 src/ui_panel.py

**Purpose:** Terminal UI rendering. Static panel and scrolling log formatter.

**Module-level state:**
- `PRICE_ALERT` — price threshold for alert display (from `.env`)
- `HEADER_LINES = 15` — number of lines in the static panel

**Functions:**

**`draw_panel(time_str, balance, btc_price, ..., asset_name, poly_latency_ms)`**
- 25+ parameters covering all display state.
- Renders the static 15-line panel at the top of the terminal.
- Uses `io.StringIO` buffer for single `write()` + `flush()` (reduces flicker).
- Uses ANSI escape codes: `\033[row;colH` for cursor positioning, `\033[K` for line clearing.
- Calls `detect_scenario()` from `signal_engine` for the ALERT line.
- Computes win rate and profit factor from `trade_history` for the POSITION line.

**`format_scrolling_line(time_str, btc_price, up_buy, down_buy, rsi_val, signal, binance_data, regime, phase, trade_amount, asset_name) -> str`**
- Formats a single scrolling log line with all indicator values.
- Called every cycle; output appears in the scroll region below the panel.
- Calls `detect_scenario()` and appends scenario tag at end of line.

**Panel layout (15 lines):**
```
Line  1: ═══ separator ═══
Line  2: RADAR POLYMARKET │ time │ balance │ trade amount
Line  3: ═══ separator ═══
Line  4: BINANCE │ price │ direction │ RSI │ Vol │ Regime │ data source
Line  5: MARKET  │ slug │ time remaining │ phase │ Price to Beat │ latency
Line  6: POLY    │ prices │ UP buy/sell │ DOWN buy/sell
Line  7: POSITION│ shares │ P&L │ trades │ win rate │ profit factor
Line  8: ACTION  │ last action performed
Line  9: SIGNAL  │ direction │ strength bar │ RSI │ trend │ MACD │ VWAP │ BB
Line 10: ALERT   │ scenario detection / status message
Line 11: ─── separator ───
Line 12: hotkey legend (U/D/C/S/Q)
Line 13: ═══ separator ═══
Line 14: column headers for scrolling log
Line 15: blank
```

---

### 2.11 src/trade_executor.py

**Purpose:** Trade execution functions. Buy, sell, close positions, and TP/SL monitoring.

**Design:** All functions receive `get_price` (callable) and `executor` (ThreadPoolExecutor) as parameters via dependency injection — no global state.

**Module-level constants:**

| Constant | Value | Purpose |
|---|---|---|
| `BUY_PRICE_OFFSET` | 0.02 | Aggressive offset above best bid |
| `SELL_PRICE_OFFSET` | 0.05 | Aggressive offset below best ask |
| `MIN_SHARES` | 5 | Polymarket minimum order size |
| `MAX_TOKEN_PRICE` | 0.99 | Max price for buy orders |
| `MIN_TOKEN_PRICE` | 0.01 | Min price for sell orders |
| `ORDER_MONITOR_TIMEOUT` | 30 | Seconds to wait for order fill |
| `ORDER_MONITOR_INTERVAL` | 2 | Seconds between order status checks |
| `CLOSE_MONITOR_TIMEOUT` | 15 | Seconds to wait for close order fill |
| `TP_SL_MONITOR_TIMEOUT` | 600 | Seconds before TP/SL monitoring times out |

**Functions:**

**`close_all_positions(positions, token_up, token_down, trade_logger, reason, session_pnl, trade_history, get_price) -> (total_pnl, count, session_pnl, pnl_list)`**
- Closes all positions and calculates P&L for each.
- `reason`: `'market_expired'`, `'emergency'`, `'exit'`, `'tp'`, `'sl'`, `'cancel'`
- Logs each close via `trade_logger.log_trade()`.
- Clears `positions` list in place.

**`execute_buy_market(client, direction, amount_usd, ..., get_price, executor) -> (result, msg)`**
- Submits aggressive market buy order via `executor.submit()`.
- Returns `({'shares': N, 'price': P}, success_msg)` or `(None, error_msg)`.

**`execute_close_market(client, token_up, token_down, get_price, executor) -> str`**
- Closes all positions with 3 retry attempts.
- For each token with shares >= 0.01: approve allowance → submit sell → monitor.

**`monitor_tp_sl(token_id, tp, sl, tp_above, sl_above, get_price, executor, timeout_sec) -> (reason, price)`**
- Monitors price until TP hit, SL hit, manual cancel (C key), or timeout.
- Uses concurrent price fetch + key checking for lower latency.
- Displays live progress bar: `SL $0.42 [████████░░] TP $0.58 │ C=close`.

**`execute_hotkey(client, direction, trade_amount, ..., get_price, executor) -> dict | None`**
- Wrapper for manual buy via hotkey (U/D). Returns position dict or `None`.

**`handle_buy(client, direction, trade_amount, ..., get_price, executor, reason) -> (info, balance, last_action)`**
- High-level buy handler. Executes buy, updates positions, balance, and logs trade.
- `reason`: `'signal'` or `'manual'`

---

### 2.12 radar_poly.py

**Purpose:** Main orchestrator. Contains the `TradingSession` class, `PriceCache`, and the main event loop.

**Size:** ~712 lines (reduced from ~1590 after extracting 6 modules).

#### Class: PriceCache

TTL-based cache for Polymarket token prices:
- Default TTL: 0.5s
- Only caches successful fetches (prevents caching error states)
- Key: `(token_id, side)` tuple
- Uses the module-level `_session` for HTTP requests

#### Class: TradingSession

Encapsulates all mutable state for a trading session:

| Category | Fields |
|---|---|
| Market state | `market_slug`, `token_up`, `token_down`, `price_to_beat`, `base_time` |
| Trading state | `positions`, `balance`, `session_pnl`, `trade_count`, `trade_history`, `current_signal` |
| Alert state | `alert_active`, `alert_side`, `alert_price` |
| UI state | `status_msg`, `status_clear_at`, `last_action`, `poly_latency_ms` |
| Timing | `last_beep`, `last_market_check` |
| Data history | `history` (deque, maxlen=60) |
| Error tracking | `binance_errors`, `market_refresh_errors` |

**Methods:**
- `set_status(msg, duration=3)` — set a temporary status message
- `clear_expired_status()` — auto-clear expired status messages
- `update_alert(up_buy, down_buy)` — edge-triggered price alert detection

#### Function: main()

The main event loop:

```
1.  Parse trade amount from CLI args
2.  Load MarketConfig
3.  Initialize RadarLogger
4.  Create TradingSession
5.  Display donation banner (20s countdown)
6.  Connect to Polymarket (create_client)
7.  Discover active market (find_current_market)
8.  Fetch Price to Beat
9.  Start Binance WebSocket
10. Configure terminal (cbreak mode, scroll region)
11. Main loop:
    a. Auto-clear status messages after 3s
    b. Refresh market every 60s (with exponential backoff on errors)
    c. Auto-recover WebSocket if dead
    d. Collect Binance data (WS preferred, HTTP fallback)
       - On error: exponential backoff: delay = min(2 * 2^errors, 30)
    e. Fetch Polymarket prices in parallel
    f. Determine market phase (via signal_engine.get_market_phase)
    g. Append to history deque
    h. Compute signal (via signal_engine.compute_signal)
    i. Log signal snapshot
    j. Draw static panel (via ui_panel.draw_panel)
    k. Print scrolling log line (via ui_panel.format_scrolling_line)
    l. Check for opportunity (beep + wait for key)
    m. Handle price alerts (edge-triggered)
    n. Sleep with key checking (0.5s WS / 2s HTTP)
    o. Process hotkeys (U/D/C/Q)
12. On exit: reset terminal, print session summary, log to CSV
13. Finally: stop WS, shutdown executor, restore terminal settings
```

**Exponential backoff (Binance errors):**
```python
session.binance_errors += 1
delay = min(2 * (2 ** (session.binance_errors - 1)), 30)
```

**Exponential backoff (market refresh):**
```python
refresh_interval = min(MARKET_REFRESH_INTERVAL * (2 ** session.market_refresh_errors), 300)
```

---

## 3. Data Flow

### Per-Cycle Data Flow (every 0.5-2s)

```
┌──────────────────┐      ┌───────────────────┐
│ BinanceWS        │      │ Polymarket CLOB    │
│ get_candles()    │      │ GET /price         │
│   ↓              │      │   ↓                │
│ candles + source │      │ up_buy, down_buy   │
└────────┬─────────┘      └─────────┬──────────┘
         │                          │
         │    ┌─────────────────────┘
         │    │   (parallel via ThreadPoolExecutor)
         ▼    ▼
┌─────────────────────┐
│ get_full_analysis() │  ← src/binance_api.py
│   compute_rsi()     │
│   compute_atr()     │
│   compute_macd()    │
│   compute_vwap()    │
│   compute_bollinger()│
│   detect_regime()   │
│   analyze_trend()   │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ compute_signal()    │  ← src/signal_engine.py
│   1. Momentum (30%) │
│   2. Divergence(20%)│
│   3. S/R (10%)      │
│   4. MACD (15%)     │
│   5. VWAP (15%)     │
│   6. Bollinger(10%) │
│   → vol amplifier   │
│   → regime adjust   │
│   → direction/str   │
└────────┬────────────┘
         │
    ┌────┴────┐
    ▼         ▼
draw_panel  format_scrolling_line    ← src/ui_panel.py
log_signal  detect_scenario          ← src/signal_engine.py
```

### Price Data Path

```
Binance WebSocket (real-time)
    │
    ├─► _on_message() → parse JSON → _candles buffer (under _lock)
    │
    └─► get_candles() → returns buffer + current forming candle
            │
            ├─► WS path: candles from memory (0ms latency)
            │
            └─► HTTP fallback: get_klines() → REST API (~300ms)
                    │
                    └─► also refreshes WS buffer (keeps it warm)
```

---

## 4. Signal Engine Internals

All signal computation lives in `src/signal_engine.py`.

### Score Computation

The signal score is a weighted sum in `[-1.0, +1.0]`:

```
score = momentum * W_MOMENTUM     (default 0.30)
      + divergence * W_DIVERGENCE  (default 0.20)
      + support_resistance * W_SR  (default 0.10)
      + macd * W_MACD              (default 0.15)
      + vwap * W_VWAP              (default 0.15)
      + bollinger * W_BB           (default 0.10)
```

Each component outputs a value in `[-1.0, +1.0]`.

### Component Details

**1. Momentum (30%)**
```
momentum = rsi_component * 0.4 + candle_score * 0.6

rsi_component:
  RSI < 25  → +1.0   (heavily oversold)
  RSI < 35  → +0.6
  RSI < 45  → +0.2
  RSI > 75  → -1.0   (heavily overbought)
  RSI > 65  → -0.6
  RSI > 55  → -0.2
  else      →  0.0

candle_score: clamped bin_score / 0.5 to [-1, +1]
```

**2. Divergence (20%)**
```
Look back DIVERGENCE_LOOKBACK (6) cycles.
btc_var = BTC % change
poly_var = UP price change

If BTC rising (>0.01%) and Poly stagnant (<0.02):
  div_score = min(btc_var * 8, 1.0)    → positive (buy UP)

If BTC falling (<-0.01%) and Poly stable (>-0.02):
  div_score = max(btc_var * 8, -1.0)   → negative (buy DOWN)
```

**3. Support/Resistance (10%) + Trend Filter**
```
Range: min/max of last SR_LOOKBACK (20) UP prices
Position = (current - min) / range

Position < 20% → +0.8  (near support)
Position < 35% → +0.4
Position > 80% → -0.8  (near resistance)
Position > 65% → -0.4

Trend filter: if |trend_strength| > 0.3 and S/R opposes trend:
  reduction = min(|trend_strength| * 2, 1.0)
  sr_score *= (1 - reduction)
```

**4. MACD (15%)**
```
|hist_delta| > 0.5 → full score (+/-1.0)
|hist_delta| > 0.1 → half score (+/-0.5)

Boost 1.2x if histogram and delta agree in direction
Clamped to [-1.0, +1.0]
```

**5. VWAP (15%)**
```
price_vs_vwap > +0.02%  → +0.5
price_vs_vwap < -0.02%  → -0.5
vwap_slope > +0.2       → +0.5
vwap_slope < -0.2       → -0.5

Combined, clamped to [-1.0, +1.0]
```

**6. Bollinger (10%)**
```
bb_pos < 15% → +0.8  (near lower band, oversold)
bb_pos < 30% → +0.4
bb_pos > 85% → -0.8  (near upper band, overbought)
bb_pos > 70% → -0.4

If squeeze detected: score *= 1.5 (breakout anticipation)
Clamped to [-1.0, +1.0]
```

### Post-Processing

```
1. Volatility amplifier:
   if ATR/price > VOL_THRESHOLD (3%):
     score *= VOL_AMPLIFIER (1.3)

2. Regime adjustment:
   CHOP      → score *= REGIME_CHOP_MULT (0.50)
   TREND_UP  → aligned *= REGIME_TREND_BOOST (1.15), counter *= REGIME_COUNTER_MULT (0.70)
   TREND_DOWN→ aligned *= REGIME_TREND_BOOST (1.15), counter *= REGIME_COUNTER_MULT (0.70)
   RANGE     → no change

3. Final clamp: [-1.0, +1.0]

4. Direction:
   score >  SIGNAL_NEUTRAL_ZONE (0.10) → UP
   score < -SIGNAL_NEUTRAL_ZONE        → DOWN
   else                                → NEUTRAL

5. Strength: |score| * 100  (0-100%)
```

### TP/SL Calculation

```
spread = TP_BASE_SPREAD + (strength / 100) * TP_STRENGTH_SCALE
       = 0.05 + (strength%) * 0.10

TP = min(entry + spread, TP_MAX_PRICE)   (default max 0.95)
SL = max(entry - SL_DEFAULT, SL_MIN_PRICE)  (default 0.06 / min 0.03)
```

### Scenario Detection

`detect_scenario()` in `src/signal_engine.py` identifies named trading patterns:

**Warning scenarios** (checked first, in priority order):
1. `CLOSING - DO NOT TRADE` — phase is CLOSING
2. `CHOP - AVOID TRADING` — regime is CHOP
3. `WEAK SIGNAL` — strength < 30 and not neutral
4. `NEUTRAL - NO MOMENTUM` — RSI 45-55 and MACD hist near zero

**Positive scenarios** (checked in order):
1. `SUPPORT BOUNCE` — RSI < 30, BB < 15%, VWAP rising, TREND_UP
2. `RESISTANCE BOUNCE` — RSI > 70, BB > 85%, VWAP falling, TREND_DOWN
3. `BREAKOUT MACD` — strong MACD delta, BB squeeze, high vol, strength > 70%
4. `DIVERGENCE UP/DN` — significant divergence score + trending regime
5. `MODERATE SUPPORT/RESISTANCE` — relaxed thresholds for moderate signals
6. `MOMENTUM UP/DN` — MACD delta > 0.2 and strength > 50%

Returns `(scenario_name, ansi_color, is_warning)` or `None`.

---

## 5. Concurrency Model

### Threads

| Thread | Purpose | Lifetime |
|---|---|---|
| Main thread | Event loop, UI rendering, key handling | Entire process |
| BinanceWS thread | WebSocket connection + reconnect loop | Start → stop/exit |
| ThreadPoolExecutor (2 workers) | Parallel Polymarket price fetches, order submission | Entire process |

### Thread Safety

- **BinanceWS candle buffer:** Protected by `threading.Lock`. All reads/writes to `_candles` and `_current` are under `_lock`.
- **PriceCache:** Not thread-safe (single-threaded access from main loop). The `_cache` dict is only accessed from the main thread.
- **TradingSession.history deque:** Not thread-safe, but only accessed from main thread.
- **ThreadPoolExecutor:** Used for fire-and-forget parallel price fetches. `Future.result()` is called synchronously in the main loop.

### Parallel I/O Pattern

```python
# Polymarket price fetches run in parallel
fut_up = _executor.submit(get_price, token_up, "BUY")
fut_dn = _executor.submit(get_price, token_down, "BUY")
up_buy = fut_up.result()     # blocks until done
down_buy = fut_dn.result()   # already done (ran in parallel)
```

### TP/SL Monitoring Concurrency

In `src/trade_executor.py`:

```python
# Price fetch runs concurrently with key checking
fut_price = executor.submit(get_price, token_id, "BUY")

for _ in range(5):           # 5 × 0.1s = 0.5s
    key = read_key_nb()      # non-blocking key check
    if key == 'c':
        fut_price.result()   # drain future before returning
        return 'CANCEL', price
    time.sleep(0.1)

price = fut_price.result()   # get price result
```

### Shutdown Sequence

```
1. KeyboardInterrupt / Q key
2. Print session summary (via session_stats.print_session_summary)
3. Exit main loop
4. finally block:
   a. binance_ws.stop()          → sets _running=False, closes WS
   b. _executor.shutdown(wait=True) → waits for pending futures
   c. Reset terminal scroll region
   d. Restore terminal settings (termios)
   e. logger.close()             → flushes and closes CSV files
```

---

## 6. Terminal UI Architecture

All UI rendering lives in `src/ui_panel.py`. Key input lives in `src/input_handler.py`.

### Scroll Region Technique

The terminal is split into two zones using ANSI escape code `\033[top;bottom r`:

```
┌─────────────────────────────────┐ ← Line 1
│         STATIC PANEL            │
│       (15 lines, redrawn        │
│        in place via cursor       │
│        positioning)              │
├─────────────────────────────────┤ ← Line 16 (HEADER_LINES + 1)
│         SCROLLING LOG           │
│       (uses normal scroll,      │
│        new lines push old       │
│        lines up)                 │
└─────────────────────────────────┘ ← Terminal bottom
```

**Setup:** `\033[16;{term_height}r` — scroll region starts at line 16

**Panel updates:** Cursor saved (`\033[s`), moved to specific lines (`\033[row;1H`), content written with line clear (`\033[K`), cursor restored (`\033[u`).

**Scrolling log:** Normal `print()` calls within the scroll region — terminal handles scrolling automatically.

### Key Input (Cross-Platform)

Handled by `src/input_handler.py`:

**Linux/macOS:**
- Terminal set to cbreak mode: `tty.setcbreak(fd)` (in `radar_poly.py`)
- Non-blocking read: `select.select([sys.stdin], [], [], 0)` with 0 timeout
- Restored on exit: `termios.tcsetattr(fd, TCSADRAIN, old_settings)`

**Windows:**
- ANSI enabled: `os.system("")` (triggers Windows 10+ ANSI support)
- Non-blocking read: `msvcrt.kbhit()` + `msvcrt.getch()`
- No terminal restore needed

### Output Buffering

- `sys.stdout.reconfigure(line_buffering=True)` — flush on every newline (real-time display)
- Panel draw uses `io.StringIO` buffer → single `write()` + `flush()` (avoids partial-render flicker)

---

## 7. Order Execution Pipeline

All execution functions live in `src/trade_executor.py`.

### Buy Flow

```
User presses U/D/S
    │
    ▼
handle_buy(client, direction, trade_amount, ..., get_price, executor)
    │                                                ← src/trade_executor.py
    ▼
execute_hotkey(client, direction, ...)
    │
    ▼
execute_buy_market(client, direction, amount_usd, ..., get_price, executor)
    │
    ├── get_price(token_id, "BUY")      → base_price
    ├── price = base_price + 0.02       → aggressive fill
    ├── shares = amount_usd / price
    ├── Validate: shares >= MIN_SHARES (5)
    │
    ├── executor.submit(_submit_order)  → async order creation
    │      ├── get_tick_size()
    │      ├── get_neg_risk()
    │      ├── create_order(OrderArgs)
    │      └── post_order(GTC)
    │
    ├── fut.result(timeout=15)           → wait for submission
    │
    └── monitor_order(order_id, interval=2, timeout=30)
           │                              ← src/polymarket_api.py
           ├── Poll every 2s
           ├── MATCHED → FILLED (return details)
           ├── CANCELED → CANCELLED
           └── Timeout → cancel + TIMEOUT
```

### Sell/Close Flow

```
execute_close_market(client, token_up, token_down, get_price, executor)
    │                                              ← src/trade_executor.py
    ├── Retry loop (3 attempts)
    │
    ├── get_token_position() for UP and DOWN       ← src/polymarket_api.py
    │
    ├── For each token with shares >= 0.01:
    │      ├── get_price(token_id, "SELL")
    │      ├── market_price = base_price - 0.05   → aggressive fill
    │      ├── update_balance_allowance()          → approve token
    │      ├── executor.submit(_submit_sell)
    │      └── monitor_order(interval=1, timeout=15)
    │
    └── sleep(1) between retries
```

### TP/SL Monitoring

```
monitor_tp_sl(token_id, tp, sl, ..., get_price, executor)
    │                                          ← src/trade_executor.py
    ├── Loop (timeout: 600s)
    │      ├── Submit get_price() to executor
    │      ├── Check keys 5 times (0.5s total)  ← src/input_handler.py
    │      │      └── C key → CANCEL
    │      ├── Get price result
    │      ├── Check TP: price >= tp → return TP
    │      ├── Check SL: price <= sl → return SL
    │      └── Display progress bar
    │
    └── return TIMEOUT
```

---

## 8. Configuration System

### Hierarchy

```
.env.example  →  .env  →  os.getenv()  →  module-level constants
                  (user creates)
```

### Parameter Categories (29 total)

| Category | Count | Module |
|---|---|---|
| Credentials | 1 | `src/polymarket_api.py` |
| Market selection | 2 | `src/market_config.py` |
| Trading | 4 | `radar_poly.py` (TRADE_AMOUNT, PRICE_ALERT, SIGNAL_STRENGTH_BEEP) + `src/ui_panel.py` (PRICE_ALERT) |
| Indicator periods | 7 | `src/binance_api.py` |
| Signal weights | 6 | `src/signal_engine.py` |
| Volatility | 2 | `src/signal_engine.py` |
| Regime multipliers | 3 | `src/signal_engine.py` |
| Phase thresholds | 3 | `src/signal_engine.py` |
| CLI override | 1 | `radar_poly.py` (argv[1]) |

### Loading Pattern

`radar_poly.py` calls `load_dotenv()` before importing `src/` modules. Each module reads env vars into module-level constants with defaults:

```python
# In src/signal_engine.py:
W_MOMENTUM = float(os.getenv('W_MOMENTUM', '0.30'))
```

This means configuration is frozen at import time. Changing `.env` requires a restart.

---

## 9. Setup Scripts

### setup.sh (Linux/macOS)

```
1. Check Python 3.10+ (parse version from sys.version_info)
2. Create venv/ if not exists
3. Activate venv + pip install -r requirements.txt
4. Copy .env.example → .env if .env doesn't exist
5. Verify critical imports (dotenv, py_clob_client, web3, eth_account, requests)
```

Uses `set -e` for fail-fast behavior.

### setup.bat (Windows)

Same 5 steps, adapted for CMD:
- Uses `where python` instead of `command -v`
- Uses `for /f` loops to capture Python version
- Uses `call venv\Scripts\activate.bat`
- Uses `copy` instead of `cp`
- Ends with `pause` so the user can see results

---

## 10. Dependencies

| Package | Version | Purpose |
|---|---|---|
| `requests` | >= 2.31.0 | HTTP client for Binance and Polymarket REST APIs |
| `python-dotenv` | >= 1.0.0 | Load `.env` configuration |
| `py-clob-client` | >= 0.34.0 | Polymarket CLOB API client (orders, positions, auth) |
| `web3` | >= 7.0.0 | Ethereum utilities (keccak256, checksum addresses, CREATE2) |
| `websocket-client` | >= 1.6.0 | Binance WebSocket connection (optional, falls back to HTTP) |

**Transitive dependencies from py-clob-client:** `eth-account`, `eth-abi`, `eth-utils`, etc.

**Standard library modules used:** `sys`, `os`, `io`, `time`, `logging`, `platform`, `shutil`, `json`, `csv`, `threading`, `collections.deque`, `concurrent.futures`, `datetime`, `select` (Unix), `termios` (Unix), `tty` (Unix), `msvcrt` (Windows).

---

## 11. Key Algorithms

### EMA (Exponential Moving Average)

Used in two places:

1. **`_ema()` in `src/signal_engine.py`** — single final value for trend filter
2. **`_ema_list()` in `src/binance_api.py`** — full series for MACD computation

```python
k = 2 / (period + 1)
ema[0] = values[0]
ema[i] = values[i] * k + ema[i-1] * (1 - k)
```

### Wilder's Smoothing (ADX)

Different from standard EMA. Used for +DI, -DI, ATR smoothing in ADX (`src/binance_api.py`):

```python
smoothed = (prev * (period - 1) + current) / period
```

Initial value: SMA of first `period` data points.

### CREATE2 Address Derivation

Polymarket uses proxy wallets (`src/polymarket_api.py`). Address computed deterministically:

```python
salt = keccak256(eoa_bytes)
address = keccak256(0xff || factory || salt || init_code_hash)[12:]
```

This allows the client to know the proxy address without querying the chain.

### Market Window Discovery

The timestamp alignment algorithm in `src/polymarket_api.py` handles clock drift and API timing:

```python
# Round to nearest window boundary
minute = now_et.minute
window_start_minute = (minute // window_min) * window_min

# Try multiple candidates to handle edge cases
possible = [rounded, raw, rounded - window_sec, rounded + window_sec]
```

Each candidate is validated: event must exist AND start time must be within 120s of expected.

---

## 12. Extension Points

### Adding a New Indicator

1. **`src/binance_api.py`:** Add `compute_new_indicator(candles) -> value`
2. **`src/binance_api.py`:** Call it in `get_full_analysis()`, add result to `details` dict
3. **`src/signal_engine.py`:** Add weight constant `W_NEW = float(os.getenv('W_NEW', '0.10'))`
4. **`src/signal_engine.py`:** Add component logic in `compute_signal()` (score += component * W_NEW)
5. **`src/ui_panel.py`:** Display in `format_scrolling_line()` and `draw_panel()`
6. **`.env.example`:** Add `W_NEW=0.10` with comment
7. **`src/logger.py`:** Add column to `SIGNAL_COLUMNS` and update `log_signal()`

### Adding a New Asset

1. **`src/market_config.py`:** Add to `SUPPORTED_ASSETS` set
2. No other changes needed — everything derives from `MarketConfig`

### Adding a New Market Window

1. **`src/market_config.py`:** Add to `SUPPORTED_WINDOWS` set
2. The phase calculation in `src/signal_engine.py:get_market_phase()` automatically scales proportionally

### Modifying the UI Layout

- Static panel: modify `draw_panel()` in `src/ui_panel.py`
- Scrolling log: modify `format_scrolling_line()` in `src/ui_panel.py`
- Adjust `HEADER_LINES` constant in `src/ui_panel.py` if panel height changes
- Scroll region will auto-adjust via `\033[{HEADER_LINES+1};{term_h}r`

### Modifying Trade Execution

- Buy/sell logic: modify `execute_buy_market()` / `execute_close_market()` in `src/trade_executor.py`
- TP/SL monitoring: modify `monitor_tp_sl()` in `src/trade_executor.py`
- Execution constants (offsets, timeouts): edit constants at top of `src/trade_executor.py`
