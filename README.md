# bot_deriv — Bot de Opções Binárias para Deriv

Bot assíncrono para a plataforma **Deriv** (ex-Binary.com), com 44 regras validadas em walk-forward 2019–2025.

Irmão do [bot IQ Option](../bot/) — mesmas estratégias, API diferente. Suporta **M30, H1 e H4** que a IQ Option não permite via bot.

---

## Instalação

```bash
git clone git@github.com:TiagoNovelli/bot_deriv.git
cd bot_deriv
pip install -r requirements.txt
cp .env.example .env
```

Edite o `.env`:

```env
DERIV_TOKEN=seu_token_aqui   # app.deriv.com/account/api-token → Read + Trade
DERIV_APP_ID=1089            # app público (ou crie o seu em developers.deriv.com)
MODO=DEMO                    # DEMO ou REAL
```

---

## Rodar

```bash
python3 bot_deriv.py
```

O bot conecta via WebSocket, monitora 22 pares/timeframes e opera automaticamente quando um sinal é confirmado.

---

## Sinais — 44 regras, ~351 ops/ano, WR médio 64.5%

| TF | Regras | Ops/ano | WR médio |
|----|--------|---------|----------|
| M1 | 8 | 113 | 62.8% |
| M5 | 6 | 48 | 65.7% |
| M15 | 3 | 31 | 63.7% |
| M30 | 6 | 36 | 67.2% |
| H1 | 13 | 70 | 66.6% |
| H4 | 8 | 54 | 63.7% |

Break-even com payout 75%: **57.1%**. Todos os sinais acima disso.

Destaques:
- USDJPY H1 DIV-RSI-BULL Ásia bb=1 → **77.1% WR, 5/5 anos**
- USDJPY M30 ENGOLFO-BAIXA Londres-abertura → **71.0% WR**
- USDJPY H4 PIN-CALL Ásia macd=0 → **63.8% WR, 7/7 anos** (maior estabilidade)

---

## Gestão — Soros-Gale Proporcional

- **Aposta base**: 1.67% da banca atual
- **Stop-loss diário**: 5% da banca do dia
- **Recuperação**: até 2 níveis (só em sinais de alta confiança)
- **Payout mínimo**: 75% — verificado via Proposal API antes de cada trade
- **Estado persistido**: `estado.json` — reinício no mesmo dia retoma de onde parou

---

## Diferenças vs IQ Option

| | IQ Option | Deriv |
|---|---|---|
| API | Unofficial | Oficial WebSocket |
| Auth | Email + senha | Token OAuth |
| M30 / H1 / H4 | ✗ | ✓ |
| Sinais de volume | ✓ (~350 ops/ano a mais) | ✗ (volume = 0) |
| Payout | Fixo ~82% | Variável, verificado por trade |
| Ops/ano | ~835 | ~351 |
| WR médio | ~62% | ~64.5% |

---

## Estrutura

```
bot_deriv/
├── bot_deriv.py    ← bot principal
├── sinais.py       ← detecção de padrões (NUVEM-NEGRA, DIV-RSI, PDV, etc.)
├── requirements.txt
├── .env.example
└── CLAUDE.md       ← contexto completo para desenvolvimento
```

---

## Dependências

```
websockets    — WebSocket async (Deriv API)
ta            — indicadores técnicos (RSI, Stoch, MACD, BB, EMA)
pandas numpy  — dados
python-dotenv — .env
```
