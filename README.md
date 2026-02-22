# Polymarket Crypto Scalping Radar

Real-time scalping radar for Polymarket crypto Up/Down markets (BTC, ETH, SOL, XRP — 5m/15m windows), powered by Binance price data via WebSocket and a 6-component signal engine with market regime detection.

## Overview

This tool monitors crypto prices on Binance (WebSocket + HTTP fallback) and cross-references them with Polymarket's prediction markets. It generates trade signals based on 6 weighted components — momentum, divergence, support/resistance, MACD, VWAP, and Bollinger Bands — displayed in a split-screen terminal UI with manual hotkey trading.

## Features

- **Real-time data** — Binance WebSocket for sub-second BTC price updates (HTTP fallback)
- **6-component signal engine** — RSI, MACD, VWAP, Bollinger Bands, divergence, S/R levels
- **Market regime detection** — Classifies market as TREND_UP, TREND_DOWN, RANGE, or CHOP via ADX
- **Phase-aware trading** — Adjusts signal thresholds based on time remaining (EARLY/MID/LATE/CLOSING)
- **Split-screen terminal UI** — Static panel (top) with live stats + scrolling log (bottom)
- **Cross-platform** — Runs on Linux, macOS, and Windows 10+
- **Manual hotkey trading** — Press U/D/C/S/Q to buy UP, buy DOWN, close all, accept a signal, or exit
- **TP/SL monitoring** — Visual progress bar tracking take-profit and stop-loss levels
- **Price alerts** — Audio beep when prices cross configurable thresholds (edge-triggered)
- **Multi-market support** — BTC, ETH, SOL, XRP with 5-minute or 15-minute windows
- **Market auto-discovery** — Automatically finds the active market window
- **CSV logging** — Signals, trades, and session summaries logged to `logs/` for analysis
- **Session stats** — Win rate, P&L, profit factor, and max drawdown displayed on exit
- **Fully configurable** — 29 parameters via `.env` (market, indicators, weights, thresholds, regime)

## Project Structure

```
polymarket/
├── radar_poly.py        Main radar script (UI, signals, trading)
├── market_config.py      Market configuration (asset, window, derived values)
├── binance_api.py        Binance API (price, candles, RSI, MACD, VWAP, BB, ADX, regime)
├── ws_binance.py         Binance WebSocket client (real-time klines, auto-reconnect)
├── polymarket_api.py     Polymarket CLOB API (auth, orders, positions)
├── logger.py             CSV logging (signals, trades, session summaries)
├── .env                  Configuration - YOU CREATE THIS (see below)
├── .env.example          Example config template (29 parameters)
├── requirements.txt      Python dependencies
├── setup.sh              Setup script for Linux / macOS
├── setup.bat             Setup script for Windows
├── logs/                 Auto-generated CSV logs (gitignored)
└── README.md             This file
```

## Installation

### Prerequisites

- Python 3.10+
- Polymarket account with exported private key
- Terminal with ANSI color support (Windows Terminal, iTerm2, any Linux terminal)
- Terminal window with at least **160 columns x 30 lines** (the layout may break on smaller screens)

### Quick Setup (Linux / macOS)

```bash
cd polymarket
chmod +x setup.sh
./setup.sh
```

### Quick Setup (Windows)

```
cd polymarket
setup.bat
```

Or double-click `setup.bat` in File Explorer.

> **Note:** Windows requires Windows 10+ for ANSI color support. Use Windows Terminal for best results.

### What the setup scripts do

1. Verify Python 3.10+ is installed
2. Create a virtual environment (`venv/`)
3. Install all dependencies from `requirements.txt`
4. Create `.env` from `.env.example` if it doesn't exist
5. Verify all Python imports work correctly

### Manual Installation

If you prefer to install manually:

```bash
cd polymarket
python -m venv venv

# Linux/macOS
source venv/bin/activate

# Windows
venv\Scripts\activate.bat

pip install -r requirements.txt
```

## Configuration

**Before running, you must create a `.env` file** with your Polymarket private key.

### Step 1: Copy the example file

```bash
# Linux/macOS
cp .env.example .env

# Windows
copy .env.example .env
```

> The setup scripts (`setup.sh` / `setup.bat`) do this automatically if `.env` doesn't exist.

### Step 2: Export your Polymarket private key

To use the radar, you need to export your private key from Polymarket:

1. Log in to your Polymarket account in the browser
2. Open a new tab and go to: **https://reveal.magic.link/polymarket**
3. Sign in with the same email/Google used on Polymarket
4. Your private key will be displayed — copy it (starts with `0x...`)
5. Log out of Magic.Link after copying

> **Security:** Never share your private key with anyone. Polymarket will never ask for it. After pasting in `.env`, copy a random text to clear your clipboard.

> **Note:** This method works for accounts created via email (Magic.Link). If you use a different wallet provider, export the key from that wallet directly.

### Step 3: Edit `.env` with your credentials

Open `.env` in any text editor and replace `0xYOUR_PRIVATE_KEY_HERE` with the private key you exported:

### Available settings

#### Market Selection

| Variable | Description | Default |
|---|---|---|
| `MARKET_ASSET` | Crypto asset to trade (`btc`, `eth`, `sol`, `xrp`) | btc |
| `MARKET_WINDOW` | Market window duration in minutes (`5` or `15`) | 15 |

**Available markets:**

| Asset | 5-minute | 15-minute |
|-------|----------|-----------|
| BTC | `btc-updown-5m` | `btc-updown-15m` |
| ETH | `eth-updown-5m` | `eth-updown-15m` |
| SOL | `sol-updown-5m` | `sol-updown-15m` |
| XRP | `xrp-updown-5m` | `xrp-updown-15m` |

#### Credentials & Trading

| Variable | Description | Default |
|---|---|---|
| `POLYMARKET_API_KEY` | Private key exported from Polymarket wallet (0x...) | **Required** |
| `POSITION_LIMIT` | Max exposure in USD (positions + pending orders) | 76 |
| `TRADE_AMOUNT` | Trade amount in USD per operation | 4 |
| `PRICE_ALERT` | Price threshold that triggers audio alert | 0.80 |
| `SIGNAL_STRENGTH_BEEP` | Min signal strength (0-100) to trigger opportunity beep | 50 |

#### Indicator Periods

| Variable | Description | Default |
|---|---|---|
| `RSI_PERIOD` | RSI period (lower = more reactive) | 7 |
| `MACD_FAST` | MACD fast EMA period | 5 |
| `MACD_SLOW` | MACD slow EMA period | 10 |
| `MACD_SIGNAL` | MACD signal line period | 4 |
| `BB_PERIOD` | Bollinger Bands lookback period | 14 |
| `BB_STD` | Bollinger Bands standard deviations | 2 |
| `ADX_PERIOD` | ADX period (trend strength) | 7 |

#### Signal Weights (must sum to ~1.0)

| Variable | Component | Default |
|---|---|---|
| `W_MOMENTUM` | BTC Momentum (RSI + candle score) | 0.30 |
| `W_DIVERGENCE` | Divergence (BTC price vs Polymarket price) | 0.20 |
| `W_SUPPORT_RESISTANCE` | Support/Resistance levels | 0.10 |
| `W_MACD` | MACD histogram delta (momentum acceleration) | 0.15 |
| `W_VWAP` | VWAP position + slope | 0.15 |
| `W_BOLLINGER` | Bollinger Bands position | 0.10 |

#### Volatility & Regime

| Variable | Description | Default |
|---|---|---|
| `VOL_THRESHOLD` | ATR/price ratio to flag high volatility (0.03 = 3%) | 0.03 |
| `VOL_AMPLIFIER` | Score multiplier when high volatility detected | 1.3 |
| `REGIME_CHOP_MULT` | CHOP regime: dampen signal (0.5 = -50%) | 0.50 |
| `REGIME_TREND_BOOST` | Trend-aligned: boost signal (1.15 = +15%) | 1.15 |
| `REGIME_COUNTER_MULT` | Counter-trend: reduce signal (0.7 = -30%) | 0.70 |

#### Phase Thresholds

| Variable | Phase | Default |
|---|---|---|
| `PHASE_EARLY_THRESHOLD` | EARLY (>66% time left): conservative | 50 |
| `PHASE_MID_THRESHOLD` | MID (33-66% time left): normal | 30 |
| `PHASE_LATE_THRESHOLD` | LATE (6-33% time left): very selective | 70 |

## Usage

**Step 1:** Activate the virtual environment (required every new terminal session):
```bash
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate.bat       # Windows
```

**Step 2:** Run the radar:
```bash
python radar_poly.py            # Default trade amount ($4 from .env)
python radar_poly.py 10         # Custom: $10 per trade
```

> **Important:** You must run `source venv/bin/activate` before `python radar_poly.py`. Without the venv, dependencies like WebSocket won't work. The radar will show a warning if the venv is not activated.

### Hotkeys

| Key | Action |
|-----|--------|
| `U` | Buy UP (market order) |
| `D` | Buy DOWN (market order) |
| `C` | Emergency close all positions |
| `S` | Accept suggested signal trade |
| `Q` | Exit (closes open positions first) |

### Screen Layout

```
 ════════════════════════════════════════════════════════════════════════════════════════
 SCALP RADAR │ 14:32:15 │ Balance: $52.30 │ Trade: $4
 ════════════════════════════════════════════════════════════════════════════════════════
 BINANCE │ BTC: $98,432.50 │ UP (score:+0.35 conf:70%) │ RSI:42 │ Vol:normal │ TREND▲ │ WS
 MARKET  │ btc-updown-15m-1740000 │ Closes in: 8.2min │ MID
 POLY    │ UP: $0.52/$0.55 (52%) │ DOWN: $0.45/$0.48 (45%)
 POSITION│ None │ P&L: +$0.00 (0 trades)
 SIGNAL  │ ▲ UP      62% [██████░░░░] │ RSI:42↑ │ T:+0.4 │ MACD:+1.2 │ VW:+0.03 │ BB:45%
 ALERT   │ ─
 ────────────────────────────────────────────────────────────────────────────────────────
 U=buy UP │ D=buy DOWN │ C=close all │ S=accept signal │ Q=exit
 ════════════════════════════════════════════════════════════════════════════════════════
   TIME     │          BTC │       UP       DN │    RSI │    SIGNAL  ─  STRENGTH │ VOL  │   TREND │   MACD │   VWAP │   BB │           S/R │ RG

   14:32:15 │ BTC:$ 98,432 │ UP:$0.52 DN:$0.45 │ RSI:42↑ │ ▲ UP  62% [██████░░░░] │ VOL↑ │ T:+0.4⬆ │  +1.2▲ │ +0.03↑ │ MD45% │ SR:+0.3→+0.2 │ T▲
   14:32:16 │ BTC:$ 98,445 │ UP:$0.53 DN:$0.44 │ RSI:43↑ │ ▲ UP  65% [██████░░░░] │      │ T:+0.5⬆ │  +1.5▲ │ +0.04↑ │ MD48% │ SR:+0.2→+0.1 │ T▲
```

## Color Coding

All indicators use color to show their current state at a glance:

| Indicator | Green | Red | Gray |
|-----------|-------|-----|------|
| **RSI** | < 40 (oversold / bullish) | > 60 (overbought / bearish) | 40-60 (neutral) |
| **Trend** | Positive (bullish) | Negative (bearish) | Near zero |
| **MACD** | Histogram > 0 (bullish momentum) | Histogram < 0 (bearish momentum) | Near zero |
| **VWAP** | Price above VWAP (bullish) | Price below VWAP (bearish) | At VWAP |
| **Bollinger** | > 80% (price strong / near upper band) | < 20% (price weak / near lower band) | 20-80% (mid-band) |
| **S/R** | Positive (support zone) | Negative (resistance zone) | Neutral |
| **Regime** | TREND UP | TREND DOWN | RANGE / CHOP |
| **Signal** | UP direction | DOWN direction | NEUTRAL |

These colors apply both to the **static panel** (SIGNAL line) and to the **scrolling log** columns.

## Signal Engine

The signal is computed from 6 weighted components with an EMA trend filter, regime-aware adjustments, and volatility amplification. All weights and parameters are configurable via `.env`.

### Components

| # | Component | Weight | Indicator | Description |
|---|-----------|--------|-----------|-------------|
| 1 | **BTC Momentum** | 30% | RSI + candle score | RSI oversold/overbought zones combined with Binance candle pattern scoring (green/red ratio, volume, momentum) |
| 2 | **Divergence** | 20% | BTC vs Polymarket | Detects when BTC price moves but Polymarket hasn't caught up yet (leading signal) |
| 3 | **Support/Resistance** | 10% | Price range position | Position within recent UP price range. Filtered by EMA trend to prevent false mean-reversion |
| 4 | **MACD** | 15% | Histogram delta | Measures momentum acceleration. Positive histogram delta = bullish acceleration. Boosted when histogram and delta agree |
| 5 | **VWAP** | 15% | Position + slope | Price above VWAP = bullish, below = bearish. VWAP slope adds directional confirmation |
| 6 | **Bollinger Bands** | 10% | Band position | Price near lower band = oversold (UP), near upper = overbought (DOWN). Squeeze detection amplifies breakout signals |

### Indicators in Detail

#### RSI (Relative Strength Index)

- **Period**: 7 (configurable via `RSI_PERIOD`)
- Measures momentum on a 0-100 scale
- Below 25 = strong oversold (bullish), above 75 = strong overbought (bearish)
- Short period (7) provides faster signals for scalping vs traditional 14-period

#### MACD (Moving Average Convergence Divergence)

- **Periods**: Fast=5, Slow=10, Signal=4 (configurable via `MACD_FAST`, `MACD_SLOW`, `MACD_SIGNAL`)
- Optimized for 1-minute candles (shorter periods than traditional 12/26/9)
- **MACD line** = Fast EMA - Slow EMA
- **Signal line** = EMA of MACD line
- **Histogram** = MACD - Signal (positive = bullish momentum)
- **Histogram delta** = change in histogram (acceleration/deceleration)
- Signal logic: strong delta (>0.5) = full score, moderate delta (>0.1) = half score
- Boosted 1.2x when histogram and delta agree in direction

#### VWAP (Volume Weighted Average Price)

- Cumulative volume-weighted price since first candle in window
- **Price vs VWAP**: above = bullish (+0.5), below = bearish (-0.5)
- **VWAP slope**: upward slope = bullish (+0.5), downward = bearish (-0.5)
- Slope computed from last 5 VWAP values, normalized to -1.0 to +1.0
- Combined score clamped to [-1.0, +1.0]

#### Bollinger Bands

- **Period**: 14, **Std Dev**: 2 (configurable via `BB_PERIOD`, `BB_STD`)
- **Position**: 0% = at lower band (oversold), 100% = at upper band (overbought)
- Below 15% = strong buy signal (+0.8), above 85% = strong sell signal (-0.8)
- **Squeeze detection**: when current bandwidth < 50% of previous period bandwidth
- Squeeze amplifies signal 1.5x (breakout anticipation)

#### ADX (Average Directional Index)

- **Period**: 7 (configurable via `ADX_PERIOD`)
- Measures trend strength on a 0-100 scale (direction-agnostic)
- Uses Wilder's smoothing method (SMA for initial, then exponential)
- ADX > 25 = strong trend, ADX 18-25 = range, ADX < 18 = chop/no direction

#### ATR (Average True Range)

- Measures price volatility (average of true range across all candles)
- Used as volatility amplifier: when ATR/price > 3%, signal is boosted by 1.3x
- Does not contribute as a weighted component — acts as a multiplier

### Trend Filter (EMA)

- EMA(5) vs EMA(12) of Polymarket UP price history
- Computes trend strength from -1.0 (strong down) to +1.0 (strong up)
- When trend is strong (|strength| > 0.3), S/R signals that conflict with the trend are reduced
- Prevents false mean-reversion signals during strong momentum moves

### Regime Detection

The signal is adjusted based on the current market regime detected via ADX, Bollinger bandwidth, and SMA direction:

| Regime | Condition | Effect |
|--------|-----------|--------|
| **TREND_UP** | ADX > 25, price above SMA, >=4/7 green candles | Aligned signals boosted +15%, counter signals reduced -30% |
| **TREND_DOWN** | ADX > 25, price below SMA, <=3/7 green candles | Aligned signals boosted +15%, counter signals reduced -30% |
| **RANGE** | ADX 18-25, or mixed signals | No adjustment |
| **CHOP** | ADX < 18, wide Bollinger bands | Signal dampened by 50% |

All multipliers are configurable: `REGIME_CHOP_MULT`, `REGIME_TREND_BOOST`, `REGIME_COUNTER_MULT`.

### Phase Thresholds

Signal strength threshold varies by time remaining, proportional to the market window size:

| Phase | Time Remaining | Min Strength | Behavior |
|-------|---------------|-------------|----------|
| **EARLY** | > 66% of window | 50% | Conservative, only strong signals |
| **MID** | 33-66% of window | 30% | Normal operation |
| **LATE** | 6-33% of window | 70% | Very selective, only very strong signals |
| **CLOSING** | < 6% of window | Blocked | No new trades allowed |

For a 15m window: EARLY >10min, MID 5-10min, LATE 1-5min, CLOSING <1min.
For a 5m window: EARLY >3.3min, MID 1.7-3.3min, LATE 0.3-1.7min, CLOSING <18s.

Thresholds are configurable: `PHASE_EARLY_THRESHOLD`, `PHASE_MID_THRESHOLD`, `PHASE_LATE_THRESHOLD`.

### Signal Output

- **Direction**: UP / DOWN / NEUTRAL
- **Strength**: 0-100% (minimum varies by phase)
- **Suggestion**: Entry price, TP (take profit), SL (stop loss)

### Signal Flow

```
Binance candles (WS/HTTP)
       │
       ├─► RSI ──────────────┐
       ├─► MACD (hist delta) ─┤
       ├─► VWAP (pos + slope)─┤
       ├─► Bollinger (pos) ───┤     Weighted Sum     Regime      Phase
       │                      ├──────────►  score  ──► adjust ──► threshold ──► SIGNAL
       │   Polymarket prices  │                        (ADX)      (time)
       ├─► Divergence ────────┤
       ├─► S/R + trend filter─┘
       │
       └─► ATR ── volatility amplifier (1.3x if high vol)
```

## Data Sources

### Binance

- **Primary**: WebSocket `wss://stream.binance.com:9443/ws/{asset}usdt@kline_1m` (real-time, ~0ms latency)
- **Fallback**: REST API `https://api.binance.com/api/v3/klines` (~300ms per call)
- Supports all configured assets: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT
- WebSocket provides 1-minute klines with auto-reconnect and exponential backoff
- Candle buffer maintained in memory (30 completed + 1 forming)
- Data source shown in dashboard: `WS` (green) or `HTTP` (gray)

### Polymarket

- REST API via `py-clob-client` for prices, orders, and positions
- Parallel price fetches for UP and DOWN tokens via ThreadPoolExecutor
- Market auto-discovery via timestamp-based slug matching

### Update Cycle

| Data Source | Cycle Time | Method |
|-------------|-----------|--------|
| With WebSocket | ~0.5s | WS candles + parallel Poly HTTP |
| HTTP fallback | ~2.0s | Sequential Binance HTTP + parallel Poly HTTP |

## Logging

All activity is logged to CSV files in the `logs/` directory (auto-created, gitignored):

| File | Content | Frequency |
|------|---------|-----------|
| `signals_YYYY-MM-DD.csv` | Every radar cycle snapshot (price, RSI, ATR, MACD, VWAP, BB, regime) | Every ~0.5-2s |
| `trades_YYYY-MM-DD.csv` | Trade events (BUY, CLOSE) with P&L | On each trade |
| `sessions.csv` | Session summaries (duration, win rate, P&L, drawdown) | On exit |

### Session Summary

On exit (Q or Ctrl+C), the radar displays a session summary:

```
 ═════════════════════════════════════════════
  SESSION SUMMARY
 ─────────────────────────────────────────────
  Duration:       45 min
  Total Trades:   6
  Win Rate:       67% (4W / 2L)
  Total P&L:      +$3.20
  Best Trade:     +$2.10
  Worst Trade:    -$1.50
  Profit Factor:  2.10
  Max Drawdown:   -$1.50
 ═════════════════════════════════════════════
```

## Files

### `radar_poly.py`
Main radar script with split-screen terminal UI. Cross-platform (Linux/macOS/Windows). Handles:
- Data collection (Binance WS + Polymarket every 0.5s)
- Signal computation (6 components + regime + phase)
- Hotkey-based manual trading (U/D/C/S/Q)
- TP/SL monitoring with visual progress bar
- Price alerts (edge-triggered audio beeps)
- Session P&L tracking (wins, losses, profit factor, drawdown)

### `market_config.py`
Market configuration module:
- `MarketConfig` — Reads `MARKET_ASSET` and `MARKET_WINDOW` from `.env`
- Derives: slug prefix, Binance symbol, WebSocket symbol, window seconds, display name
- Validates supported assets (btc, eth, sol, xrp) and windows (5, 15)

### `binance_api.py`
Binance public API wrapper (no authentication needed). All functions accept a `symbol` parameter (default: BTCUSDT):
- `get_btc_price(symbol)` — Current price for any trading pair
- `get_klines(symbol)` — Historical candles (1m default)
- `compute_rsi()` — RSI (configurable period, default 7)
- `compute_atr()` — Average True Range (volatility)
- `compute_adx()` — Average Directional Index (trend strength, Wilder's smoothing)
- `compute_macd()` — MACD line, signal line, histogram, histogram delta
- `compute_vwap()` — VWAP price, position vs VWAP, VWAP slope
- `compute_bollinger()` — Upper/middle/lower bands, bandwidth, position, squeeze detection
- `compute_bollinger_bandwidth()` — Simplified bandwidth + position
- `detect_regime()` — Market regime classification (TREND_UP/DOWN, RANGE, CHOP)
- `get_full_analysis(candles, symbol)` — Combined analysis with all indicators (accepts WS candles)
- `analyze_trend()` — Score-based candle trend analysis

### `ws_binance.py`
Binance WebSocket client for real-time kline data (configurable symbol):
- `BinanceWS(symbol, interval)` — Dynamic endpoint based on trading pair
- Auto-reconnect with exponential backoff (2s → 30s max)
- Dual endpoint failover (`stream.binance.com:9443` and `:443`)
- Thread-safe candle buffer (completed + live forming candle)
- Seeds initial data via HTTP on startup
- Falls back to HTTP polling when WebSocket is unavailable
- Returns `(candles, source)` where source is `'ws'` or `'http'`

### `polymarket_api.py`
Polymarket CLOB API wrapper:
- `create_client()` — Authenticated ClobClient with proxy wallet
- `find_current_market(config)` — Auto-discovers active market for configured asset/window
- `get_balance()` — USDC balance (net of open orders)
- `get_token_position()` — Conditional token balance
- `check_limit()` — Position limit verification
- `monitor_order()` — Order status tracking until fill/cancel/timeout

### `logger.py`
CSV logging module:
- `RadarLogger.log_signal()` — Logs each radar cycle (every ~0.5-2s)
- `RadarLogger.log_trade()` — Logs trade events (BUY, CLOSE)
- `RadarLogger.log_session_summary()` — Logs session stats on exit
- Auto-rotates files daily (`signals_YYYY-MM-DD.csv`, `trades_YYYY-MM-DD.csv`)

### Setup & config
- `setup.sh` — Automated setup for Linux/macOS (bash)
- `setup.bat` — Automated setup for Windows (cmd)
- `.env.example` — Template configuration file with 29 parameters
- `requirements.txt` — Python package dependencies

## Technical Details

- **Terminal UI**: ANSI escape codes with scroll regions (`\033[top;bottomr`)
- **Key input (Linux/macOS)**: Non-blocking via `tty.setcbreak()` + `select.select()`
- **Key input (Windows)**: Non-blocking via `msvcrt.kbhit()` + `msvcrt.getch()`
- **ANSI on Windows**: Enabled with `os.system("")` (Windows 10+)
- **Output buffering**: `sys.stdout.reconfigure(line_buffering=True)` for real-time display
- **WebSocket**: `websocket-client` library with `run_forever()`, 30s ping interval
- **Parallel I/O**: `ThreadPoolExecutor` for concurrent Polymarket price fetches
- **Price history**: `deque(maxlen=60)` — ~2 minutes of data at 2s polling interval
- **Market discovery**: Timestamp-based slug matching (`{asset}-updown-{window}m-{timestamp}`)
- **Proxy wallet**: CREATE2 address derivation from Polymarket factory contract
- **Regime detection**: ADX (Wilder's smoothing) + Bollinger bandwidth + SMA direction
- **Log rotation**: Daily CSV files with automatic header creation

## Support the Developer

Built by a freelance developer in his spare time. If this tool helps you trade, consider sending a tip — any amount helps keep this project alive and improving.

**Send a tip on Polymarket:**

```
https://polymarket.com/profile/0xa27Bf6B2B26594f8A1BF6Ab50B00Ae0e503d71F6
```

Thank you for your support!

## License

Private use only.
