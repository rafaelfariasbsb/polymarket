# Trading Guide — Polymarket Crypto Scalping Radar

## Overview

The radar combines **6 technical indicators** from Binance with real-time Polymarket data to generate **UP** or **DOWN** signals on updown markets (BTC, ETH, SOL, XRP — 5 or 15 minute windows).

---

## 1. The 6 Indicators

### 1.1 Momentum (25% of signal)
Combines RSI + Binance candle analysis. RSI period: 5 (optimized for 15min).

| RSI       | Reading              | Signal         |
|-----------|----------------------|----------------|
| < 15      | Extreme oversold     | **Mean Reversion UP** |
| 15 – 25   | Heavily oversold     | Strong UP      |
| 25 – 35   | Oversold             | Moderate UP    |
| 35 – 45   | Slightly oversold    | Slight UP      |
| 45 – 55   | Neutral              | No signal      |
| 55 – 65   | Slightly overbought  | Slight DOWN    |
| 65 – 75   | Overbought           | Moderate DOWN  |
| 75 – 85   | Heavily overbought   | Strong DOWN    |
| > 85      | Extreme overbought   | **Mean Reversion DOWN** |

**Candles:** Last 5 candles — count of green/red, buyer vs seller volume, and momentum (average of last 3 vs previous 3).

### 1.2 BTC vs Polymarket Divergence (25% of signal)
Detects when BTC price and Polymarket UP price move in opposite directions.

| Situation | Interpretation |
|-----------|----------------|
| BTC rising + UP stagnant | Polymarket will "correct" upward → **buy UP** |
| BTC falling + UP stable | Polymarket will "correct" downward → **buy DOWN** |

**The greater the divergence, the stronger the signal.**

### 1.3 Support/Resistance (10% of signal)
Analyzes price position within the range of the last 20 candles.

| Range Position | Signal |
|----------------|--------|
| < 20% (near support) | UP (+0.8) |
| 20 – 35% | Slight UP (+0.4) |
| 65 – 80% | Slight DOWN (-0.4) |
| > 80% (near resistance) | DOWN (-0.8) |

**Trend filter:** If the overall trend is strong and contrary to S/R, the signal is automatically reduced.

### 1.4 MACD — Momentum Acceleration (10% of signal)
Standard MACD (12/26/9) — confirmation indicator, not primary driver.

| Condition | Signal |
|-----------|--------|
| Positive histogram + positive delta | Strong UP (momentum accelerating) |
| Positive histogram + negative delta | UP weakening |
| Negative histogram + negative delta | Strong DOWN |
| Negative histogram + positive delta | DOWN weakening |

**How to read on screen:** `+3.2▲` = positive histogram and accelerating. `-1.5▼` = negative and accelerating downward.

### 1.5 VWAP — Volume Weighted Average Price (15% of signal)

| Condition | Signal |
|-----------|--------|
| Price above VWAP + VWAP rising | Strong UP |
| Price above VWAP + VWAP falling | Weak UP |
| Price below VWAP + VWAP falling | Strong DOWN |
| Price below VWAP + VWAP rising | Weak DOWN |

**How to read on screen:** `+0.15↑` = price 0.15% above VWAP. `-0.08↓` = price 0.08% below.

### 1.6 Bollinger Bands — Extremes and Squeeze (15% of signal)
Bollinger Bands (10 periods, 1.5 standard deviations — tighter for 15min, better squeeze detection).

| Band Position | Signal |
|---------------|--------|
| < 15% (touching lower band) | Strong UP (oversold) |
| 15 – 30% | Slight UP |
| 70 – 85% | Slight DOWN |
| > 85% (touching upper band) | Strong DOWN (overbought) |

**Squeeze:** When bands become narrow (low volatility), the signal is amplified by 50% — indicates imminent breakout.

**How to read on screen:** `LO 12%` = near lower band. `HI 88%` = near upper band. `SQ` = squeeze detected.

---

## 2. Signal Modifiers

### 2.1 Volatility Amplifier
When ATR > 3% of price, all signals are amplified by **30%**.
- On screen shows `VOL↑` when active
- Volatile markets = bigger opportunities (and bigger risks)

### 2.2 Market Regime

| Regime | Icon | Effect on Signal |
|--------|------|------------------|
| **TREND_UP** | `T▲` | +15% if signal is UP, -30% if signal is DOWN |
| **TREND_DOWN** | `T▼` | +15% if signal is DOWN, -30% if signal is UP |
| **RANGE** | `RG` | Neutral (no modification) |
| **CHOP** | `CH` | **-50% on all signals** (avoid trading!) |

**Golden rule:** Trade with the regime. TREND_UP + strong UP signal = best scenario. CHOP = stay out.

---

## 3. Market Phases (Time Window)

Each updown market has a fixed duration (5 or 15 minutes). The radar divides this time into 4 phases:

| Phase | Time Remaining | Min Threshold | Recommendation |
|-------|----------------|---------------|----------------|
| **EARLY** | > 66% (e.g. >10min in 15m) | 50% | Conservative — strong signals only |
| **MID** | 33–66% (e.g. 5–10min) | 30% | Normal — best window for trading |
| **LATE** | 6–33% (e.g. 1–5min) | 70% | Aggressive — very strong signals only |
| **CLOSING** | < 6% (e.g. <1min) | Blocked | **DO NOT trade** — risk of non-execution |

**Best time to enter:** **MID** phase, when there's enough time for TP/SL to work and the threshold is lower.

---

## 4. When to Enter (Buy)

### 4.1 Automatic Entry (Signal)
The radar emits **3 beeps** when it detects an opportunity:
1. Strength ≥ current phase threshold
2. Defined direction (UP or DOWN)
3. TP/SL suggestion generated

**You have 10 seconds to accept with the `S` key.**

### 4.2 Manual Entry
At any time, press:
- **`U`** → Buy UP (bet that price goes up)
- **`D`** → Buy DOWN (bet that price goes down)

You can also buy directly on the **Polymarket website**. The radar automatically detects positions opened outside the script (every 60 seconds) and adds them to the panel display. On startup, it also checks for existing positions.

### 4.3 Mean Reversion Alert (Primary Strategy)

The radar's primary alert is the **Mean Reversion Alert** — it beeps only when all conditions align for a high-probability mean reversion trade:

**Trigger conditions (ALL must be true):**
1. Market phase = **MID** (minutes 5-10 of 15min window)
2. RSI at extreme level: **≤ 15** (oversold) or **≥ 85** (overbought)
3. Bollinger Bands touch: **≤ 0.10** (lower band) or **≥ 0.90** (upper band)
4. Reversal-side token price **< $0.70** (still cheap, not priced in)

**When it beeps (3 beeps):**
```
═══════════════════════════════════════════════════════════
  MEAN REVERSION → UP │ RSI=12 BB=0.05 │ $0.35
  Token cheap + RSI extreme + Bollinger touch
  Press U to buy or wait...
═══════════════════════════════════════════════════════════
```

**What to do:**
1. Check the direction (UP or DOWN)
2. Press the corresponding key (**U** for UP, **D** for DOWN)
3. The radar monitors TP/SL automatically (see section 5.1)
4. Wait for TP alert or close manually with **C**

**Expected performance:** ~65% win rate, TP = entry + $0.20 (cap at $0.55), SL = entry - $0.15 (floor at $0.05).

### 4.4 Entry Checklist (ideal)

```
✅ Regime: TREND_UP or TREND_DOWN (avoid CHOP)
✅ Phase: MID (best) or EARLY with strong signal
✅ Strength: ≥ 50% (the higher, the better)
✅ Indicators aligned:
   - Extreme RSI (< 15 for UP, > 85 for DOWN — mean reversion)
   - MACD accelerating in same direction
   - Price on the right side of VWAP
   - Bollinger confirming (touching extreme band)
✅ Volatility: VOL↑ present (amplifies gains)
✅ Divergence: BTC vs Poly divergent (correction likely)
```

### 4.5 High Probability Scenarios

**Scenario 1 — Mean Reversion (Primary):**
```
RSI ≤ 15 + BB ≤ 0.10 + MID phase + token < $0.70
→ Strong UP signal — price at extreme, reversal expected
→ The radar beeps automatically for this scenario
```

**Scenario 2 — Support Bounce:**
```
RSI < 30 + BB position < 15% + VWAP rising + TREND_UP
→ Strong UP signal (price oversold with support)
```

**Scenario 3 — MACD Breakout:**
```
Strong positive MACD delta + BB squeeze + VOL↑ + Strength > 70%
→ Imminent breakout in MACD direction
```

**Scenario 4 — Divergence + Trend:**
```
BTC rising + UP Poly stagnant + TREND_UP + RSI < 50
→ Polymarket will correct upward
```

### 4.6 When NOT to Enter

```
❌ CHOP regime — chaotic market, signals are unreliable
❌ CLOSING phase — less than 1 minute, no time to execute
❌ Strength < 30% — weak signal, indicators diverge from each other
❌ Neutral RSI (45–55) + neutral MACD — no clear momentum
❌ Just lost a trade — wait for the next market cycle
```

---

## 5. When to Exit (Close Position)

### 5.1 Position Monitor (TP/SL Alerts)
The radar continuously monitors all open positions and beeps when TP or SL levels are hit:

**Mean Reversion TP/SL (for manual entries via U/D keys):**
- **Take Profit (TP):** Entry + $0.20 (capped at $0.55)
- **Stop Loss (SL):** Entry - $0.15 (floor at $0.05)

| Entry Price | TP Target | SL Target | Risk:Reward |
|-------------|-----------|-----------|-------------|
| $0.30 | $0.50 | $0.15 | 1:1.3 |
| $0.35 | $0.55 | $0.20 | 1:1.3 |
| $0.40 | $0.55 | $0.25 | 1:1.0 |
| $0.50 | $0.55 | $0.35 | 1:0.3 |

**When TP is hit (2 beeps):**
```
  TP HIT │ UP $0.35 → $0.55 (+57%) │ Press C to close
```

**When SL is hit (1 beep):**
```
  SL HIT │ UP $0.35 → $0.20 (-43%) │ Press C to close
```

Press **C** to close all positions when alerted.

**Signal-based TP/SL (for entries via S key):**

The TP spread scales with confidence:
| Strength | TP Spread | Example (entry $0.50) |
|----------|-----------|----------------------|
| 30% | $0.08 | TP: $0.58 |
| 50% | $0.10 | TP: $0.60 |
| 70% | $0.12 | TP: $0.62 |
| 100% | $0.15 | TP: $0.65 |

**Fixed SL:** Entry - $0.06 (e.g. entry $0.50 → SL $0.44)

### 5.2 Manual Exit
- **`C`** → Closes ALL positions immediately (emergency close)
- Use when the scenario has changed drastically (e.g. regime turned CHOP)

### 5.3 Position Sync
The radar automatically syncs with the Polymarket platform every 60 seconds. If you **sell directly on the website**, the radar detects the sale and removes the position from its tracking. Similarly, your USDC balance is re-synced from the platform on each refresh.

### 5.4 Exit Rules

```
📊 TP hit → Profit realized automatically
📉 SL hit → Loss limited automatically
⏰ Market expiring → Positions closed on window transition
🔑 C key → Manual emergency exit
🚪 Q key → Close everything and shut down the radar
```

---

## 6. Reading the Panel

### BINANCE Line
```
BINANCE │ BTC: $98,432.50 │ UP (score:+0.35 conf:72%) │ RSI:38 │ Vol:HIGH │ TREND▲ │ WebSocket
```
- **Current price** of the asset on Binance
- **Direction** from Binance analysis with score and confidence
- **RSI**, **Volatility**, **Regime** and data source

### MARKET Line
```
MARKET  │ btc-updown-15m-1708617600 │ Closes in: 8.5min │ MID │ Beat: $98,200.00 (+232.50) │ Poly:145ms
```
- **Slug** of the active market
- **Time remaining** and current **phase**
- **Price to Beat:** reference price — if BTC ends above, UP wins; below, DOWN wins
- **Latency** of the Polymarket API

### POLY Line
```
POLY    │ BTC: $98,432.50 │ UP: $0.55/$0.45 (55%) │ DOWN: $0.45/$0.55 (45%)
```
- **Current price** of the asset
- **UP:** buy price / sell price (implied probability %)
- **DOWN:** buy price / sell price (implied probability %)

### POSITION Line
```
POSITION│ UP 52sh @ $0.55 │ Session P&L: +$3.20 │ Trades: 6 │ WR: 67% (4W/2L) │ PF: 2.1
```
- Current position (direction, shares, average price)
- Session P&L, number of trades, win rate and profit factor

### Scrolling Log
```
UP:$0.55 DN:$0.45 │ RSI: 38↑ │ ▲ UP      72% │ VOL↑ │ T:+0.5⬆ │ +3.2▲ │ +0.15↑ │ LO 12% │ SR:+0.8→+0.6 │ T▲
```

---

## 7. Hotkeys

| Key | Action |
|-----|--------|
| **U** | Buy UP (manual) |
| **D** | Buy DOWN (manual) |
| **S** | Accept automatic signal (during alert) |
| **C** | Close ALL positions (emergency) |
| **Q** | Shut down radar (closes positions + summary) |

---

## 8. Risk Management

### Fundamental Rules

1. **Never trade in CHOP regime** — signals are cut by 50% for a reason
2. **Respect the phase** — CLOSING = don't trade, LATE = very strong signals only
3. **One trade per window** — avoid overtrading; each window is 5 or 15 minutes
4. **SL is sacred** — never widen the SL to "give more room"
5. **Monitor your win rate** — below 50%, review your strategy
6. **Profit Factor > 1.5** — your average profit should be greater than your average loss

### Position Size
- Configured via `TRADE_AMOUNT` in `.env`
- Limited by `POSITION_LIMIT` (maximum total exposure)
- Start small ($2–5) until you validate the strategy

### Price to Beat — The Most Important Metric
The "Beat" shows the price BTC needs to be at **by the end of the window**:
- Current BTC **above** Beat → UP is winning
- Current BTC **below** Beat → DOWN is winning
- **Large difference** (e.g. +$300) → UP is likely, Poly price already reflects this
- **Small difference** (e.g. +$10) → undecided, higher risk

---

## 9. Complete Trade Flow

```
1. Radar detects opportunity
   ├── Strength: 65% UP
   ├── Regime: TREND_UP
   ├── Phase: MID
   └── BEEP BEEP BEEP

2. Trader evaluates (10 seconds)
   ├── Indicators aligned? ✅
   ├── Favorable regime? ✅
   ├── Enough time? ✅
   └── Presses S

3. Automatic execution
   ├── Buy UP @ $0.52
   ├── TP set: $0.62
   ├── SL set: $0.46
   └── Monitoring started

4. Result
   ├── TP hit → Sell @ $0.62 → P&L: +$0.10/share ✅
   ├── SL hit → Sell @ $0.46 → P&L: -$0.06/share ❌
   └── Manual (C) → Sell at current price

5. Radar resumes monitoring
   └── Waits for next signal
```

---

## 10. Advanced Tips

1. **Mean reversion is king:** The primary strategy for 15-minute windows. Wait for the radar to beep (RSI extreme + BB touch + MID phase) and trade the reversal. ~65% win rate historically.

2. **Buy the CHEAP token:** On mean reversion, you buy the side that's currently losing. If BTC is oversold (RSI < 15), buy UP — which is cheap because the market expects DOWN. That's where the edge is.

3. **Don't hold until expiry:** Take profit early when the position monitor alerts TP hit. Mean reversion trades often spike quickly then flatten. Early exit at TP captures most of the move.

4. **Combine indicators:** The best signal has extreme RSI + accelerating MACD + VWAP confirming. Don't rely on a single indicator.

5. **Watch the divergence:** When BTC moves strongly and Polymarket doesn't follow, the Poly usually "corrects" — that's the opportunity.

6. **Bollinger Squeeze:** Narrow bands → imminent breakout. If the squeeze coincides with MACD crossing, it's a powerful setup.

7. **Trend is your friend:** In TREND_UP, favor UP buys even with moderate signals. Against the trend, require very strong signals (>70%).

8. **High volatility = wider spread:** When VOL↑ appears, both gains and losses are amplified. Ideal for those seeking quick TP.

9. **Monitor your session P&L:** If you lost 3 trades in a row (win rate dropping), stop and wait for better conditions. The market will be there tomorrow.

10. **Price to Beat near current price:** When the difference is small ($0–$50), the market is undecided. These are the best moments for divergence signals.
