# bot_deriv — Bot de Trading para Deriv

Versão do bot de opções binárias adaptada para a plataforma **Deriv** (antiga Binary.com).

Usa as mesmas estratégias validadas estatisticamente do [bot IQ Option](../bot/), com as seguintes diferenças:

| | IQ Option | Deriv |
|---|---|---|
| API | Unofficial (iqoptionapi) | Oficial WebSocket |
| Autenticação | Email + senha | Token OAuth |
| Volume | Real (forex) | Sempre 0 (forex) |
| Sinais DNC-RSI+VOL | Sim | Não (sem volume) |
| OTC 24/7 | Sim | Não |
| Payout | Fixo ~82% | Variável — verificado antes de cada trade |
| Regulação | Questionável | MGA (Malta), Labuan, Vanuatu |

---

## Instalação

```bash
cd bot_deriv
pip install -r requirements.txt
cp .env.example .env
```

### Configurar token Deriv

1. Acesse [app.deriv.com/account/api-token](https://app.deriv.com/account/api-token)
2. Crie um token com permissões **Read** e **Trade**
3. Copie o token para o `.env`:

```
DERIV_TOKEN=seu_token_aqui
DERIV_APP_ID=1089
MODO=DEMO
```

Para operar conta real: `MODO=REAL` (e use o token da conta real).

---

## Rodar

```bash
python3 bot_deriv.py
```

---

## Como funciona

- Loop a cada 10s verificando 12 pares/timeframes (M1, M5, M15)
- **19 regras** ativas (excluindo DNC-RSI+VOL que depende de volume)
- Antes de cada trade: verifica payout via Proposal API — só opera se payout ≥ 75%
- Aposta proporcional: 1.67% da banca atual
- Soros-Gale 2 níveis com estado persistido em `estado.json`
- Stop-loss diário: 5% da banca no início do dia
- Reconexão automática em caso de queda do WebSocket

---

## Regras ativas (19)

Todas validadas com walk-forward por ano no bot IQ Option. Excluídas as que dependem de volume real (DNC-RSI+VOL) e os pares OTC.

| Timeframe | Par | Sinal | Sessão | WR histórico |
|-----------|-----|-------|--------|-------------|
| M15 | EURGBP | NUVEM-NEGRA | Ásia | 64.5% |
| M15 | USDJPY | ENGOLFO-BAIXA | NY | 58.6% |
| M15 | EURUSD | DOJI-EXTREMO | Ásia | 62.3% |
| M15 | EURJPY | DOJI-EXTREMO | Ásia | 63.8% |
| M5  | EURGBP | TRESCORVOS | Londres | 67.1% |
| M5  | EURUSD | ENGOLFO-ALTA | Ásia | 62.6% |
| M5  | EURUSD | DIV-RSI-BULL | Londres-abertura | 58.6% |
| M5  | EURUSD | PDV-S4-RSI | NY-abertura | 56.4% |
| M5  | EURJPY | PIN-CALL | Ásia | 62.8% |
| M5  | EURJPY | TRESSOLDADOS | Londres | 63.9% |
| M5  | EURJPY | HARAMI-ALTA | Londres | 61.6% |
| M1  | EURGBP | NUVEM-NEGRA | Londres | 59.7% |
| M1  | EURUSD | DIV-RSI-BULL | NY-abertura | 60.8% |
| M1  | EURJPY | NUVEM-NEGRA | Ásia | 63.6% |
| M1  | EURJPY | HARAMI-BAIXA | NY-abertura | 60.3% |
| M1  | USDJPY | NUVEM-NEGRA | Londres | 72.9% |
| M1  | USDJPY | NUVEM-NEGRA | Londres | 63.1% |
| M1  | GBPUSD | DIV-RSI-BEAR | Londres-abertura | 65.8% |
| M1  | GBPUSD | NUVEM-NEGRA | NY-abertura | 59.9% |

---

## Sobre o payout variável

Na Deriv o payout não é fixo como na IQ Option. Antes de cada trade, o bot faz uma requisição `proposal` e verifica se o payout líquido está acima de `PAYOUT_MIN` (padrão: 75%). Se estiver abaixo, o trade é ignorado.

Break-even por payout:
- Payout 82% → WR mínimo 54.9%
- Payout 75% → WR mínimo 57.1%
- Payout 70% → WR mínimo 58.8%

---

## Dependências

- `websockets` — WebSocket async para a Deriv API
- `ta` — indicadores técnicos (RSI, Stoch, MACD, BB, EMA)
- `pandas`, `numpy` — séries de dados
- `python-dotenv` — credenciais via .env
