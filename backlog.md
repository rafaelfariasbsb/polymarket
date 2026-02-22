# Backlog de Melhorias — Polymarket BTC Scalping Radar

Documento gerado a partir da análise de 3 especialistas (Arquitetura, Trading, Performance) sobre o `radar_poly.py`.

**Data:** 2026-02-22
**Branch:** develop
**Último commit:** 2147539

---

## Status das Fases do Plano Original

| Fase | Descrição | Status |
|------|-----------|--------|
| 1 | Logging & Backtesting | ✅ Completa |
| 2 | Novos Indicadores (MACD, VWAP, BB) | ✅ Completa |
| 3 | Market Regime Detection | ✅ Completa |
| 4 | TP/SL Dinâmico & Trailing Stop | ⬜ Pendente |
| 5 | Session Win Rate & Performance Stats | ✅ Completa |
| 6 | WebSocket Real-Time Data | ✅ Completa |
| 7 | Melhorias Menores | ⬜ Parcial |
| 8 | Multi-Market Support | ✅ Completa |

---

## Melhorias Identificadas — Análise dos 3 Especialistas

### PRIORIDADE ALTA

#### 1. TP/SL Non-Blocking (Fase 4)
- **Problema**: `monitor_tp_sl()` é um loop bloqueante — enquanto monitora TP/SL, o radar para de atualizar, o painel estático congela, e o scrolling log não recebe novos dados.
- **Solução**: Integrar checagem de TP/SL no ciclo principal (`while True`). A cada ciclo (0.5s), verificar se preço atingiu TP ou SL. Manter progress bar na linha ACTION do painel estático.
- **Impacto**: Alto — experiência do usuário e responsividade
- **Esforço**: Médio
- **Arquivos**: `radar_poly.py` — refatorar `monitor_tp_sl()` para state-based em vez de loop

#### 2. TP/SL Dinâmico com ATR (Fase 4)
- **Problema**: Stop loss fixo de `$0.06` e TP baseado em spread fixo (`0.05 + strength * 0.10`). Num mercado volátil, SL é apertado demais (stopado por ruído); num mercado calmo, é largo demais (perde muito quando erra).
- **Solução**: Usar ATR (já disponível em `binance_data['atr']`) para calcular TP/SL dinâmico:
  - `TP = entry + ATR * 1.5`
  - `SL = entry - ATR * 1.0`
  - Risk:Reward ratio mínimo de 1.5:1
- **Impacto**: Alto — gestão de risco
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py` — linhas 308-311 (`suggestion` dict)

#### 3. Market Expiry — Executar Close Real
- **Problema**: Na transição de mercado (linha 860-877), o código calcula P&L teórico via `get_price(token_id, "SELL")` mas **não executa** `execute_close_market()`. Os tokens ficam na carteira do usuário sem serem vendidos.
- **Solução**: Chamar `execute_close_market()` antes de calcular P&L na transição. Se a venda falhar, avisar o usuário.
- **Impacto**: Alto — dinheiro real pode ficar preso em tokens expirados
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py` — bloco de market transition (~linha 860)

#### 4. Re-sync Balance Periodicamente
- **Problema**: `balance` é definido uma vez no início (`get_balance(client)`) e depois decrementado/incrementado manualmente a cada trade. Com o tempo, diverge do saldo real por causa de arredondamentos, taxas, e ordens parcialmente preenchidas.
- **Solução**: Chamar `get_balance(client)` a cada 60s (junto com o market refresh) para corrigir o drift.
- **Impacto**: Médio — informação incorreta no painel
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py` — dentro do bloco `if now - last_market_check > 60`

---

### PRIORIDADE MÉDIA

#### 5. Trailing Stop (Fase 4)
- **Problema**: Uma vez definidos, TP e SL são fixos. Se o preço vai 80% do caminho para o TP e depois volta, o trade pode terminar em SL (-100% do risco).
- **Solução**: Trailing stop com 3 níveis:
  - Preço atinge 50% do TP → mover SL para breakeven (entry)
  - Preço atinge 75% do TP → mover SL para 50% do lucro
  - Exibir trailing SL atualizado na progress bar
- **Impacto**: Médio — protege lucro parcial
- **Esforço**: Médio
- **Arquivos**: `radar_poly.py` — `monitor_tp_sl()` (ou nova lógica non-blocking)

#### 6. `requests.Session()` Persistente (Fase 7) ✅
- **Problema**: `get_price()` cria uma nova conexão HTTP a cada chamada (`requests.get()`). Com 2+ chamadas por ciclo (UP + DOWN), são ~4 conexões TCP novas por segundo no modo WebSocket.
- **Solução**: Criar `requests.Session()` global ou por módulo para reutilizar conexões HTTP via keep-alive.
- **Impacto**: CRITICAL — cada requests.get() abre nova conexão TCP (+50-500ms por request)
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py` (`get_price()`), `binance_api.py`, `polymarket_api.py`
- **Status**: ✅ Implementado — sessions globais em todos os 3 módulos

#### 7. ThreadPoolExecutor Persistente ✅
- **Problema**: `ThreadPoolExecutor(max_workers=2)` é criado e destruído a cada ciclo (linha 1149). No modo WebSocket (~2 ciclos/s), são 1800+ criações/destruições por hora.
- **Solução**: Criar o pool uma vez no nível do módulo e reutilizá-lo.
- **Impacto**: HIGH — overhead de criação/destruição de threads a cada 0.5-2s
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py` — mover `ThreadPoolExecutor` para nível do módulo
- **Status**: ✅ Implementado — pool persistente com shutdown no finally

#### 8. Extrair Funções `handle_buy()` e `handle_close()` (DRY)
- **Problema**: A lógica de compra está duplicada em 3 locais:
  1. Linhas 1075-1120 — signal buy (durante oportunidade, com TP/SL)
  2. Linhas 1123-1134 — manual buy durante oportunidade (U/D)
  3. Linhas 1159-1178 — manual buy durante sleep cycle (U/D)
  Cada local repete: `execute_hotkey()` + `last_action` + `positions.append()` + `balance -=` + `logger.log_trade()`. Qualquer mudança precisa ser feita em 3 lugares.
- **Solução**: Criar `handle_buy(client, direction, amount, reason, ...)` que encapsula toda a lógica de compra. Idem `handle_close()` para os 3 locais de fechamento (emergency, TP/SL, market expiry, exit).
- **Impacto**: Médio — reduz bugs de inconsistência, facilita manutenção
- **Esforço**: Médio
- **Arquivos**: `radar_poly.py` — novas funções + refatorar chamadas

#### 9. Timeout no `monitor_tp_sl()`
- **Problema**: O `monitor_tp_sl()` roda indefinidamente até TP, SL, ou cancelamento manual (C). Se o preço ficar parado na zona neutra por 15+ minutos, o mercado pode mudar e o usuário fica preso num loop sem atualização.
- **Solução**: Adicionar `timeout_sec` (default 600s / 10min). Se exceder, retornar `('TIMEOUT', current_price)`.
- **Impacto**: Baixo — edge case, mas perigoso
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py` — `monitor_tp_sl()`

#### 10. Multi-Market Support (Fase 8) ✅
- **Problema**: Todo o sistema estava hardcoded para `btc-updown-15m`. 30+ referências em 4 arquivos.
- **Solução**: Novo `market_config.py` com classe `MarketConfig` que centraliza configuração derivada de `MARKET_ASSET` e `MARKET_WINDOW` (.env).
- **Impacto**: Alto — permite operar BTC, ETH, SOL, XRP em janelas de 5min e 15min
- **Esforço**: Alto
- **Arquivos**: `market_config.py` (novo), `polymarket_api.py`, `binance_api.py`, `ws_binance.py`, `radar_poly.py`, `.env.example`
- **Status**: ✅ Implementado — MarketConfig, find_current_market(config), symbol param em todas funções Binance, WS dinâmico, display parametrizado, phases proporcionais

---

### PRIORIDADE BAIXA

#### 11. PanelState Dataclass para `draw_panel()`
- **Problema**: `draw_panel()` tem **30 parâmetros**. Difícil de ler, fácil de errar a ordem, e qualquer novo dado exige mudar a assinatura + todas as 4 chamadas.
- **Solução**: Criar `@dataclass PanelState` com todos os campos. Passar um único objeto para `draw_panel()`.
- **Impacto**: Baixo — legibilidade e manutenibilidade
- **Esforço**: Médio
- **Arquivos**: `radar_poly.py`

#### 12. Extrair `format_scrolling_line()`
- **Problema**: A formatação da linha de scrolling (linhas 966-1054) são ~90 linhas de construção de colunas dentro do loop principal.
- **Solução**: Extrair para `format_scrolling_line(signal, btc_price, up_buy, down_buy, positions, regime)`.
- **Impacto**: Baixo — legibilidade
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py`

#### 13. History Deque com Proteção contra Gaps
- **Problema**: `history = deque(maxlen=60)` é global e o `_ema()` não tem proteção contra descontinuidades de timestamp. Se houver gap de dados (WS desconecta por 5min), a EMA mistura dados antigos com novos.
- **Solução**: Antes de calcular EMA, filtrar `hist` removendo entries com timestamp > 30s de diferença do anterior.
- **Impacto**: Baixo — edge case de reconexão WS
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py` — `compute_signal()`

#### 14. Connection Pooling (Fase 7) ✅
- **Problema**: `binance_api.py` e `polymarket_api.py` criam conexões HTTP individuais por request.
- **Solução**: Usar `requests.Session()` em cada módulo para reusar conexões.
- **Impacto**: Baixo — complementa item 6
- **Esforço**: Baixo
- **Arquivos**: `binance_api.py`, `polymarket_api.py`
- **Status**: ✅ Implementado junto com item 6

#### 15. Failed VWAP Reclaim Detection (Fase 7)
- **Problema**: Quando preço cruza VWAP para cima mas falha em se manter, é um forte sinal DOWN. Atualmente não detectado.
- **Solução**: Rastrear cruzamentos de VWAP. Se preço cruzou acima nas últimas 5 amostras mas agora está abaixo → boost DOWN signal.
- **Impacto**: Baixo — melhoria incremental de sinal
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py` — `compute_signal()`

#### 16. Market Transition Handling (Fase 7)
- **Problema**: Quando a janela 15min fecha, o radar espera até o próximo check de 60s para encontrar o novo mercado.
- **Solução**: Quando `time_remaining < 0.5min`, fazer check a cada 10s em vez de 60s. Exibir notificação de switching.
- **Impacto**: Baixo — reduz gap entre mercados
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py` — lógica de market refresh

---

## Análise Detalhada: `main()` — God Function (597 linhas, 44 variáveis)

A função `main()` (linhas 717→1317) concentra toda a lógica do sistema: UI, trading, hotkeys, market transition, alertas e sessão. É o principal gargalo de manutenibilidade.

### Mapa de Blocos

| Linhas | Bloco | Linhas | Extraível? |
|--------|-------|:------:|:----------:|
| 717-723 | Parse argumento trade_amount | 6 | Sim |
| 725-749 | Logger + banner doação + countdown | 24 | Parcial |
| 751-770 | Conectar API + balance + find market | 19 | Parcial |
| 772-780 | Price to Beat (BTC histórico) | 8 | Sim |
| 782-800 | Iniciar WebSocket | 18 | Sim |
| 802-820 | Configurar terminal (tty, scroll region) | 18 | Sim |
| 822-842 | Inicializar variáveis de sessão + painel inicial | 20 | Parcial |
| 846-928 | Coleta de dados (WS/HTTP candles, análise) | 82 | Sim |
| 930-947 | Fetch preços tokens + compute signal | 17 | Parcial |
| 949-964 | Log signal + atualizar painel estático | 15 | Parcial |
| **967-1055** | **Formatar linha scrolling (colunas + cores)** | **88** | **Sim** |
| **1057-1138** | **Oportunidade + hotkeys (signal buy + TP/SL)** | **81** | **Sim** |
| 1140-1154 | Price alert (beep) | 14 | Sim |
| **1156-1220** | **Sleep + hotkeys manuais (U/D/C/Q)** | **64** | **Parcial** |
| 1222-1240 | KeyboardInterrupt: fechar posições | 18 | Parcial |
| **1242-1297** | **Session summary (cálculo + print + log)** | **55** | **Sim** |
| 1305-1312 | Finally: cleanup (WS stop, terminal restore) | 7 | Parcial |

### 3 Padrões Duplicados Críticos

**Padrão A — Fechar posições (3 cópias)**

Aparece em: market transition (L863), emergency close (L1194), exit (L1231)
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
Solução: `close_all_positions(positions, token_up, token_down, logger, reason)` → retorna `(total_pnl, count, pnl_list)`

**Padrão B — Executar compra (3 cópias)**

Aparece em: signal buy (L1077), manual during opportunity (L1125), manual during sleep (L1160)
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
Solução: `handle_buy(client, direction, amount, reason, ...)` → retorna `(info, last_action)`

**Padrão C — Chamar draw_panel (4 cópias)**

Aparece em: painel inicial (L838), após signal (L956), emergency close antes (L1183), emergency close depois (L1209)
Todas com ~12 parâmetros idênticos repetidos.
Solução: `PanelState` dataclass — atualizar campos individuais, passar objeto único

### 44 Variáveis Locais

**Sessão (definidas uma vez):**
`trade_amount`, `logger`, `session_start`, `session_start_str`, `trade_history`, `client`, `limit`, `balance`, `event`, `market`, `token_up`, `token_down`, `time_remaining`, `market_slug`, `price_to_beat`, `binance_ws`, `ws_started`, `old_settings`, `fd`, `is_tty`

**Estado do loop (mutáveis a cada ciclo):**
`last_beep`, `last_market_check`, `base_time`, `positions`, `current_signal`, `alert_active`, `alert_side`, `alert_price`, `session_pnl`, `trade_count`, `status_msg`, `status_clear_at`, `last_action`, `now`, `now_str`

**Temporárias dentro do loop (~30+):**
`ws_candles`, `data_source`, `bin_direction`, `confidence`, `details`, `btc_price`, `binance_data`, `current_regime`, `up_buy`, `down_buy`, `s_dir`, `strength`, `rsi_val`, `trend`, `sr_raw`, `sr_adj`, `col_*` (15 variáveis de coluna), `blocks`, `bar`, `color`, `sym`, ...

### Plano de Refatoração

| Função a extrair | Elimina | Linhas salvas | Prioridade |
|-----------------|---------|:-------------:|:----------:|
| `close_all_positions()` | Padrão A (3x) | ~40 | Alta |
| `handle_buy()` | Padrão B (3x) | ~50 | Alta |
| `format_scrolling_line()` | Bloco 967-1055 | ~88 | Média |
| `calculate_session_stats()` | Bloco 1242-1262 | ~30 | Média |
| `PanelState` dataclass | Padrão C (4x) | ~20 | Baixa |
| **Total** | | **~230 (38%)** | |

Resultado: `main()` cai de **597 → ~370 linhas** e de **44 → ~30 variáveis**.

---

## Análise Detalhada: Performance (Especialista C)

### 7 Problemas de Performance Identificados

| # | Problema | Severidade | Local | Impacto |
|---|---------|-----------|-------|---------|
| 1 | Sem `requests.Session()` | CRITICAL | binance_api.py, polymarket_api.py, radar_poly.py | +50-500ms por request (nova conexão TCP) |
| 2 | `get_price()` sem cache | CRITICAL | radar_poly.py:117 | 2-10 requests/s duplicados no monitor_tp_sl() |
| 3 | ThreadPoolExecutor recriado a cada ciclo | HIGH | radar_poly.py:1149 | 1800+ criações/hora |
| 4 | `monitor_tp_sl()` I/O bloqueante | HIGH | radar_poly.py:885 | Tempo de resposta 1+s |
| 5 | 65+ sys.stdout.write() por redraw | MEDIUM | radar_poly.py:546-721 | 2200+ ops terminal/min |
| 6 | Polling HTTP com WebSocket ativo | MEDIUM | binance_api.py:411 | HTTP desnecessário para indicadores |
| 7 | Cópias de deque/list desnecessárias | LOW | radar_poly.py:165, ws_binance.py:108 | CPU/mem mínimo |

### Detalhamento

**1. HTTP Connection Reuse (CRITICAL)**
- Cada `requests.get()` sem Session abre nova conexão TCP: handshake 50-100ms rede rápida, 200-500ms rede lenta
- `get_price()` chamado 2x por ciclo (UP + DOWN), ciclo de 0.5s = 4 conexões/segundo
- `check_limit()` faz 2 requests sequenciais no polymarket_api.py:254-269
- **Fix**: `session = requests.Session()` no nível do módulo, trocar `requests.get()` → `session.get()`

**2. get_price() Sem Cache (CRITICAL)**
- Chamado em: close_all_positions (por posição), execute_buy_market (entry), execute_close_market (3x retry), monitor_tp_sl (cada 0.5s), main loop (UP+DOWN)
- No `monitor_tp_sl()`: polling a cada 0.5s, cada HTTP leva 100-500ms
- **Fix**: PriceCache com TTL de 0.5s para evitar duplicatas dentro do mesmo ciclo

**3. ThreadPoolExecutor (HIGH)**
- Linha 1149: `with ThreadPoolExecutor(max_workers=2) as pool:` dentro do loop
- Criação de pool inclui: alocação de threads, inicialização de estado, locks
- Com ciclo de 0.5s: ~7200 criações/destruições por hora
- **Fix**: Pool persistente no nível do módulo, `executor.shutdown()` no finally

**4. monitor_tp_sl() Blocking (HIGH)**
- `get_price()` bloqueia por 100-500ms → ciclo real é 1+s ao invés de 0.5s
- Key checking acontece DEPOIS do fetch (não concorrente)
- **Fix**: Fetch assíncrono + key checking concorrente via ThreadPoolExecutor

**5. Terminal Rendering (MEDIUM)**
- `draw_panel()` faz 66+ `sys.stdout.write()` individuais por redraw
- Cada `flush()` dispara I/O para o terminal
- 33+ redraws/min × 66 ops = 2200+ operações terminal/minuto
- **Fix**: Acumular em `io.StringIO()`, único `write()` + `flush()`

### Status de Implementação

| # | Fix | Status |
|---|-----|--------|
| 1 | requests.Session() persistente | ✅ Implementado |
| 2 | PriceCache com TTL | ✅ Implementado |
| 3 | ThreadPoolExecutor persistente | ✅ Implementado |
| 4 | monitor_tp_sl() concorrente | ✅ Implementado |
| 5 | Batch terminal writes (StringIO) | ✅ Implementado |
| 6 | Otimizar polling com WS ativo | ⬜ Pendente (requer mais análise) |
| 7 | Eliminar cópias de deque | ✅ Implementado |

**Estimativa combinada: 60-70% redução em latência de rede, 40-50% redução em overhead de CPU.**

---

## Melhorias de UI já Implementadas (sessão atual)

- ✅ Cor no RSI da coluna scrolling (verde < 40, vermelho > 60)
- ✅ Cor na barra de strength do scrolling
- ✅ Cor nos indicadores da linha SIGNAL (RSI, Trend, MACD, VWAP, BB)
- ✅ Cor do ALERT (verde UP, vermelho DOWN)
- ✅ Cor do S/R (verde positivo, vermelho negativo)
- ✅ Cor do BB corrigida (verde > 80%, vermelho < 20%)
- ✅ Alinhamento coluna BB (largura fixa 6 chars)
- ✅ Alinhamento header RSI (7 chars)
- ✅ Coluna RG renomeada para REGIME
- ✅ Linha ACTION no painel estático (trades sem poluir scrolling)
- ✅ `execute_hotkey()` silencioso (quiet=True)
- ✅ Tecla C funciona durante TP/SL monitoring
- ✅ Market transition calcula P&L real (fetch SELL price)
- ✅ Session summary no exit (clear + print)
- ✅ Aviso de venv não ativado
- ✅ WS auto-recovery no loop principal
- ✅ WebSocket em vez de WS na linha BINANCE
- ✅ Banner de doação com countdown 20s
- ✅ WR/PF exibidos na linha POSITION

---

## Ordem de Implementação Sugerida

### Sprint 1 — Risco & Execução (Fase 4 completa)
1. TP/SL dinâmico com ATR (#2)
2. TP/SL non-blocking (#1)
3. Trailing stop (#5)
4. Timeout no monitor_tp_sl (#9)

### Sprint 2 — Confiabilidade
5. Market expiry close real (#3)
6. Re-sync balance (#4)
7. requests.Session() persistente (#6)
8. ThreadPoolExecutor persistente (#7)

### Sprint 3 — Refatoração (parcial ✅)
9. Extrair handle_buy/handle_close (#8) ✅
10. Extrair format_scrolling_line (#12) ✅
11. PanelState dataclass (#11)

### Sprint 4 — Multi-Market (Fase 8) ✅
12. MarketConfig + parametrização (#10) ✅

### Sprint 5 — Polish
13. History gap protection (#13)
14. Connection pooling (#14)
15. VWAP reclaim detection (#15)
16. Market transition handling (#16)
