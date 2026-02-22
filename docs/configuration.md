# Configuration Reference

All 29 parameters are configured via the `.env` file. Copy `.env.example` to `.env` and edit as needed.

---

## Credentials

| Variable | Description | Default |
|---|---|---|
| `POLYMARKET_API_KEY` | Private key exported from Polymarket wallet (0x...) | **Required** |

## Market Selection

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

## Trading

| Variable | Description | Default |
|---|---|---|
| `POSITION_LIMIT` | Max exposure in USD (positions + pending orders) | 76 |
| `TRADE_AMOUNT` | Trade amount in USD per operation | 4 |
| `PRICE_ALERT` | Price threshold that triggers audio alert | 0.80 |
| `SIGNAL_STRENGTH_BEEP` | Min signal strength (0-100) to trigger opportunity beep | 50 |

## Indicator Periods

| Variable | Description | Default |
|---|---|---|
| `RSI_PERIOD` | RSI period (lower = more reactive) | 7 |
| `MACD_FAST` | MACD fast EMA period | 5 |
| `MACD_SLOW` | MACD slow EMA period | 10 |
| `MACD_SIGNAL` | MACD signal line period | 4 |
| `BB_PERIOD` | Bollinger Bands lookback period | 14 |
| `BB_STD` | Bollinger Bands standard deviations | 2 |
| `ADX_PERIOD` | ADX period (trend strength) | 7 |

## Signal Weights

Component weights for the signal score. Must sum to ~1.0.

| Variable | Component | Default |
|---|---|---|
| `W_MOMENTUM` | BTC Momentum (RSI + candle score) | 0.30 |
| `W_DIVERGENCE` | Divergence (BTC price vs Polymarket price) | 0.20 |
| `W_SUPPORT_RESISTANCE` | Support/Resistance levels | 0.10 |
| `W_MACD` | MACD histogram delta (momentum acceleration) | 0.15 |
| `W_VWAP` | VWAP position + slope | 0.15 |
| `W_BOLLINGER` | Bollinger Bands position | 0.10 |

## Volatility & Regime

| Variable | Description | Default |
|---|---|---|
| `VOL_THRESHOLD` | ATR/price ratio to flag high volatility (0.03 = 3%) | 0.03 |
| `VOL_AMPLIFIER` | Score multiplier when high volatility detected | 1.3 |
| `REGIME_CHOP_MULT` | CHOP regime: dampen signal (0.5 = -50%) | 0.50 |
| `REGIME_TREND_BOOST` | Trend-aligned: boost signal (1.15 = +15%) | 1.15 |
| `REGIME_COUNTER_MULT` | Counter-trend: reduce signal (0.7 = -30%) | 0.70 |

## Phase Thresholds

Min signal strength per market phase (proportional to window size).

| Variable | Phase | Default |
|---|---|---|
| `PHASE_EARLY_THRESHOLD` | EARLY (>66% time left): conservative | 50 |
| `PHASE_MID_THRESHOLD` | MID (33-66% time left): normal | 30 |
| `PHASE_LATE_THRESHOLD` | LATE (6-33% time left): very selective | 70 |
