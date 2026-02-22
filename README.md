# Polymarket BTC Scalping Radar

Real-time scalping radar for Polymarket BTC 15-minute Up/Down markets, powered by Binance price data and a custom trend-following signal engine with market regime detection.

## Overview

This tool monitors BTC price on Binance and cross-references it with Polymarket's BTC 15-minute prediction markets. It generates trade signals based on momentum, divergence, support/resistance, volatility, and market regime analysis, displayed in a split-screen terminal UI with manual hotkey trading.

## Features

- **Cross-platform** — Runs on Linux, macOS, and Windows 10+
- **Split-screen terminal UI** — Static panel (top) with live stats + scrolling log (bottom)
- **Real-time signal engine** — Trend-following with EMA filter, RSI, divergence detection, S/R levels
- **Market regime detection** — Classifies market as TREND_UP, TREND_DOWN, RANGE, or CHOP to adapt signals
- **Phase-aware trading** — Adjusts signal thresholds based on time remaining in 15-min window (EARLY/MID/LATE/CLOSING)
- **Manual hotkey trading** — Press U/D/C/S/Q to buy UP, buy DOWN, close all, accept a signal, or exit
- **TP/SL monitoring** — Visual progress bar tracking take-profit and stop-loss levels
- **Price alerts** — Audio beep when prices cross configurable thresholds (edge-triggered, beeps once)
- **Market auto-discovery** — Automatically finds the active BTC 15-minute market window
- **CSV logging** — Signals, trades, and session summaries logged to `logs/` for analysis
- **Session stats** — Win rate, P&L, profit factor, and max drawdown displayed on exit

## Project Structure

```
polymarket/
├── radar_scalp.py        Main radar script (UI, signals, trading)
├── binance_api.py        Binance public API (price, candles, RSI, ATR, ADX, regime)
├── polymarket_api.py     Polymarket CLOB API (auth, orders, positions)
├── logger.py             CSV logging (signals, trades, session summaries)
├── .env                  Configuration - YOU CREATE THIS (see below)
├── .env.example          Example config template
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

### Step 2: Edit `.env` with your credentials

Open `.env` in any text editor and replace `0xYOUR_PRIVATE_KEY_HERE` with your actual private key exported from Polymarket.

### Available settings

| Variable | Description | Default |
|---|---|---|
| `POLYMARKET_API_KEY` | Private key exported from Polymarket wallet (0x...) | **Required** |
| `POSITION_LIMIT` | Max exposure in USD (positions + pending orders) | 76 |
| `TRADE_AMOUNT` | Trade amount in USD per operation | 4 |
| `PRICE_ALERT` | Price threshold that triggers audio alert | 0.80 |
| `SIGNAL_STRENGTH_BEEP` | Min signal strength (0-100) to trigger opportunity beep | 50 |

## Usage

```bash
# Activate virtual environment first
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate.bat       # Windows

# Run with default trade amount ($4 from .env)
python radar_scalp.py

# Run with custom trade amount
python radar_scalp.py 10        # $10 per trade
```

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
 ════════════════════════════════════════════════════════════════════════════════
 SCALP RADAR │ 14:32:15 │ Balance: $52.30 │ Trade: $4
 ════════════════════════════════════════════════════════════════════════════════
 BINANCE │ BTC: $98,432.50 │ UP (score:+0.35 conf:70%) │ RSI:42 │ Vol:normal │ TREND▲
 MARKET  │ btc-updown-15m-1740000 │ Closes in: 8.2min │ MID
 POLY    │ UP: $0.52/$0.55 (52%) │ DOWN: $0.45/$0.48 (45%)
 POSITION│ None │ P&L: +$0.00 (0 trades)
 SIGNAL  │ ▲ UP      62% [██████░░░░] │ RSI:42↑ │ T:+0.4 │ SR:+0.3→+0.2
 ALERT   │ ─
 ────────────────────────────────────────────────────────────────────────────────
 U=buy UP │ D=buy DOWN │ C=close all │ S=accept signal │ Q=exit
 ════════════════════════════════════════════════════════════════════════════════
   TIME     │          BTC │       UP       DN │    RSI │    SIGNAL  ─  STRENGTH │ VOL  │   TREND │           S/R │ RG

   14:32:15 │ BTC:$ 98,432 │ UP:$0.52 DN:$0.45 │ RSI:42↑ │ ▲ UP  62% [██████░░░░] │ VOL↑ │ T:+0.4⬆ │ SR:+0.3→+0.2 │ T▲
   14:32:17 │ BTC:$ 98,445 │ UP:$0.53 DN:$0.44 │ RSI:43↑ │ ▲ UP  65% [██████░░░░] │      │ T:+0.5⬆ │ SR:+0.2→+0.1 │ T▲
```

## Signal Engine

The signal is computed from 4 components with an EMA trend filter and regime-aware adjustments:

### Components

| Component | Weight | Description |
|-----------|--------|-------------|
| **BTC Momentum** | 40% | RSI (7-period) + Binance candle score |
| **Divergence** | 30% | BTC price vs Polymarket price divergence |
| **Support/Resistance** | 15% | Position within recent price range (with trend filter) |
| **Volatility** | Amplifier (1.3x) | ATR-based, boosts signal in high-volatility conditions |

### Trend Filter (EMA)

- EMA(5) vs EMA(12) of Polymarket UP price
- When trend is strong (>0.3), S/R signals that conflict with the trend are reduced
- Prevents false mean-reversion signals during strong momentum

### Regime Adjustments

The signal is adjusted based on the current market regime detected via ADX and Bollinger Bands:

| Regime | Condition | Effect |
|--------|-----------|--------|
| **TREND_UP** | ADX > 25, price above SMA, majority green candles | +15% boost for UP signals, -30% for DOWN |
| **TREND_DOWN** | ADX > 25, price below SMA, majority red candles | +15% boost for DOWN signals, -30% for UP |
| **RANGE** | ADX 18-25, or mixed signals | No adjustment |
| **CHOP** | ADX < 18, wide Bollinger bands | Signal dampened by 50% |

### Phase Thresholds

Signal strength threshold varies by time remaining in the 15-minute window:

| Phase | Time Remaining | Min Strength | Behavior |
|-------|---------------|-------------|----------|
| **EARLY** | > 10 min | 50% | Conservative, only strong signals |
| **MID** | 5-10 min | 30% | Normal operation |
| **LATE** | 1-5 min | 70% | Very selective, only very strong signals |
| **CLOSING** | < 1 min | Blocked | No new trades allowed |

### Signal Output

- **Direction**: UP / DOWN / NEUTRAL
- **Strength**: 0-100% (minimum varies by phase)
- **Suggestion**: Entry price, TP (take profit), SL (stop loss)

## Logging

All activity is logged to CSV files in the `logs/` directory (auto-created, gitignored):

| File | Content | Frequency |
|------|---------|-----------|
| `signals_YYYY-MM-DD.csv` | Every radar cycle snapshot (price, RSI, ATR, signal, regime) | Every ~2s |
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

### `radar_scalp.py`
Main radar script with split-screen terminal UI. Cross-platform (Linux/macOS/Windows). Handles:
- Data collection (Binance + Polymarket every 2s)
- Signal computation with regime and phase awareness
- Hotkey-based manual trading (U/D/C/S/Q)
- TP/SL monitoring with visual progress bar
- Price alerts (edge-triggered audio beeps)
- Session P&L tracking (wins, losses, profit factor, drawdown)

### `binance_api.py`
Binance public API wrapper (no authentication needed):
- `get_btc_price()` — Current BTC/USDT price
- `get_klines()` — Historical candles (1m default)
- `compute_rsi()` — Fast RSI (7-period)
- `compute_atr()` — Average True Range
- `compute_adx()` — Average Directional Index (trend strength)
- `compute_bollinger_bandwidth()` — Bollinger Bands width and position
- `detect_regime()` — Market regime classification (TREND_UP/DOWN, RANGE, CHOP)
- `get_full_analysis()` — Combined analysis with trend, RSI, ATR, ADX, regime
- `analyze_trend()` — Score-based trend analysis

### `polymarket_api.py`
Polymarket CLOB API wrapper:
- `create_client()` — Authenticated ClobClient with proxy wallet
- `find_current_market()` — Auto-discovers active BTC 15m market
- `get_balance()` — USDC balance (net of open orders)
- `get_token_position()` — Conditional token balance
- `check_limit()` — Position limit verification
- `monitor_order()` — Order status tracking until fill/cancel/timeout

### `logger.py`
CSV logging module:
- `RadarLogger.log_signal()` — Logs each radar cycle (every ~2s)
- `RadarLogger.log_trade()` — Logs trade events (BUY, CLOSE)
- `RadarLogger.log_session_summary()` — Logs session stats on exit
- Auto-rotates files daily (`signals_YYYY-MM-DD.csv`, `trades_YYYY-MM-DD.csv`)

### Setup & config
- `setup.sh` — Automated setup for Linux/macOS (bash)
- `setup.bat` — Automated setup for Windows (cmd)
- `.env.example` — Template configuration file (copy to `.env` and add your private key)
- `requirements.txt` — Python package dependencies

## Technical Details

- **Terminal UI**: ANSI escape codes with scroll regions (`\033[top;bottomr`)
- **Key input (Linux/macOS)**: Non-blocking via `tty.setcbreak()` + `select.select()`
- **Key input (Windows)**: Non-blocking via `msvcrt.kbhit()` + `msvcrt.getch()`
- **ANSI on Windows**: Enabled with `os.system("")` (Windows 10+)
- **Output buffering**: `sys.stdout.reconfigure(line_buffering=True)` for real-time display
- **Price history**: `deque(maxlen=60)` — ~2 minutes of data at 2s polling interval
- **Market discovery**: Timestamp-based slug matching (`btc-updown-15m-{timestamp}`)
- **Proxy wallet**: CREATE2 address derivation from Polymarket factory contract
- **Regime detection**: ADX (Wilder's smoothing) + Bollinger Bandwidth + SMA direction
- **Log rotation**: Daily CSV files with automatic header creation

## License

Private use only.
