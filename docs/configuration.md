# Configuration Reference

All 32 parameters are configured via the `.env` file. Copy `.env.example` to `.env` and edit as needed.

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
| `PRICE_ALERT_ENABLED` | Enable (1) or disable (0) audio beep when token price crosses threshold | 1 |
| `PRICE_ALERT` | Price threshold that triggers audio alert | 0.80 |
| `SIGNAL_ENABLED` | Enable (1) or disable (0) signal opportunity beep + trade prompt | 1 |
| `SIGNAL_STRENGTH_BEEP` | Min signal strength (0-100) to trigger opportunity beep | 50 |
| `PRICE_BEAT_ALERT` | Beep when BTC price moves $X or more from Price to Beat (0 = disabled) | 80 |

## Indicator Periods

Optimized for 15-minute mean reversion strategy.

| Variable | Description | Default |
|---|---|---|
| `RSI_PERIOD` | RSI period (2-6 optimal for 15min; shorter = more reactive) | 5 |
| `MACD_FAST` | MACD fast EMA period | 12 |
| `MACD_SLOW` | MACD slow EMA period | 26 |
| `MACD_SIGNAL` | MACD signal line period | 9 |
| `BB_PERIOD` | Bollinger Bands lookback period (tighter for 15min squeeze detection) | 10 |
| `BB_STD` | Bollinger Bands standard deviations (1.5 = tighter bands) | 1.5 |
| `ADX_PERIOD` | ADX period (14 = standard, recommended for regime detection) | 14 |

## Signal Weights

Component weights for the signal score. Must sum to ~1.0. Optimized for mean reversion (divergence + bollinger have higher weight).

| Variable | Component | Default |
|---|---|---|
| `W_MOMENTUM` | BTC Momentum (RSI + candle score) | 0.25 |
| `W_DIVERGENCE` | Divergence (BTC price vs Polymarket price — key for mean reversion) | 0.25 |
| `W_SUPPORT_RESISTANCE` | Support/Resistance levels | 0.10 |
| `W_MACD` | MACD histogram delta (confirmation, not primary) | 0.10 |
| `W_VWAP` | VWAP position + slope | 0.15 |
| `W_BOLLINGER` | Bollinger Bands position (squeeze + band touch = entry signal) | 0.15 |

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
| `PHASE_EARLY_THRESHOLD` | EARLY (>66% time left): conservative — wait for data | 55 |
| `PHASE_MID_THRESHOLD` | MID (33-66% time left): best entry window — more permissive | 25 |
| `PHASE_LATE_THRESHOLD` | LATE (6-33% time left): very selective — only high conviction | 70 |
