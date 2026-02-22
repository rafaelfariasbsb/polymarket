# Polymarket Crypto Scalping Radar

Real-time scalping radar for Polymarket crypto Up/Down markets (BTC, ETH, SOL, XRP — 5m/15m windows), powered by Binance price data via WebSocket and a 6-component signal engine with market regime detection.

## Features

- **Real-time data** — Binance WebSocket for sub-second price updates (HTTP fallback)
- **6-component signal engine** — RSI, MACD, VWAP, Bollinger Bands, divergence, S/R levels
- **Market regime detection** — Classifies market as TREND_UP, TREND_DOWN, RANGE, or CHOP via ADX
- **Phase-aware trading** — Adjusts signal thresholds based on time remaining (EARLY/MID/LATE/CLOSING)
- **Split-screen terminal UI** — Static panel (top) with live stats + scrolling log (bottom)
- **Cross-platform** — Runs on Linux, macOS, and Windows 10+
- **Manual hotkey trading** — Press U/D/C/S/Q to buy UP, buy DOWN, close all, accept a signal, or exit
- **TP/SL monitoring** — Visual progress bar tracking take-profit and stop-loss levels
- **Multi-market support** — BTC, ETH, SOL, XRP with 5-minute or 15-minute windows
- **Session stats** — Win rate, P&L, profit factor, and max drawdown
- **Fully configurable** — 29 parameters via `.env`

## Project Structure

```
polymarket/
├── radar_poly.py                Main entry point (TradingSession, event loop)
├── src/                         Library modules
│   ├── signal_engine.py         Signal computation (6 indicators, regime, scenarios)
│   ├── ui_panel.py              Terminal UI (static panel, scrolling log)
│   ├── trade_executor.py        Trade execution (buy, sell, close, TP/SL)
│   ├── input_handler.py         Cross-platform keyboard input
│   ├── session_stats.py         Session statistics and summary
│   ├── colors.py                Shared ANSI color constants
│   ├── binance_api.py           Binance API + indicators (RSI, MACD, VWAP, BB, ADX)
│   ├── ws_binance.py            Binance WebSocket client (auto-reconnect, HTTP fallback)
│   ├── polymarket_api.py        Polymarket CLOB API (auth, orders, positions)
│   ├── market_config.py         Market configuration (asset, window, derived values)
│   └── logger.py                CSV logging (signals, trades, sessions)
├── docs/                        Documentation
│   ├── index.md                 Documentation hub
│   ├── TRADING_GUIDE.md         How to trade with the radar
│   ├── configuration.md         All 29 .env parameters
│   ├── development-guide.md     Technical reference for developers
│   └── backlog.md               Feature backlog and roadmap
├── .env.example                 Config template (copy to .env)
├── requirements.txt             Python dependencies
├── setup.sh / setup.bat         Setup scripts (Linux/macOS / Windows)
└── logs/                        Auto-generated CSV logs
```

## Quick Start

### 1. Setup

```bash
# Linux/macOS
chmod +x setup.sh && ./setup.sh

# Windows
setup.bat
```

This creates a virtual environment, installs dependencies, and copies `.env.example` to `.env`.

### 2. Configure

Export your private key from **https://polymarket.com/settings?tab=export-private-key**, then edit `.env`:

```
POLYMARKET_API_KEY=0xYOUR_PRIVATE_KEY_HERE
```

> **Security:** Never share your private key. After pasting in `.env`, clear your clipboard.

See [docs/configuration.md](docs/configuration.md) for all 29 parameters.

### 3. Run

```bash
source venv/bin/activate        # Linux/macOS (required every session)
# venv\Scripts\activate.bat     # Windows

python radar_poly.py            # Default $4 trades (from .env)
python radar_poly.py 10         # $10 per trade
```

## Hotkeys

| Key | Action |
|-----|--------|
| `U` | Buy UP (market order) |
| `D` | Buy DOWN (market order) |
| `S` | Accept suggested signal trade |
| `C` | Emergency close all positions |
| `Q` | Exit (prints session summary) |

## Screen Layout

```
 ═══════════════════════════════════════════════════════════════════════════════════════════════
 RADAR POLYMARKET │ 14:32:15 │ Balance: $52.30 │ Trade: $4
 ═══════════════════════════════════════════════════════════════════════════════════════════════
 BINANCE │ BTC: $98,432.50 │ UP (score:+0.35 conf:70%) │ RSI:42 │ Vol:normal │ TREND▲ │ WebSocket
 MARKET  │ btc-updown-15m-1740000 │ Closes in: 8.2min │ MID │ Beat: $98,200.00 (+232.50)
 POLY    │ BTC: $98,432.50 │ UP: $0.52/$0.48 (52%) │ DOWN: $0.48/$0.52 (48%)
 POSITION│ None │ P&L: +$0.00 (0 trades)
 ACTION  │ ─
 SIGNAL  │ ▲ UP      62% [██████░░░░] │ RSI:42↑ │ T:+0.4 │ MACD:+1.2 │ VW:+0.03 │ BB:45%
 ALERT   │ ─
 ─────────────────────────────────────────────────────────────────────────────────────────────
 U=buy UP │ D=buy DOWN │ C=close all │ S=accept signal │ Q=exit
 ═══════════════════════════════════════════════════════════════════════════════════════════════
       UP       DN │  RSI  │  SIGNAL   STRENGTH  │ VOL │ TREND │  MACD │  VWAP │  BB  │     S/R     │ RG
   UP:$0.52 DN:$0.48 │ RSI:42↑ │ ▲ UP  62% [██████░░░░] │ VOL↑ │ T:+0.4⬆ │ +1.2▲ │ +0.03↑ │ MD45% │ SR:+0.3→+0.2 │ T▲
```

## Documentation

| Document | Description |
|---|---|
| **[Trading Guide](docs/TRADING_GUIDE.md)** | Indicators explained, entry/exit rules, scenarios, risk management |
| **[Configuration](docs/configuration.md)** | All 29 `.env` parameters with defaults |
| **[Development Guide](docs/development-guide.md)** | Architecture, signal engine internals, concurrency, extension points |
| **[Backlog](docs/backlog.md)** | Feature roadmap |

## Support the Developer

If this tool helps you trade, consider sending a tip:

**https://polymarket.com/profile/0xa27Bf6B2B26594f8A1BF6Ab50B00Ae0e503d71F6**

## License

Private use only.
