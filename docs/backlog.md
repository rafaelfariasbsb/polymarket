# Improvement Backlog — Polymarket BTC Scalping Radar

Document generated from the analysis of 3 specialists (Architecture, Trading, Performance) on `radar_poly.py`.

**Date:** 2026-02-22
**Branch:** develop
**Last commit:** 2147539

---

## Status of Original Plan Phases

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Logging & Backtesting | ✅ Complete |
| 2 | New Indicators (MACD, VWAP, BB) | ✅ Complete |
| 3 | Market Regime Detection | ✅ Complete |
| 4 | Dynamic TP/SL & Trailing Stop | ⬜ Pending |
| 5 | Session Win Rate & Performance Stats | ✅ Complete |
| 6 | WebSocket Real-Time Data | ✅ Complete |
| 7 | Minor Improvements | ⬜ Partial |
| 8 | Multi-Market Support | ✅ Complete |

---

## Identified Improvements — Analysis from 3 Specialists

### HIGH PRIORITY

#### 1. TP/SL Non-Blocking (Phase 4)
- **Problem**: `monitor_tp_sl()` is a blocking loop — while monitoring TP/SL, the radar stops updating, the static panel freezes, and the scrolling log receives no new data.
- **Solution**: Integrate TP/SL checking into the main cycle (`while True`). Each cycle (0.5s), check if price has reached TP or SL. Keep progress bar on the ACTION line of the static panel.
- **Impact**: High — user experience and responsiveness
- **Effort**: Medium
- **Files**: `radar_poly.py` — refactor `monitor_tp_sl()` to state-based instead of loop

#### 2. Dynamic TP/SL with ATR (Phase 4)
- **Problem**: Fixed stop loss of `$0.06` and TP based on fixed spread (`0.05 + strength * 0.10`). In a volatile market, SL is too tight (stopped out by noise); in a calm market, it's too wide (loses too much when wrong).
- **Solution**: Use ATR (already available in `binance_data['atr']`) to calculate dynamic TP/SL:
  - `TP = entry + ATR * 1.5`
  - `SL = entry - ATR * 1.0`
  - Minimum Risk:Reward ratio of 1.5:1
- **Impact**: High — risk management
- **Effort**: Low
- **Files**: `radar_poly.py` — lines 308-311 (`suggestion` dict)

#### 3. Market Expiry — Execute Real Close
- **Problem**: During market transition (line 860-877), the code calculates theoretical P&L via `get_price(token_id, "SELL")` but **does not execute** `execute_close_market()`. The tokens remain in the user's wallet without being sold.
- **Solution**: Call `execute_close_market()` before calculating P&L on transition. If the sell fails, warn the user.
- **Impact**: High — real money can get stuck in expired tokens
- **Effort**: Low
- **Files**: `radar_poly.py` — market transition block (~line 860)

#### 4. Periodically Re-sync Balance ✅
- **Problem**: `balance` is set once at startup (`get_balance(client)`) and then manually decremented/incremented on each trade. Over time, it diverges from the actual balance due to rounding, fees, and partially filled orders.
- **Solution**: Call `get_balance(client)` every 60s (along with the market refresh) to correct the drift.
- **Impact**: Medium — incorrect information on the panel
- **Effort**: Low
- **Files**: `radar_poly.py` — inside the `if now - last_market_check > 60` block
- **Status**: ✅ Implemented — `get_balance(client)` called every 60s in the market refresh block

---

### MEDIUM PRIORITY

#### 5. Trailing Stop (Phase 4)
- **Problem**: Once set, TP and SL are fixed. If the price goes 80% of the way to TP and then reverses, the trade can end at SL (-100% of risk).
- **Solution**: Trailing stop with 3 levels:
  - Price reaches 50% of TP → move SL to breakeven (entry)
  - Price reaches 75% of TP → move SL to 50% of profit
  - Display updated trailing SL in the progress bar
- **Impact**: Medium — protects partial profit
- **Effort**: Medium
- **Files**: `radar_poly.py` — `monitor_tp_sl()` (or new non-blocking logic)

#### 6. Persistent `requests.Session()` (Phase 7) ✅
- **Problem**: `get_price()` creates a new HTTP connection on each call (`requests.get()`). With 2+ calls per cycle (UP + DOWN), that's ~4 new TCP connections per second in WebSocket mode.
- **Solution**: Create a global or per-module `requests.Session()` to reuse HTTP connections via keep-alive.
- **Impact**: CRITICAL — each requests.get() opens a new TCP connection (+50-500ms per request)
- **Effort**: Low
- **Files**: `radar_poly.py` (`get_price()`), `binance_api.py`, `polymarket_api.py`
- **Status**: ✅ Implemented — global sessions in all 3 modules

#### 7. Persistent ThreadPoolExecutor ✅
- **Problem**: `ThreadPoolExecutor(max_workers=2)` is created and destroyed each cycle (line 1149). In WebSocket mode (~2 cycles/s), that's 1800+ creations/destructions per hour.
- **Solution**: Create the pool once at module level and reuse it.
- **Impact**: HIGH — thread creation/destruction overhead every 0.5-2s
- **Effort**: Low
- **Files**: `radar_poly.py` — move `ThreadPoolExecutor` to module level
- **Status**: ✅ Implemented — persistent pool with shutdown in finally

#### 8. Extract `handle_buy()` and `handle_close()` Functions (DRY) ✅
- **Problem**: The buy logic is duplicated in 3 locations:
  1. Lines 1075-1120 — signal buy (during opportunity, with TP/SL)
  2. Lines 1123-1134 — manual buy during opportunity (U/D)
  3. Lines 1159-1178 — manual buy during sleep cycle (U/D)
  Each location repeats: `execute_hotkey()` + `last_action` + `positions.append()` + `balance -=` + `logger.log_trade()`. Any change needs to be made in 3 places.
- **Solution**: Create `handle_buy(client, direction, amount, reason, ...)` that encapsulates all buy logic. Same for `handle_close()` for the 3 close locations (emergency, TP/SL, market expiry, exit).
- **Impact**: Medium — reduces inconsistency bugs, eases maintenance
- **Effort**: Medium
- **Files**: `src/trade_executor.py` — `handle_buy()`, `close_all_positions()`, `execute_close_market()`
- **Status**: ✅ Implemented — extracted to `src/trade_executor.py` with dependency injection (`get_price`, `executor` as parameters)

#### 9. Timeout on `monitor_tp_sl()`
- **Problem**: `monitor_tp_sl()` runs indefinitely until TP, SL, or manual cancellation (C). If the price stays in the neutral zone for 15+ minutes, the market can change and the user is stuck in a loop without updates.
- **Solution**: Add `timeout_sec` (default 600s / 10min). If exceeded, return `('TIMEOUT', current_price)`.
- **Impact**: Low — edge case, but dangerous
- **Effort**: Low
- **Files**: `radar_poly.py` — `monitor_tp_sl()`

#### 10. Multi-Market Support (Phase 8) ✅
- **Problem**: The entire system was hardcoded for `btc-updown-15m`. 30+ references across 4 files.
- **Solution**: New `market_config.py` with `MarketConfig` class that centralizes configuration derived from `MARKET_ASSET` and `MARKET_WINDOW` (.env).
- **Impact**: High — enables operating BTC, ETH, SOL, XRP in 5min and 15min windows
- **Effort**: High
- **Files**: `market_config.py` (new), `polymarket_api.py`, `binance_api.py`, `ws_binance.py`, `radar_poly.py`, `.env.example`
- **Status**: ✅ Implemented — MarketConfig, find_current_market(config), symbol param in all Binance functions, dynamic WS, parameterized display, proportional phases

---

### LOW PRIORITY

#### 11. PanelState Dataclass for `draw_panel()`
- **Problem**: `draw_panel()` has **30 parameters**. Hard to read, easy to get the order wrong, and any new data requires changing the signature + all 4 call sites.
- **Solution**: Create `@dataclass PanelState` with all fields. Pass a single object to `draw_panel()`.
- **Impact**: Low — readability and maintainability
- **Effort**: Medium
- **Files**: `src/ui_panel.py`

#### 12. Extract `format_scrolling_line()` ✅
- **Problem**: The scrolling line formatting (lines 966-1054) is ~90 lines of column construction inside the main loop.
- **Solution**: Extract to `format_scrolling_line(signal, btc_price, up_buy, down_buy, positions, regime)`.
- **Impact**: Low — readability
- **Effort**: Low
- **Files**: `src/ui_panel.py`
- **Status**: ✅ Implemented — extracted to `src/ui_panel.py`

#### 13. History Deque with Gap Protection
- **Problem**: `history = deque(maxlen=60)` is global and `_ema()` has no protection against timestamp discontinuities. If there's a data gap (WS disconnects for 5min), the EMA mixes old data with new.
- **Solution**: Before calculating EMA, filter `hist` removing entries with timestamp > 30s difference from the previous one.
- **Impact**: Low — edge case of WS reconnection
- **Effort**: Low
- **Files**: `radar_poly.py` — `compute_signal()`

#### 14. Connection Pooling (Phase 7) ✅
- **Problem**: `binance_api.py` and `polymarket_api.py` create individual HTTP connections per request.
- **Solution**: Use `requests.Session()` in each module to reuse connections.
- **Impact**: Low — complements item 6
- **Effort**: Low
- **Files**: `binance_api.py`, `polymarket_api.py`
- **Status**: ✅ Implemented along with item 6

#### 15. Failed VWAP Reclaim Detection (Phase 7)
- **Problem**: When price crosses VWAP upward but fails to hold, it's a strong DOWN signal. Currently not detected.
- **Solution**: Track VWAP crossovers. If price crossed above in the last 5 samples but is now below → boost DOWN signal.
- **Impact**: Low — incremental signal improvement
- **Effort**: Low
- **Files**: `radar_poly.py` — `compute_signal()`

#### 16. Market Transition Handling (Phase 7)
- **Problem**: When the 15min window closes, the radar waits until the next 60s check to find the new market.
- **Solution**: When `time_remaining < 0.5min`, check every 10s instead of 60s. Display switching notification.
- **Impact**: Low — reduces gap between markets
- **Effort**: Low
- **Files**: `radar_poly.py` — market refresh logic

---

## Detailed Analysis: `main()` — Refactored ✅

~~The `main()` function (lines 717→1317) concentrates all system logic: UI, trading, hotkeys, market transition, alerts and session. It is the main maintainability bottleneck.~~

**Status:** Partially resolved. `radar_poly.py` was refactored from **1,591 → 712 lines (-55%)**. Six modules were extracted to `src/`, a `TradingSession` class encapsulates all mutable state, and exponential backoff was added on API failures. The `main()` function still contains the event loop (~350 lines) but now delegates to extracted modules for all heavy logic.

### Block Map

| Lines | Block | Lines | Extractable? |
|-------|-------|:-----:|:------------:|
| 717-723 | Parse trade_amount argument | 6 | Yes |
| 725-749 | Logger + donation banner + countdown | 24 | Partial |
| 751-770 | Connect API + balance + find market | 19 | Partial |
| 772-780 | Price to Beat (historical BTC) | 8 | Yes |
| 782-800 | Start WebSocket | 18 | Yes |
| 802-820 | Configure terminal (tty, scroll region) | 18 | Yes |
| 822-842 | Initialize session variables + initial panel | 20 | Partial |
| 846-928 | Data collection (WS/HTTP candles, analysis) | 82 | Yes |
| 930-947 | Fetch token prices + compute signal | 17 | Partial |
| 949-964 | Log signal + update static panel | 15 | Partial |
| **967-1055** | **Format scrolling line (columns + colors)** | **88** | **Yes** |
| **1057-1138** | **Opportunity + hotkeys (signal buy + TP/SL)** | **81** | **Yes** |
| 1140-1154 | Price alert (beep) | 14 | Yes |
| **1156-1220** | **Sleep + manual hotkeys (U/D/C/Q)** | **64** | **Partial** |
| 1222-1240 | KeyboardInterrupt: close positions | 18 | Partial |
| **1242-1297** | **Session summary (calculation + print + log)** | **55** | **Yes** |
| 1305-1312 | Finally: cleanup (WS stop, terminal restore) | 7 | Partial |

### 3 Critical Duplicated Patterns

**Pattern A — Close positions (3 copies)**

Appears in: market transition (L863), emergency close (L1194), exit (L1231)
```python
for p in positions:
    token_id = token_up if p['direction'] == 'up' else token_down
    price = get_price(token_id, "SELL")
    pnl = (price - p['price']) * p['shares']
    session_pnl += pnl
    trade_count += 1
    trade_history.append(pnl)
    logger.log_trade("CLOSE", p['direction'], p['shares'], price, ...)
    balance += price * p['shares']
positions.clear()
```
Solution: `close_all_positions(positions, token_up, token_down, logger, reason)` → returns `(total_pnl, count, pnl_list)`

**Pattern B — Execute buy (3 copies)**

Appears in: signal buy (L1077), manual during opportunity (L1125), manual during sleep (L1160)
```python
info = execute_hotkey(client, direction, trade_amount, token_up, token_down)
if info:
    positions.append(info)
    balance -= info['price'] * info['shares']
    logger.log_trade("BUY", direction, info['shares'], info['price'], ...)
    last_action = f"BUY {direction.upper()} ...sh @ $..."
else:
    last_action = f"✗ BUY {direction.upper()} FAILED"
```
Solution: `handle_buy(client, direction, amount, reason, ...)` → returns `(info, last_action)`

**Pattern C — Call draw_panel (4 copies)**

Appears in: initial panel (L838), after signal (L956), emergency close before (L1183), emergency close after (L1209)
All with ~12 identical repeated parameters.
Solution: `PanelState` dataclass — update individual fields, pass single object

### 44 Local Variables

**Session (defined once):**
`trade_amount`, `logger`, `session_start`, `session_start_str`, `trade_history`, `client`, `limit`, `balance`, `event`, `market`, `token_up`, `token_down`, `time_remaining`, `market_slug`, `price_to_beat`, `binance_ws`, `ws_started`, `old_settings`, `fd`, `is_tty`

**Loop state (mutable each cycle):**
`last_beep`, `last_market_check`, `base_time`, `positions`, `current_signal`, `alert_active`, `alert_side`, `alert_price`, `session_pnl`, `trade_count`, `status_msg`, `status_clear_at`, `last_action`, `now`, `now_str`

**Temporary within loop (~30+):**
`ws_candles`, `data_source`, `bin_direction`, `confidence`, `details`, `btc_price`, `binance_data`, `current_regime`, `up_buy`, `down_buy`, `s_dir`, `strength`, `rsi_val`, `trend`, `sr_raw`, `sr_adj`, `col_*` (15 column variables), `blocks`, `bar`, `color`, `sym`, ...

### Refactoring Plan — Status

| Function to extract | Eliminates | Lines saved | Status |
|---------------------|------------|:-----------:|:------:|
| `close_all_positions()` | Pattern A (3x) | ~40 | ✅ `src/trade_executor.py` |
| `handle_buy()` | Pattern B (3x) | ~50 | ✅ `src/trade_executor.py` |
| `format_scrolling_line()` | Block 967-1055 | ~88 | ✅ `src/ui_panel.py` |
| `calculate_session_stats()` | Block 1242-1262 | ~30 | ✅ `src/session_stats.py` |
| `compute_signal()` | Signal engine | ~170 | ✅ `src/signal_engine.py` |
| `draw_panel()` | Static panel UI | ~180 | ✅ `src/ui_panel.py` |
| `detect_scenario()` | Scenario detection | ~55 | ✅ `src/signal_engine.py` |
| `execute_buy/close/monitor` | Trade execution | ~235 | ✅ `src/trade_executor.py` |
| `read_key/wait/sleep` | Input handling | ~55 | ✅ `src/input_handler.py` |
| `TradingSession` class | 17 local vars → class | — | ✅ `radar_poly.py` |
| `PanelState` dataclass | Pattern C (4x) | ~20 | ⬜ Pending |

Result: `radar_poly.py` dropped from **1,591 → 712 lines (-55%)**. `TradingSession` class encapsulates all mutable state. `main()` now delegates to 6 extracted modules.

---

## Detailed Analysis: Performance (Specialist C)

### 7 Performance Problems Identified

| # | Problem | Severity | Location | Impact |
|---|---------|----------|----------|--------|
| 1 | No `requests.Session()` | CRITICAL | binance_api.py, polymarket_api.py, radar_poly.py | +50-500ms per request (new TCP connection) |
| 2 | `get_price()` without cache | CRITICAL | radar_poly.py:117 | 2-10 duplicated requests/s in monitor_tp_sl() |
| 3 | ThreadPoolExecutor recreated each cycle | HIGH | radar_poly.py:1149 | 1800+ creations/hour |
| 4 | `monitor_tp_sl()` blocking I/O | HIGH | radar_poly.py:885 | Response time 1+s |
| 5 | 65+ sys.stdout.write() per redraw | MEDIUM | radar_poly.py:546-721 | 2200+ terminal ops/min |
| 6 | HTTP polling with active WebSocket | MEDIUM | binance_api.py:411 | Unnecessary HTTP for indicators |
| 7 | Unnecessary deque/list copies | LOW | radar_poly.py:165, ws_binance.py:108 | Minimal CPU/mem |

### Details

**1. HTTP Connection Reuse (CRITICAL)**
- Each `requests.get()` without Session opens a new TCP connection: handshake 50-100ms on fast network, 200-500ms on slow network
- `get_price()` called 2x per cycle (UP + DOWN), 0.5s cycle = 4 connections/second
- `check_limit()` makes 2 sequential requests in polymarket_api.py:254-269
- **Fix**: `session = requests.Session()` at module level, replace `requests.get()` → `session.get()`

**2. get_price() Without Cache (CRITICAL)**
- Called in: close_all_positions (per position), execute_buy_market (entry), execute_close_market (3x retry), monitor_tp_sl (every 0.5s), main loop (UP+DOWN)
- In `monitor_tp_sl()`: polling every 0.5s, each HTTP takes 100-500ms
- **Fix**: PriceCache with 0.5s TTL to avoid duplicates within the same cycle

**3. ThreadPoolExecutor (HIGH)**
- Line 1149: `with ThreadPoolExecutor(max_workers=2) as pool:` inside the loop
- Pool creation includes: thread allocation, state initialization, locks
- With 0.5s cycle: ~7200 creations/destructions per hour
- **Fix**: Persistent pool at module level, `executor.shutdown()` in finally

**4. monitor_tp_sl() Blocking (HIGH)**
- `get_price()` blocks for 100-500ms → actual cycle is 1+s instead of 0.5s
- Key checking happens AFTER the fetch (not concurrent)
- **Fix**: Asynchronous fetch + concurrent key checking via ThreadPoolExecutor

**5. Terminal Rendering (MEDIUM)**
- `draw_panel()` makes 66+ individual `sys.stdout.write()` calls per redraw
- Each `flush()` triggers I/O to the terminal
- 33+ redraws/min × 66 ops = 2200+ terminal operations/minute
- **Fix**: Accumulate in `io.StringIO()`, single `write()` + `flush()`

### Implementation Status

| # | Fix | Status |
|---|-----|--------|
| 1 | Persistent requests.Session() | ✅ Implemented |
| 2 | PriceCache with TTL | ✅ Implemented |
| 3 | Persistent ThreadPoolExecutor | ✅ Implemented |
| 4 | Concurrent monitor_tp_sl() | ✅ Implemented |
| 5 | Batch terminal writes (StringIO) | ✅ Implemented |
| 6 | Optimize polling with active WS | ⬜ Pending (requires further analysis) |
| 7 | Eliminate deque copies | ✅ Implemented |

**Combined estimate: 60-70% reduction in network latency, 40-50% reduction in CPU overhead.**

---

## UI Improvements Already Implemented (current session)

- ✅ Color on scrolling column RSI (green < 40, red > 60)
- ✅ Color on scrolling strength bar
- ✅ Color on SIGNAL line indicators (RSI, Trend, MACD, VWAP, BB)
- ✅ ALERT color (green UP, red DOWN)
- ✅ S/R color (green positive, red negative)
- ✅ BB color fixed (green > 80%, red < 20%)
- ✅ BB column alignment (fixed width 6 chars)
- ✅ RSI header alignment (7 chars)
- ✅ RG column renamed to REGIME
- ✅ ACTION line on static panel (trades without polluting scrolling)
- ✅ Silent `execute_hotkey()` (quiet=True)
- ✅ C key works during TP/SL monitoring
- ✅ Market transition calculates real P&L (fetch SELL price)
- ✅ Session summary on exit (clear + print)
- ✅ Virtual environment not activated warning
- ✅ WS auto-recovery in main loop
- ✅ WebSocket instead of WS on BINANCE line
- ✅ Donation banner with 20s countdown
- ✅ WR/PF displayed on POSITION line

---

## Suggested Implementation Order

### Sprint 1 — Risk & Execution (Phase 4 complete)
1. Dynamic TP/SL with ATR (#2)
2. TP/SL non-blocking (#1)
3. Trailing stop (#5)
4. Timeout on monitor_tp_sl (#9)

### Sprint 2 — Reliability
5. Market expiry real close (#3)
6. Re-sync balance (#4) ✅
7. Persistent requests.Session() (#6) ✅
8. Persistent ThreadPoolExecutor (#7) ✅

### Sprint 3 — Refactoring ✅
9. Extract handle_buy/handle_close (#8) ✅
10. Extract format_scrolling_line (#12) ✅
11. PanelState dataclass (#11) — ⬜ Pending
12. TradingSession class ✅ — encapsulates 17 mutable state variables
13. Module extraction ✅ — 6 new modules: signal_engine, ui_panel, trade_executor, input_handler, session_stats, colors
14. Exponential backoff on API failures ✅ — Binance errors, market refresh, market slug lookup

### Sprint 4 — Multi-Market (Phase 8) ✅
12. MarketConfig + parameterization (#10) ✅

### Sprint 5 — Polish
13. History gap protection (#13)
14. Connection pooling (#14)
15. VWAP reclaim detection (#15)
16. Market transition handling (#16)

---

## Trading Specialist Analysis — Signal, Execution and Risk Improvements

**Date:** 2026-02-22
**Context:** Deep analysis of the system from the perspective of a specialist trader in updown crypto markets on Polymarket. Focus on problems that directly affect P&L.

---

### CRITICAL — Directly affect P&L

#### T1. Price-to-Beat as a signal component
- **Problem**: The Price to Beat (BTC price at the start of the window) is the most important metric in an updown market — it defines the outcome (BTC above = UP wins, below = DOWN wins). However `compute_signal()` **completely ignores** this information. The signal uses generic RSI/MACD/VWAP without considering the reference that defines the market outcome.
- **Example**: If BTC is $500 above the beat price with 3 minutes remaining, the probability of UP is very high. But the signal might say DOWN if RSI is overbought and MACD crosses downward — a severe false negative.
- **Solution**: New component `beat_distance_score`:
  ```python
  beat_diff_pct = (btc_price - price_to_beat) / price_to_beat * 100
  # Scale: each 0.1% difference = ~10 confidence points
  beat_score = max(-1.0, min(1.0, beat_diff_pct / 0.3))
  ```
  Dynamic weight by phase:
  - EARLY: 10% (BTC can reverse, low predictive value)
  - MID: 25% (trend is established, moderate weight)
  - LATE: 50% (almost deterministic, dominates the signal)
- **Impact**: HIGH — this is the most predictive information for the final outcome
- **Effort**: Low
- **Files**: `radar_poly.py` — `compute_signal()` receives `price_to_beat` and `phase` as parameters

#### T2. Risk/reward filter at price extremes
- **Problem**: When UP=$0.92, buying UP yields at most $0.08 (8.7% upside) but can lose $0.91 (98.9% downside). The risk/reward is 1:11 — catastrophic. The script does not prevent this buy. Similarly, buying DOWN at $0.05 has $0.94 upside but very low probability.
- **Concrete example**: Trader sees UP 75% signal, presses S. The token is at $0.93. Buys 43 shares at $0.93 = $40. If it resolves UP, gains $3. If it resolves DOWN, loses $40.
- **Solution**: Block or alert when the entry token exceeds threshold:
  ```python
  MAX_ENTRY_PRICE = 0.85  # Don't buy above 85 cents
  MIN_ENTRY_PRICE = 0.08  # Don't buy below 8 cents (very low probability)
  ```
  When blocked, show in ALERT: `BLOCKED: UP@$0.93 — risk/reward 1:11 (max $0.07 / risk $0.93)`
- **Impact**: HIGH — prevents the worst possible losses (near-total trade loss)
- **Effort**: Low (5-10 lines)
- **Files**: `radar_poly.py` — inside the detected opportunity block and in `handle_buy()`

#### T3. Enforce check_limit() before each buy
- **Problem**: The `check_limit()` function exists in `polymarket_api.py:246` and calculates total exposure (positions + open orders) vs POSITION_LIMIT. But it is **never called** in the trade flow: `handle_buy()` → `execute_hotkey()` → `execute_buy_market()` proceeds without checking. The user can accumulate unlimited exposure.
- **Example**: POSITION_LIMIT=76 in .env. Trader buys 10x of $10 = $100 exposure. No blocking.
- **Solution**: Call `check_limit()` at the beginning of `handle_buy()`:
  ```python
  can_trade, exposure, limit = check_limit(client, token_up, token_down, trade_amount)
  if not can_trade:
      last_action = f"BLOCKED: exposure ${exposure:.0f}/${limit:.0f}"
      return None, balance, last_action
  ```
- **Impact**: HIGH — fundamental risk control that already exists but is not connected
- **Effort**: Low (10 lines)
- **Files**: `radar_poly.py` — `handle_buy()` + pass `client, token_up, token_down` as args

#### T4. Auto-close before market expiration
- **Problem**: Market refresh happens every 60s (`last_market_check`). If the last check was at T-80s, positions might not close before market resolution. Updown tokens resolve automatically: those who were right receive $1, those who were wrong receive $0. If the trader has the right position, they might miss the opportunity to sell at $0.95 before resolution (since the market resolves at $1.00, but without liquidity in the last seconds).
- **Real risk**: If on the wrong side, the token goes to $0.00 — total loss. And in the last 30-60 seconds, the orderbook spread widens significantly, making the close difficult.
- **Solution**: Hard cutoff at T-45s (configurable via .env `AUTO_CLOSE_SECONDS=45`):
  ```python
  if current_time <= 0.75 and positions:  # 45 seconds
      status_msg = "AUTO-CLOSE: market expiring"
      execute_close_market(client, token_up, token_down)
      close_all_positions(...)
  ```
- **Impact**: HIGH — prevents total loss from resolution on the wrong side
- **Effort**: Low (15 lines)
- **Files**: `radar_poly.py` — in main loop, before the data collection block

#### T5. TP/SL proportional to entry price and time remaining
- **Problem**: Current TP/SL is fixed: `spread = 0.05 + (strength/100)*0.10`, `sl = entry - 0.06`. This does not consider:
  1. **Entry price**: SL of $0.06 on a $0.90 token is 6.6% risk, but on a $0.20 token is 30%.
  2. **Time remaining**: With 10min remaining, TP of +$0.15 is achievable. With 1min, it's impossible.
  3. **Volatility**: In a volatile market, tight SL = stopped out by noise. In a calm market, wide SL = unnecessary loss.
- **Solution**: Adaptive TP/SL based on ATR + time + entry:
  ```python
  atr = binance_data.get('atr', 0)
  atr_pct = atr / btc_price if btc_price > 0 else 0.001
  time_factor = min(current_time / 10, 1.0)  # decreases with time

  # Based on ATR, adjusted by time remaining
  tp_spread = max(0.03, atr_pct * 50 * time_factor)
  sl_spread = max(0.02, atr_pct * 30 * time_factor)

  # Limit by entry price (SL cannot exceed 50% of entry)
  sl_spread = min(sl_spread, entry * 0.20)

  tp = min(entry + tp_spread, 0.95)
  sl = max(entry - sl_spread, 0.03)
  ```
- **Impact**: HIGH — TP/SL responsive to actual market conditions
- **Effort**: Medium
- **Files**: `radar_poly.py` — `compute_signal()` (suggestion) + `monitor_tp_sl()`

---

### HIGH — Signal Quality

#### T6. Non-blocking TP/SL (already in backlog as #1, trading detail)
- **Additional trading problem**: While `monitor_tp_sl()` blocks, the market can change windows (15min have passed), the regime can switch from TREND to CHOP, and new opportunities are missed. Worse: if the market expires during monitoring, the P&L may not be calculated correctly.
- **Trading solution**: In the main loop, maintain `active_tp_sl = {'token_id': ..., 'tp': ..., 'sl': ..., 'entry': ...}`. Each cycle:
  1. Fetch price of the monitored token
  2. Check TP/SL/Trailing
  3. Display progress bar on ACTION line
  4. Allow hotkey C to cancel
  5. If TP/SL hit, execute close automatically
- **Impact**: HIGH — trader maintains full market view during open position
- **Effort**: Medium-High
- **Files**: `radar_poly.py` — replace `monitor_tp_sl()` with state machine in loop

#### T7. Session max-loss circuit breaker
- **Problem**: If the trader loses 5 consecutive trades ($30 loss on a $76 account), the system continues operating normally. Without a per-session loss limit, a bad day can decimate the entire account.
- **Solution**: New .env variable `MAX_SESSION_LOSS=20` (default $20). When `session_pnl <= -MAX_SESSION_LOSS`:
  - Automatically close all positions
  - Disable trading (ignore hotkeys U/D/S)
  - Show on STATUS line: `CIRCUIT BREAKER: session loss $-20.00 (limit: $20)`
  - Continue displaying the radar (monitoring) but without executing trades
  - Hotkey R to reset the breaker (requires confirmation)
- **Impact**: MEDIUM-HIGH — essential protection against bad days
- **Effort**: Low (20 lines)
- **Files**: `radar_poly.py` — check in `handle_buy()` + new .env variable

#### T8. Cooldown after loss
- **Problem**: After a loss, the trader (and the system) can immediately enter a new trade. In real trading, this leads to "revenge trading" — emotional trades that accumulate more losses. The signal may be correct but the market condition that caused the loss still persists.
- **Solution**: Configurable cooldown after loss: `COOLDOWN_AFTER_LOSS=30` (seconds). After closing a position with negative P&L:
  ```python
  if pnl < 0:
      cooldown_until = time.time() + COOLDOWN_AFTER_LOSS
  ```
  During cooldown:
  - Signals continue to be calculated and displayed
  - Opportunities are detected but **do not offer prompt** (S/U/D ignored)
  - STATUS line shows: `COOLDOWN: 25s remaining (last trade: -$1.50)`
- **Impact**: MEDIUM — prevents accumulation of consecutive losses
- **Effort**: Low (15 lines)
- **Files**: `radar_poly.py` — variable `cooldown_until`, check in the opportunity block

---

### MEDIUM — Signal Refinement

#### T9. Dynamic weights by temporal phase
- **Problem**: The 6 signal weights (Momentum 30%, Divergence 20%, S/R 10%, MACD 15%, VWAP 15%, BB 10%) are fixed. But the usefulness of each indicator changes drastically throughout the window:
  - **EARLY** (>66%): Momentum/MACD are informative (trend forming), but Price-to-Beat has low predictive value (BTC can reverse multiple times)
  - **MID** (33-66%): All indicators have similar value
  - **LATE** (<33%): The BTC vs Beat distance is almost deterministic. RSI oversold is irrelevant if BTC is $300 above beat with 2 minutes remaining
- **Solution**: Weight table by phase:
  ```
  Component          EARLY   MID    LATE
  ─────────────────────────────────────
  Beat Distance      10%    25%    50%
  Momentum           30%    20%    10%
  Divergence         20%    15%     5%
  MACD               15%    15%    10%
  VWAP               15%    15%    10%
  S/R                 5%     5%    10%
  Bollinger           5%     5%     5%
  ```
- **Impact**: MEDIUM — better calibrated signal for each moment of the window
- **Effort**: Medium (weight table + refactor compute_signal)
- **Files**: `radar_poly.py` — `compute_signal()` receives `phase` and adjusts weights

#### T10. Normalize indicator thresholds by price
- **Problem**: Several indicators use thresholds in absolute dollar values:
  - MACD: `abs(macd_hist_delta) > 0.5` (line 266) — $0.50 in BTC at $98k is 0.0005%, irrelevant. At $20k it would be 0.0025%, more significant.
  - VWAP: `vwap_pos > 0.02` (line 283) — 0.02% is ~$20 in BTC at $98k. Too small to be significant.
  - ATR-based vol threshold: `VOL_THRESHOLD=0.03` (3%) is reasonable but static.
- **Solution**: Normalize by current price. For MACD:
  ```python
  macd_delta_pct = macd_hist_delta / btc_price * 100  # in percentage
  if abs(macd_delta_pct) > 0.0005: macd_score = 1.0 if macd_delta_pct > 0 else -1.0
  ```
  For VWAP: increase threshold to `0.05` (0.05% = ~$50 in BTC at $98k).
- **Impact**: MEDIUM — reduces false signals from miscalibrated thresholds
- **Effort**: Low (adjust 3-4 comparisons)
- **Files**: `radar_poly.py` — `compute_signal()` components 4 (MACD) and 5 (VWAP)

#### T11. Recover existing positions on startup ✅
- **Problem**: `positions = []` is initialized empty at the start of main(). If the script crashes and restarts, it doesn't know about existing positions in the UP/DOWN tokens. The trader may have shares that don't appear on the panel, and the session P&L starts wrong.
- **Solution**: `sync_positions()` in `src/trade_executor.py` queries `get_token_position()` for both UP/DOWN tokens, compares with local tracking, and adds/removes positions accordingly.
- **Impact**: MEDIUM — resilience to crashes + correct information on panel
- **Effort**: Low
- **Files**: `src/trade_executor.py` — `sync_positions()`, `radar_poly.py` — startup + periodic sync
- **Status**: ✅ Implemented — `sync_positions()` called on startup (detects existing positions) and every 60s in the market refresh block (detects buys/sells made directly on Polymarket's web interface). Balance also re-synced via `get_balance()` on each refresh.

#### T12. Longer Divergence lookback
- **Problem**: The Divergence component (BTC vs Polymarket price) looks at only 6 past cycles (~12 seconds with 2s cycle, ~3s with WS). In crypto, 12-second movements are pure noise — any micro-fluctuation generates false "divergence".
- **Solution**: Increase lookback to 30-60 cycles (~1-2 minutes). With more history, the detected divergence is more significant:
  ```python
  DIVERGENCE_LOOKBACK = 30  # cycles (~60s with 2s cycle, ~15s with WS 0.5s)
  if len(history) >= DIVERGENCE_LOOKBACK:
      h_old = history[-DIVERGENCE_LOOKBACK]
      h_new = history[-1]
      ...
  ```
  Additionally, consider using the **average** of the last 5 old points vs last 5 recent points to smooth noise.
- **Impact**: MEDIUM — reduces false divergences
- **Effort**: Low (change 1 constant + optional smoothing)
- **Files**: `radar_poly.py` — `compute_signal()` component 2 (Divergence)

#### T13. S/R at BTC levels (not Polymarket token)
- **Problem**: The current S/R component calculates support/resistance on UP token prices (values between $0.01-$0.99). This reflects what the **market has already priced in**, not what will happen. The true driver is the BTC price — if BTC is testing support at $68,000, that's new information that the Polymarket market may not have priced in yet.
- **Solution**: Calculate S/R using BTC prices from Binance candles:
  ```python
  btc_prices = [c['high'] for c in candles[-20:]] + [c['low'] for c in candles[-20:]]
  btc_high = max(btc_prices)
  btc_low = min(btc_prices)
  btc_range = btc_high - btc_low

  # Current price position in the recent range
  if btc_range > 0:
      btc_pos = (btc_price - btc_low) / btc_range
      if btc_pos < 0.15: sr_score = 0.8    # near support = UP
      elif btc_pos > 0.85: sr_score = -0.8  # near resistance = DOWN
  ```
  Bonus: detect round numbers ($68,000, $68,500, etc.) as psychological support/resistance:
  ```python
  round_500 = round(btc_price / 500) * 500
  dist_to_round = abs(btc_price - round_500) / btc_price
  if dist_to_round < 0.001:  # within 0.1% of a round number
      sr_score *= 1.2  # amplify S/R signal
  ```
- **Impact**: MEDIUM — S/R on BTC is more predictive than on token price
- **Effort**: Medium (rewrite S/R component)
- **Files**: `radar_poly.py` — `compute_signal()` component 3, or `binance_api.py` new function `compute_sr_levels(candles)`

---

### LOW — Refinements

#### T14. Volume as confidence multiplier
- **Problem**: Binance volume is calculated (`vol_up`, `vol_down` in `analyze_trend()`) but only used for display (HIGH/normal flag). A bullish signal without buying volume is much less reliable — it may just be a fluctuation due to lack of liquidity.
- **Solution**: Use volume ratio as multiplier of the final score:
  ```python
  vol_ratio = vol_up / (vol_up + vol_down) if (vol_up + vol_down) > 0 else 0.5
  # If volume confirms direction, boost. If contradicts, dampen.
  if score > 0 and vol_ratio > 0.60:
      score *= 1.15  # volume confirms bullish
  elif score > 0 and vol_ratio < 0.40:
      score *= 0.75  # volume contradicts bullish
  elif score < 0 and vol_ratio < 0.40:
      score *= 1.15  # volume confirms bearish
  elif score < 0 and vol_ratio > 0.60:
      score *= 0.75  # volume contradicts bearish
  ```
- **Impact**: LOW-MEDIUM — incremental false signal filter
- **Effort**: Low (10 lines)
- **Files**: `radar_poly.py` — `compute_signal()` after final score, before regime adjustment

#### T15. Spread monitoring (orderbook bid-ask)
- **Problem**: The script fetches only best BUY and best SELL price. It doesn't show the spread (difference between bid and ask). Wide spread = low liquidity = higher entry/exit cost = higher effective slippage. On tokens with $0.10 spread, a $4 trade already has $0.40 implicit cost (10%).
- **Solution**: Calculate and display spread on the POLY line:
  ```python
  up_sell = get_price(token_up, "SELL")
  spread_up = up_buy - up_sell
  # POLY │ UP: $0.55/$0.45 (55%) spread:$0.03 │ DOWN: ...
  ```
  Additionally, use spread as filter: if `spread > 0.08`, alert that transaction cost is high.
- **Impact**: LOW — useful information for manual decision, liquidity filter
- **Effort**: Medium (additional fetch + display + filter)
- **Files**: `radar_poly.py` — `draw_panel()` POLY line, `compute_signal()` as filter

---

## Implementation Order — Trading Improvements

### Sprint T1 — Capital Protection (Impact: prevent avoidable losses)
1. Enforce check_limit() (T3) — Low effort, immediate impact
2. Risk/reward extremes filter (T2) — Low effort, prevents worst losses
3. Auto-close before expiration (T4) — Low effort, prevents total loss
4. Session max-loss circuit breaker (T7) — Low effort, session protection

### Sprint T2 — Signal Quality (Impact: improve decisions)
5. Price-to-Beat in signal (T1) — The most predictive information for the outcome
6. Proportional TP/SL (T5) — Adaptive risk management
7. Post-loss cooldown (T8) — Prevent revenge trading

### Sprint T3 — Refinement (Impact: better calibrated signals)
8. Dynamic weights by phase (T9) — Signal adapts to temporal window
9. Normalize thresholds (T10) — Reduces false signals
10. Longer Divergence lookback (T12) — More significant divergence

### Sprint T4 — Advanced Execution
11. Non-blocking TP/SL (T6) — Full view during position
12. Recover positions on startup (T11) — Resilience ✅
13. S/R at BTC levels (T13) — More predictive S/R
14. Volume as multiplier (T14) — Signal confirmation
15. Spread monitoring (T15) — Liquidity information

---

## Python Best Practices Analysis — Senior Code Review

**Date:** 2026-02-22
**Branch:** feature/melhores_praticas
**Scope:** All 6 project files

---

### CRITICAL

#### P1. Bare `except Exception: pass` in 8+ locations
- **Problem**: Exceptions are silently swallowed in `radar_poly.py` (lines 147, 370, 393, 955, 1241, 1273), `polymarket_api.py` (lines 60, 114, 241), `ws_binance.py` (line 233), `logger.py` (lines 120, 137, 164). Network, parsing and API errors go unnoticed — impossible to diagnose failures.
- **Solution**: Replace with specific exceptions (`requests.RequestException`, `ValueError`, `KeyError`, `json.JSONDecodeError`) with logging via `logging` module.
- **Files**: All 6 files
- **Status**: ⬜ Pending

#### P2. Private key in `.env` without protection
- **Problem**: `POLYMARKET_API_KEY` is in `.env` without rotation or encryption. If `.env` leaks, funds are compromised.
- **Solution**: Verify `.gitignore` includes `.env`, add warning in `.env.example`, document use of secrets manager for production.
- **Files**: `polymarket_api.py`, `.env.example`
- **Status**: ⬜ Pending (mitigation — `.env` is already in `.gitignore`)

---

### HIGH

#### P3. PriceCache caches errors as 0.0
- **Problem**: `PriceCache.get()` returns 0.0 on network failure and caches for 0.5s. Delays real price detection and can generate incorrect decisions.
- **Solution**: Don't cache when response is an error. Distinguish real 0.0 from failure.
- **Files**: `radar_poly.py` — class `PriceCache`
- **Status**: ⬜ Pending

#### P4. ThreadPoolExecutor `shutdown(wait=False)`
- **Problem**: During cleanup, trades in execution may be cancelled mid-operation.
- **Solution**: Use `wait=True` or ensure futures complete before shutdown.
- **Files**: `radar_poly.py` — finally block
- **Status**: ⬜ Pending

#### P5. Blocking I/O on main thread
- **Problem**: `get_full_analysis()` is a blocking HTTP call on the main thread. If API takes 5-10s, the entire UI freezes.
- **Solution**: Move to executor with timeout.
- **Files**: `radar_poly.py` — main loop
- **Status**: ⬜ Pending

#### P6. Race condition on WebSocket restart
- **Problem**: `ws_binance.py` checks `_thread.is_alive()` and creates new thread outside the lock. Thread can die between check and start.
- **Solution**: Protect with lock.
- **Files**: `ws_binance.py`
- **Status**: ⬜ Pending

#### P7. Silent exceptions in `polymarket_api.py`
- **Problem**: `get_balance()`, `get_open_orders_value()`, `get_price_at_timestamp()` silently swallow exceptions.
- **Solution**: Specific catch + logging.
- **Files**: `polymarket_api.py`
- **Status**: ⬜ Pending

#### P8. Main loop with 300+ lines ✅
- **Problem**: Impossible to unit test. Mixes data fetching, signal computation, UI, trade execution, hotkeys.
- **Solution**: Extract `fetch_market_data()`, `process_signal()`, `handle_input()`, `update_ui()`.
- **Files**: `radar_poly.py`, `src/signal_engine.py`, `src/ui_panel.py`, `src/trade_executor.py`, `src/input_handler.py`, `src/session_stats.py`
- **Status**: ✅ Implemented — 6 modules extracted, `TradingSession` class added, `radar_poly.py` reduced from 1,591 to 712 lines

---

### MEDIUM

#### P9. `compute_signal()` mutates global state ✅
- **Problem**: `history.append()` inside a function that should be pure. Hidden side-effect makes function untestable.
- **Solution**: Return data for append externally, or move append to the caller.
- **Files**: `src/signal_engine.py`
- **Status**: ✅ Implemented — `history` is now a parameter of `compute_signal()`, not a global. Append happens in `main()` before calling the function.

#### P10. Magic numbers without named constants ✅
- **Problem**: Values like `0.02`, `0.05`, `0.06`, `5`, `30`, `999`, `0.99` scattered without explanation.
- **Solution**: Create constants with descriptive names at the top of the file.
- **Files**: `src/signal_engine.py`, `src/trade_executor.py`
- **Status**: ✅ Implemented — all magic numbers extracted as named constants in their respective modules

#### P11. Unprotected division by zero
- **Problem**: `time_remaining / window_min` (line 178), `gw / gl` (line 720) can cause crash.
- **Solution**: Add guards `if x > 0` or use safe division.
- **Files**: `radar_poly.py`
- **Status**: ⬜ Pending

#### P12. No type hints on public functions
- **Problem**: All main functions without type annotations. IDE and analysis tools cannot validate.
- **Solution**: Add type hints for parameters and returns.
- **Files**: All 6 files
- **Status**: ⬜ Pending

#### P13. Incorrectly positioned docstrings in `binance_api.py`
- **Problem**: In 5+ functions, docstring appears after code (if/validation) instead of at the beginning of the function.
- **Solution**: Move docstrings to right after `def`.
- **Files**: `binance_api.py`
- **Status**: ⬜ Pending

#### P14. Timezone naive in `polymarket_api.py`
- **Problem**: `datetime.now()` without timezone on line 153. If server changes TZ, breaks silently.
- **Solution**: Use `datetime.now(BRASILIA)` explicitly.
- **Files**: `polymarket_api.py`
- **Status**: ⬜ Pending

#### P15. Retry without backoff in `find_current_market()` ✅
- **Problem**: 4 slug attempts without delay between requests. Can cause rate limiting.
- **Solution**: Add increasing sleep between attempts.
- **Files**: `src/polymarket_api.py`
- **Status**: ✅ Implemented — exponential backoff: `0.2 * 2^i` (0.2s, 0.4s, 0.8s, 1.6s), capped at 2.0s

#### P16. File handles without context manager in `logger.py`
- **Problem**: Files opened with `open()` without `with` statement. If exception occurs, file descriptor leaks.
- **Solution**: Refactor to use context managers or ensure close in finally.
- **Files**: `logger.py`
- **Status**: ⬜ Pending

#### P17. Duplicated position logic
- **Problem**: Position aggregation appears in `format_scrolling_line()` and `draw_panel()`.
- **Solution**: Extract to `aggregate_positions()` function.
- **Files**: `src/ui_panel.py`
- **Status**: ⬜ Pending

#### P18. Thread safety on WebSocket `_current`
- **Problem**: `get_candles()` reads `_current` outside the lock in some paths.
- **Solution**: Always read candle state inside the lock.
- **Files**: `ws_binance.py`
- **Status**: ⬜ Pending

---

### LOW

#### P19. `list(history)[-20:]` creates unnecessary copy
- **Problem**: Allocation every 0.5-2s cycle.
- **Solution**: Use `itertools.islice` or iterate directly.
- **Files**: `radar_poly.py`
- **Status**: ⬜ Pending

#### P20. `shutil.get_terminal_size()` called without cache
- **Problem**: Syscall on every panel redraw.
- **Solution**: Cache and update with SIGWINCH.
- **Files**: `radar_poly.py`
- **Status**: ⬜ Pending

#### P21. Print used for logging instead of `logging` module
- **Problem**: `print()` for errors mixes with UI output. Impossible to filter by severity.
- **Solution**: Use `logging.warning()`, `logging.error()` for internal errors.
- **Files**: `radar_poly.py`
- **Status**: ⬜ Pending

#### P22. `_ema_list` defined inside `compute_macd()` on each call
- **Problem**: Inner function recreated on each invocation.
- **Solution**: Move to module level.
- **Files**: `binance_api.py`
- **Status**: ⬜ Pending

#### P23. Circular import in `polymarket_api.py`
- **Problem**: `from market_config import MarketConfig` inside function (line 146).
- **Solution**: Move to top of file.
- **Files**: `polymarket_api.py`
- **Status**: ⬜ Pending

---

### Implementation Order — Best Practices

#### Sprint P1 — Error Handling (Impact: stability)
1. Replace bare excepts with specific exceptions (P1)
2. Don't cache errors in PriceCache (P3)
3. Fix silent exceptions in polymarket_api/ws_binance (P6, P7)
4. Protect divisions by zero (P11)

#### Sprint P2 — Concurrency & Safety (Impact: reliability)
5. Correct ThreadPoolExecutor shutdown (P4)
6. Blocking I/O with timeout on main thread (P5)
7. Race condition on WS restart (P6)
8. Thread safety on `_current` (P18)

#### Sprint P3 — Code Quality (Impact: maintainability)
9. Magic numbers → named constants (P10) ✅
10. compute_signal() without side effects (P9) ✅
11. Type hints on public functions (P12)
12. Correct docstrings in binance_api.py (P13)

#### Sprint P4 — Minor Fixes
13. Explicit timezone (P14)
14. Retry with backoff (P15) ✅
15. Logger file handles (P16)
16. Performance: cache terminal size, deque slicing (P19, P20)
17. Circular import (P23)
