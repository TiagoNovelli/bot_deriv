# CLAUDE.md — bot_deriv

## Visão geral

Bot de opções binárias para a plataforma **Deriv** (ex-Binary.com), irmão do [bot IQ Option](../bot/).

Usa a **API oficial WebSocket da Deriv** (`wss://ws.binaryws.com/websockets/v3`), autenticação por token OAuth, e suporta timeframes longos (M30, H1, H4) que a IQ Option não permite via bot.

---

## Estrutura

```
bot_deriv/
├── bot_deriv.py    ← Bot principal (WebSocket async, 44 regras, Soros-Gale)
├── sinais.py       ← Detecção de padrões e sinais (extraído de analise_m15.py)
├── requirements.txt
├── .env            ← Token Deriv (NÃO commitar)
├── .env.example
├── estado.json     ← Estado Soros-Gale runtime (criado automaticamente)
└── README.md
```

---

## Como rodar

```bash
pip install -r requirements.txt
cp .env.example .env
# editar .env com token Deriv e MODO=DEMO
python3 bot_deriv.py
```

---

## Configuração (.env)

```
DERIV_TOKEN=seu_token_aqui     # app.deriv.com/account/api-token (Read + Trade)
DERIV_APP_ID=1089               # app público Deriv (pode criar o próprio)
MODO=DEMO                       # DEMO ou REAL
```

---

## Diferenças vs IQ Option

| | IQ Option (bot_m15.py) | Deriv (bot_deriv.py) |
|---|---|---|
| API | Unofficial | Oficial WebSocket |
| Auth | Email + senha | Token OAuth |
| Volume forex | Real | Sempre 0 |
| Sinais DNC-RSI+VOL | Sim (~350 ops/ano) | **Não** (sem volume) |
| OTC 24/7 | Sim | Não |
| M30 / H1 / H4 | **Não** (max M15) | **Sim** |
| Payout | Fixo ~82% | Variável — verificado via Proposal antes de cada trade |
| Ops/ano | ~835 | ~351 |
| WR médio | ~62% | **~64.5%** |

---

## Regras ativas — 44 regras, ~351 ops/ano

Todas validadas walk-forward por ano (2019–2025), break-even 54.9% (payout mín. 75%).
Sinais dependentes de volume (DNC-RSI+VOL, PDV-S3-VOL) excluídos — volume = 0 na Deriv.

### M1 — 8 regras, ~113 ops/ano, WR médio 62.8%

| Par | Sinal | Sessão | Filtros | WR |
|-----|-------|--------|---------|-----|
| EURGBP | NUVEM-NEGRA | Londres | ema50=0 + stoch_virando=0 | 61.2% |
| EURUSD | DIV-RSI-BULL | NY-abertura | bb=1 + stoch=0 | 61.3% |
| EURJPY | NUVEM-NEGRA | Ásia | ema50=1 + bb=1 | 63.0% |
| EURJPY | HARAMI-BAIXA | NY-abertura | bb=1 + stoch=1 | 60.6% |
| USDJPY | NUVEM-NEGRA | Londres | stoch_extremo=1 | 73.6% |
| USDJPY | NUVEM-NEGRA | Londres | stoch_virando=1 | 62.9% |
| GBPUSD | DIV-RSI-BEAR | Londres-abertura | bb=1 + stoch=0 | 61.3% |
| GBPUSD | NUVEM-NEGRA | NY-abertura | stoch=1 | 62.1% |

### M5 — 6 regras, ~48 ops/ano, WR médio 65.7%

Dados: ticks Dukascopy diretos (não resample), revalidado 2019–2025.
Os sinais antigos (TRESCORVOS, PIN-CALL, etc.) não tinham edge no dataset completo.

| Par | Sinal | Sessão | Filtros | WR |
|-----|-------|--------|---------|-----|
| EURGBP | PDV-S1 | Londres | stoch_virando=1 | 69.2% |
| EURUSD | PDV-S1 | NY-abertura | stoch=1 | 68.4% |
| EURUSD | PERFURACAO-ALTA | NY | bb=0 | 63.5% |
| EURJPY | EVENING-STAR | Londres-abertura | stoch_virando=0 | 67.8% |
| GBPUSD | PDV-S2 | NY-abertura | stoch=1 | 71.8% |
| USDJPY | PDV-S1 | Ásia | — | 59.0% |

### M15 — 3 regras, ~31 ops/ano, WR médio 63.7%

| Par | Sinal | Sessão | Filtros | WR |
|-----|-------|--------|---------|-----|
| EURGBP | NUVEM-NEGRA | Ásia | ema50=1 | 65.0% |
| EURUSD | DOJI-EXTREMO | Ásia | stoch=1 | 62.3% |
| EURJPY | DOJI-EXTREMO | Ásia | stoch=1 | 63.8% |

### M30 — 6 regras, ~36 ops/ano, WR médio 67.2% (exclusivo Deriv)

| Par | Sinal | Sessão | Filtros | WR |
|-----|-------|--------|---------|-----|
| USDJPY | ENGOLFO-BAIXA | Londres-abertura | stoch_virando=0 | 71.0% |
| USDJPY | TRESSOLDADOS | NY-abertura | ema50=1 | 70.3% |
| EURJPY | TRESSOLDADOS | NY | ema50=1 | 67.6% |
| EURJPY | TRESSOLDADOS | NY | — | 65.5% |
| EURJPY | MORNING-STAR | Londres | — | 66.7% |
| EURUSD | TRESCORVOS | Londres-abertura | stoch=0 | 63.6% |

### H1 — 13 regras, ~70 ops/ano, WR médio 66.6% (exclusivo Deriv)

| Par | Sinal | Sessão | Filtros | WR |
|-----|-------|--------|---------|-----|
| USDJPY | MORNING-STAR | Ásia | macd=0 | 71.0% |
| USDJPY | DIV-RSI-BULL | Ásia | bb=1 | 77.1% |
| USDJPY | EVENING-STAR | Londres-abertura | bb=0 | 65.5% |
| USDJPY | HARAMI-ALTA | NY | — | 63.3% |
| USDJPY | PDV-S4-RSI | Londres | — | 66.7% |
| EURUSD | MORNING-STAR | Londres-abertura | bb=0 | 70.4% |
| EURUSD | TRESCORVOS | Ásia | macd=0 | 63.0% |
| EURUSD | DIV-RSI-BEAR | Ásia | ema50=1 | 66.3% |
| EURJPY | ENGOLFO-BAIXA | Ásia | ema50=1 | 66.7% |
| EURJPY | TRESSOLDADOS | Ásia | — | 60.5% |
| EURGBP | MORNING-STAR | Ásia | macd=0 | 59.5% |
| GBPUSD | DIV-RSI-BULL | NY | — | 71.7% |
| GBPUSD | HARAMI-ALTA | Ásia | macd=0 | 62.5% |

### H4 — 8 regras, ~54 ops/ano, WR médio 63.7% (exclusivo Deriv)

| Par | Sinal | Sessão | Filtros | WR |
|-----|-------|--------|---------|-----|
| USDJPY | MORNING-STAR | Ásia | ema50=0 | 62.5% |
| USDJPY | PDV-S4-RSI | Londres-abertura | macd=0 | 69.6% |
| USDJPY | PIN-CALL | Ásia | macd=0 | 63.8% |
| EURJPY | EVENING-STAR | Ásia | stoch_virando=0 | 59.5% |
| EURJPY | PDV-S4-RSI | NY-abertura | — | 65.6% |
| EURUSD | TRESCORVOS | Ásia | — | 57.6% |
| EURUSD | DIV-RSI-BEAR | Londres-abertura | — | 65.8% |
| GBPUSD | DIV-RSI-BULL | Ásia | — | 66.0% |

---

## Estratégia Soros-Gale

```
Aposta base:       1.67% da banca atual (proporcional)
Stop-loss diário:  5% da banca no início do dia
Máx. níveis:       2  (só para sinais nivel=2, WR ≥ 65%)
Fórmula recovery:  valor_recuperar / 2 × 1.3
Payout mínimo:     75% (verificado via Proposal antes de cada trade)
```

Estado de recuperação persiste em `estado.json` — reinício no mesmo dia retoma do ponto onde parou.

---

## Sessões (UTC)

```python
22h–07h  → Ásia          (19h–4h Brasília)
07h–10h  → Londres-abertura  (4h–7h Brasília)
10h–13h  → Londres       (7h–10h Brasília)
13h–17h  → NY-abertura   (10h–14h Brasília)
17h–22h  → NY            (14h–19h Brasília)
```

---

## Análise e validação

Os dados de treinamento estão no repositório irmão `../bot/analise_padroes/`:

```bash
# Baixar dados M1/M5/M15 (Dukascopy, 2019-2025)
cd ../bot/analise_padroes
python3 baixar_dados.py

# Gerar M30/H1/H4 do M1
python3 gerar_timeframes.py

# Rodar análise walk-forward
python3 analise_m15.py "EURGBP-M30" "EURJPY-H1" "USDJPY-H4" ...
```

---

## Contexto do usuário

- Tiago Novelli (`novellitiago95@gmail.com`)
- Banca atual: R$3.187 (DEMO) | Aposta: 1.67% proporcional
- Repositório irmão: `../bot/` (IQ Option, análise, Monte Carlo)
