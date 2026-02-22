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

---

## Análise de Trading Especialista — Melhorias de Sinal, Execução e Risco

**Data:** 2026-02-22
**Contexto:** Análise profunda do sistema do ponto de vista de um trader especialista em mercados updown crypto na Polymarket. Foco em problemas que afetam diretamente o P&L.

---

### CRÍTICO — Afetam diretamente o P&L

#### T1. Price-to-Beat como componente do sinal
- **Problema**: O Price to Beat (preço do BTC no início da janela) é a métrica mais importante num mercado updown — é ele que define o resultado (BTC acima = UP vence, abaixo = DOWN vence). Porém `compute_signal()` **ignora completamente** essa informação. O sinal usa RSI/MACD/VWAP genéricos sem considerar a referência que define o resultado do mercado.
- **Exemplo**: Se BTC está $500 acima do beat price com 3 minutos restantes, a probabilidade de UP é altíssima. Mas o sinal pode dizer DOWN se o RSI estiver sobrecomprado e o MACD cruzar para baixo — um falso negativo grave.
- **Solução**: Novo componente `beat_distance_score`:
  ```python
  beat_diff_pct = (btc_price - price_to_beat) / price_to_beat * 100
  # Escala: cada 0.1% de diferença = ~10 pontos de confiança
  beat_score = max(-1.0, min(1.0, beat_diff_pct / 0.3))
  ```
  Peso dinâmico por fase:
  - EARLY: 10% (BTC pode reverter, pouco valor preditivo)
  - MID: 25% (já tem tendência, peso moderado)
  - LATE: 50% (quase determinístico, domina o sinal)
- **Impacto**: ALTO — esta é a informação mais preditiva do resultado final
- **Esforço**: Baixo
- **Arquivos**: `radar_poly.py` — `compute_signal()` recebe `price_to_beat` e `phase` como parâmetros

#### T2. Filtro de risk/reward nos extremos de preço
- **Problema**: Quando UP=$0.92, comprar UP rende no máximo $0.08 (8.7% upside) mas pode perder $0.91 (98.9% downside). O risk/reward é 1:11 — catastrófico. O script não impede essa compra. Igualmente, comprar DOWN a $0.05 tem upside de $0.94 mas probabilidade baixíssima.
- **Exemplo concreto**: Trader vê sinal UP 75%, pressiona S. O token está a $0.93. Compra 43 shares a $0.93 = $40. Se resolver UP, ganha $3. Se resolver DOWN, perde $40.
- **Solução**: Bloquear ou alertar quando o token de entrada excede threshold:
  ```python
  MAX_ENTRY_PRICE = 0.85  # Não comprar acima de 85 centavos
  MIN_ENTRY_PRICE = 0.08  # Não comprar abaixo de 8 centavos (probabilidade muito baixa)
  ```
  Quando bloqueado, mostrar no ALERT: `BLOCKED: UP@$0.93 — risk/reward 1:11 (max $0.07 / risk $0.93)`
- **Impacto**: ALTO — evita as piores perdas possíveis (perda quase total do trade)
- **Esforço**: Baixo (5-10 linhas)
- **Arquivos**: `radar_poly.py` — dentro do bloco de oportunidade detectada e no `handle_buy()`

#### T3. Enforçar check_limit() antes de cada buy
- **Problema**: A função `check_limit()` existe em `polymarket_api.py:246` e calcula exposure total (posições + ordens abertas) vs POSITION_LIMIT. Mas **nunca é chamada** no fluxo de trade: `handle_buy()` → `execute_hotkey()` → `execute_buy_market()` prossegue sem verificar. O usuário pode acumular exposição ilimitada.
- **Exemplo**: POSITION_LIMIT=76 no .env. Trader compra 10x de $10 = $100 de exposição. Nenhum bloqueio.
- **Solução**: Chamar `check_limit()` no início de `handle_buy()`:
  ```python
  can_trade, exposure, limit = check_limit(client, token_up, token_down, trade_amount)
  if not can_trade:
      last_action = f"BLOCKED: exposure ${exposure:.0f}/${limit:.0f}"
      return None, balance, last_action
  ```
- **Impacto**: ALTO — controle de risco fundamental que já existe mas não está conectado
- **Esforço**: Baixo (10 linhas)
- **Arquivos**: `radar_poly.py` — `handle_buy()` + passar `client, token_up, token_down` como args

#### T4. Auto-close antes da expiração do mercado
- **Problema**: O refresh de mercado acontece a cada 60s (`last_market_check`). Se o último check foi em T-80s, as posições podem não fechar antes da resolução do mercado. Tokens updown resolvem automaticamente: quem acertou recebe $1, quem errou recebe $0. Se o trader tem a posição certa, pode perder a oportunidade de vender a $0.95 antes da resolução (pois o mercado resolve em $1.00, mas sem liquidez nos últimos segundos).
- **Risco real**: Se estiver no lado errado, o token vai para $0.00 — perda total. E nos últimos 30-60 segundos, o spread do orderbook abre muito, dificultando o close.
- **Solução**: Hard cutoff em T-45s (configurável via .env `AUTO_CLOSE_SECONDS=45`):
  ```python
  if current_time <= 0.75 and positions:  # 45 segundos
      status_msg = "AUTO-CLOSE: market expiring"
      execute_close_market(client, token_up, token_down)
      close_all_positions(...)
  ```
- **Impacto**: ALTO — evita perda total por resolução no lado errado
- **Esforço**: Baixo (15 linhas)
- **Arquivos**: `radar_poly.py` — no main loop, antes do bloco de data collection

#### T5. TP/SL proporcional ao entry price e tempo restante
- **Problema**: TP/SL atual é fixo: `spread = 0.05 + (strength/100)*0.10`, `sl = entry - 0.06`. Isso não considera:
  1. **Entry price**: SL de $0.06 num token de $0.90 é 6.6% de risco, mas num token de $0.20 é 30%.
  2. **Tempo restante**: Com 10min restantes, TP de +$0.15 é alcançável. Com 1min, é impossível.
  3. **Volatilidade**: Em mercado volátil, SL apertado = stopado por ruído. Em mercado calmo, SL largo = perda desnecessária.
- **Solução**: TP/SL adaptativo baseado em ATR + time + entry:
  ```python
  atr = binance_data.get('atr', 0)
  atr_pct = atr / btc_price if btc_price > 0 else 0.001
  time_factor = min(current_time / 10, 1.0)  # diminui com tempo

  # Base em ATR, ajustado pelo tempo restante
  tp_spread = max(0.03, atr_pct * 50 * time_factor)
  sl_spread = max(0.02, atr_pct * 30 * time_factor)

  # Limitar por entry price (não pode ter SL > 50% do entry)
  sl_spread = min(sl_spread, entry * 0.20)

  tp = min(entry + tp_spread, 0.95)
  sl = max(entry - sl_spread, 0.03)
  ```
- **Impacto**: ALTO — TP/SL responsivo às condições reais de mercado
- **Esforço**: Médio
- **Arquivos**: `radar_poly.py` — `compute_signal()` (suggestion) + `monitor_tp_sl()`

---

### ALTO — Qualidade do Sinal

#### T6. Non-blocking TP/SL (já no backlog como #1, detalhamento de trading)
- **Problema de trading adicional**: Enquanto `monitor_tp_sl()` bloqueia, o mercado pode mudar de janela (15min se passaram), o regime pode virar de TREND para CHOP, e novas oportunidades são perdidas. Pior: se o mercado expirar durante o monitoramento, o P&L pode não ser calculado corretamente.
- **Solução de trading**: No main loop, manter `active_tp_sl = {'token_id': ..., 'tp': ..., 'sl': ..., 'entry': ...}`. A cada ciclo:
  1. Fetch price do token monitorado
  2. Verificar TP/SL/Trailing
  3. Exibir progress bar na linha ACTION
  4. Permitir hotkey C para cancelar
  5. Se TP/SL atingido, executar close automaticamente
- **Impacto**: ALTO — trader mantém visão completa do mercado durante posição aberta
- **Esforço**: Médio-Alto
- **Arquivos**: `radar_poly.py` — substituir `monitor_tp_sl()` por state machine no loop

#### T7. Session max-loss circuit breaker
- **Problema**: Se o trader perder 5 trades consecutivos ($30 de perda numa conta de $76), o sistema continua operando normalmente. Sem limite de perda por sessão, um dia ruim pode dizimar a conta inteira.
- **Solução**: Nova variável .env `MAX_SESSION_LOSS=20` (default $20). Quando `session_pnl <= -MAX_SESSION_LOSS`:
  - Fechar todas as posições automaticamente
  - Desabilitar trading (ignore hotkeys U/D/S)
  - Mostrar na linha STATUS: `CIRCUIT BREAKER: session loss $-20.00 (limit: $20)`
  - Continuar exibindo o radar (monitoramento) mas sem executar trades
  - Hotkey R para resetar o breaker (requer confirmação)
- **Impacto**: MÉDIO-ALTO — proteção essencial contra dias ruins
- **Esforço**: Baixo (20 linhas)
- **Arquivos**: `radar_poly.py` — check no `handle_buy()` + nova variável .env

#### T8. Cooldown após perda
- **Problema**: Após uma perda, o trader (e o sistema) pode entrar imediatamente num novo trade. Em trading real, isso leva a "revenge trading" — trades emocionais que acumulam mais perdas. O sinal pode estar correto mas a condição de mercado que causou a perda ainda persiste.
- **Solução**: Cooldown configurável após loss: `COOLDOWN_AFTER_LOSS=30` (segundos). Após fechar uma posição com P&L negativo:
  ```python
  if pnl < 0:
      cooldown_until = time.time() + COOLDOWN_AFTER_LOSS
  ```
  Durante cooldown:
  - Sinais continuam sendo calculados e exibidos
  - Oportunidades são detectadas mas **não oferecem prompt** (S/U/D ignorados)
  - Linha STATUS mostra: `COOLDOWN: 25s remaining (last trade: -$1.50)`
- **Impacto**: MÉDIO — previne acumulação de perdas consecutivas
- **Esforço**: Baixo (15 linhas)
- **Arquivos**: `radar_poly.py` — variável `cooldown_until`, check no bloco de oportunidade

---

### MÉDIO — Refinamento do Sinal

#### T9. Pesos dinâmicos por fase temporal
- **Problema**: Os 6 pesos do sinal (Momentum 30%, Divergence 20%, S/R 10%, MACD 15%, VWAP 15%, BB 10%) são fixos. Mas a utilidade de cada indicador muda drasticamente ao longo da janela:
  - **EARLY** (>66%): Momentum/MACD são informativos (tendência se formando), mas Price-to-Beat tem pouco valor preditivo (BTC pode reverter várias vezes)
  - **MID** (33-66%): Todos os indicadores têm valor similar
  - **LATE** (<33%): A distância BTC vs Beat é quase determinística. RSI oversold é irrelevante se BTC está $300 acima do beat com 2 minutos restantes
- **Solução**: Tabela de pesos por fase:
  ```
  Componente        EARLY   MID    LATE
  ─────────────────────────────────────
  Beat Distance      10%    25%    50%
  Momentum           30%    20%    10%
  Divergence         20%    15%     5%
  MACD               15%    15%    10%
  VWAP               15%    15%    10%
  S/R                 5%     5%    10%
  Bollinger           5%     5%     5%
  ```
- **Impacto**: MÉDIO — sinal mais calibrado para cada momento da janela
- **Esforço**: Médio (tabela de pesos + refatorar compute_signal)
- **Arquivos**: `radar_poly.py` — `compute_signal()` recebe `phase` e ajusta pesos

#### T10. Normalizar thresholds de indicadores pelo preço
- **Problema**: Vários indicadores usam thresholds em valores absolutos de dólar:
  - MACD: `abs(macd_hist_delta) > 0.5` (linha 266) — $0.50 em BTC a $98k é 0.0005%, irrelevante. A $20k seria 0.0025%, mais significativo.
  - VWAP: `vwap_pos > 0.02` (linha 283) — 0.02% é ~$20 em BTC a $98k. Muito pequeno para ser significativo.
  - ATR-based vol threshold: `VOL_THRESHOLD=0.03` (3%) é razoável mas estático.
- **Solução**: Normalizar pelo preço atual. Para MACD:
  ```python
  macd_delta_pct = macd_hist_delta / btc_price * 100  # em percentual
  if abs(macd_delta_pct) > 0.0005: macd_score = 1.0 if macd_delta_pct > 0 else -1.0
  ```
  Para VWAP: aumentar threshold para `0.05` (0.05% = ~$50 em BTC a $98k).
- **Impacto**: MÉDIO — reduz sinais falsos por thresholds descalibrados
- **Esforço**: Baixo (ajustar 3-4 comparações)
- **Arquivos**: `radar_poly.py` — `compute_signal()` componentes 4 (MACD) e 5 (VWAP)

#### T11. Recuperar posições existentes no startup
- **Problema**: `positions = []` é inicializado vazio no início do main(). Se o script crashar e reiniciar, não sabe das posições existentes nos tokens UP/DOWN. O trader pode ter shares que não aparecem no painel, e o P&L da sessão começa errado.
- **Solução**: No startup, após obter token_up/token_down, consultar posições:
  ```python
  up_shares = get_token_position(client, token_up)
  down_shares = get_token_position(client, token_down)
  if up_shares > 0.01:
      up_price = get_price(token_up, "SELL")
      positions.append({'direction': 'up', 'price': up_price, 'shares': up_shares, 'time': now_str})
      print(f"Recovered UP position: {up_shares:.0f}sh @ ${up_price:.2f}")
  # idem para down_shares
  ```
- **Impacto**: MÉDIO — resiliência a crashes + informação correta no painel
- **Esforço**: Baixo (15 linhas)
- **Arquivos**: `radar_poly.py` — após `find_current_market()`, antes do main loop

#### T12. Divergence lookback mais longo
- **Problema**: O componente Divergence (BTC vs Polymarket price) olha apenas 6 ciclos passados (~12 segundos com ciclo de 2s, ~3s com WS). Em crypto, movimentos de 12 segundos são ruído puro — qualquer micro-flutuação gera "divergência" falsa.
- **Solução**: Aumentar lookback para 30-60 ciclos (~1-2 minutos). Com mais história, a divergência detectada é mais significativa:
  ```python
  DIVERGENCE_LOOKBACK = 30  # ciclos (~60s com ciclo 2s, ~15s com WS 0.5s)
  if len(history) >= DIVERGENCE_LOOKBACK:
      h_old = history[-DIVERGENCE_LOOKBACK]
      h_new = history[-1]
      ...
  ```
  Adicionalmente, considerar usar a **média** dos últimos 5 pontos antigos vs últimos 5 pontos recentes para suavizar ruído.
- **Impacto**: MÉDIO — reduz divergências falsas
- **Esforço**: Baixo (alterar 1 constante + suavização opcional)
- **Arquivos**: `radar_poly.py` — `compute_signal()` componente 2 (Divergence)

#### T13. S/R em níveis de BTC (não do token Polymarket)
- **Problema**: O componente S/R atual calcula suporte/resistência nos preços do token UP (valores entre $0.01-$0.99). Isso reflete o que o **mercado já precificou**, não o que vai acontecer. O verdadeiro driver é o preço do BTC — se BTC está testando suporte em $68,000, isso é informação nova que o mercado Polymarket pode não ter precificado ainda.
- **Solução**: Calcular S/R usando preços BTC dos candles Binance:
  ```python
  btc_prices = [c['high'] for c in candles[-20:]] + [c['low'] for c in candles[-20:]]
  btc_high = max(btc_prices)
  btc_low = min(btc_prices)
  btc_range = btc_high - btc_low

  # Posição do preço atual no range recente
  if btc_range > 0:
      btc_pos = (btc_price - btc_low) / btc_range
      if btc_pos < 0.15: sr_score = 0.8    # próximo do suporte = UP
      elif btc_pos > 0.85: sr_score = -0.8  # próximo da resistência = DOWN
  ```
  Bonus: detectar round numbers ($68,000, $68,500, etc.) como suporte/resistência psicológicos:
  ```python
  round_500 = round(btc_price / 500) * 500
  dist_to_round = abs(btc_price - round_500) / btc_price
  if dist_to_round < 0.001:  # dentro de 0.1% de um round number
      sr_score *= 1.2  # amplificar sinal de S/R
  ```
- **Impacto**: MÉDIO — S/R em BTC é mais preditivo que em preço de token
- **Esforço**: Médio (reescrever componente S/R)
- **Arquivos**: `radar_poly.py` — `compute_signal()` componente 3, ou `binance_api.py` nova função `compute_sr_levels(candles)`

---

### BAIXO — Refinamentos

#### T14. Volume como multiplicador de confiança
- **Problema**: O volume da Binance é calculado (`vol_up`, `vol_down` em `analyze_trend()`) mas só usado para display (flag HIGH/normal). Um sinal de alta sem volume comprando é muito menos confiável — pode ser apenas uma flutuação por falta de liquidez.
- **Solução**: Usar razão de volume como multiplicador do score final:
  ```python
  vol_ratio = vol_up / (vol_up + vol_down) if (vol_up + vol_down) > 0 else 0.5
  # Se volume confirma a direção, boost. Se contradiz, dampen.
  if score > 0 and vol_ratio > 0.60:
      score *= 1.15  # volume confirma bullish
  elif score > 0 and vol_ratio < 0.40:
      score *= 0.75  # volume contradiz bullish
  elif score < 0 and vol_ratio < 0.40:
      score *= 1.15  # volume confirma bearish
  elif score < 0 and vol_ratio > 0.60:
      score *= 0.75  # volume contradiz bearish
  ```
- **Impacto**: BAIXO-MÉDIO — filtro incremental de sinais falsos
- **Esforço**: Baixo (10 linhas)
- **Arquivos**: `radar_poly.py` — `compute_signal()` após score final, antes de regime adjustment

#### T15. Spread monitoring (bid-ask do orderbook)
- **Problema**: O script busca apenas best BUY e best SELL price. Não mostra o spread (diferença entre bid e ask). Spread largo = baixa liquidez = maior custo de entrada/saída = maior slippage efetivo. Em tokens com spread de $0.10, um trade de $4 já tem $0.40 de custo implícito (10%).
- **Solução**: Calcular e exibir spread na linha POLY:
  ```python
  up_sell = get_price(token_up, "SELL")
  spread_up = up_buy - up_sell
  # POLY │ UP: $0.55/$0.45 (55%) spread:$0.03 │ DOWN: ...
  ```
  Adicionalmente, usar spread como filtro: se `spread > 0.08`, alertar que o custo de transação é alto.
- **Impacto**: BAIXO — informação útil para decisão manual, filtro de liquidez
- **Esforço**: Médio (fetch adicional + exibição + filtro)
- **Arquivos**: `radar_poly.py` — `draw_panel()` linha POLY, `compute_signal()` como filtro

---

## Ordem de Implementação — Melhorias de Trading

### Sprint T1 — Proteção de Capital (Impacto: prevenir perdas evitáveis)
1. Enforçar check_limit() (T3) — Baixo esforço, impacto imediato
2. Filtro risk/reward extremos (T2) — Baixo esforço, evita piores perdas
3. Auto-close antes de expiração (T4) — Baixo esforço, evita perda total
4. Session max-loss circuit breaker (T7) — Baixo esforço, proteção de sessão

### Sprint T2 — Qualidade do Sinal (Impacto: melhorar decisões)
5. Price-to-Beat no sinal (T1) — A informação mais preditiva do resultado
6. TP/SL proporcional (T5) — Gestão de risco adaptativa
7. Cooldown pós-loss (T8) — Prevenir revenge trading

### Sprint T3 — Refinamento (Impacto: sinais mais calibrados)
8. Pesos dinâmicos por fase (T9) — Sinal adapta à janela temporal
9. Normalizar thresholds (T10) — Reduz sinais falsos
10. Divergence lookback maior (T12) — Divergência mais significativa

### Sprint T4 — Execução Avançada
11. Non-blocking TP/SL (T6) — Visão completa durante posição
12. Recuperar posições no startup (T11) — Resiliência
13. S/R em níveis BTC (T13) — S/R mais preditivo
14. Volume como multiplicador (T14) — Confirmação de sinal
15. Spread monitoring (T15) — Informação de liquidez
