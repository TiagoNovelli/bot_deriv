"""
bot_deriv.py — Deriv WebSocket Bot
====================================
Mesmas estratégias do bot IQ Option via Deriv API (WebSocket oficial).

Diferenças vs IQ Option:
  - Sem sinais DNC-RSI+VOL (Deriv não fornece volume real em forex)
  - Payout verificado antes de cada trade (varia por ativo/condição)
  - Autenticação por token OAuth (não email/senha)
  - Suporta M30 além de M1/M5/M15
  - Mercado real forex fecha fins de semana (sem OTC aqui)
"""

import asyncio
import json
import os
import sys
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import ta
import websockets
from dotenv import load_dotenv

from sinais import (
    cor_vela,
    detectar_padrao_confirmado,
    detectar_morning_evening_star,
    detectar_doji_extremo,
    detectar_pin_bar,
    sinais_padrao_vela,
    sinais_dinamicos,
    classificar_sessao,
)

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── Parâmetros ────────────────────────────────────────────────────────────────

FRAC_BANCA    = 1 / 60    # 1.667% da banca por operação
STOP_LOSS_PCT = 0.05      # 5% da banca do início do dia
PAYOUT_MIN    = 0.75      # payout líquido mínimo aceitável (ex: 0.75 = 75%)
VELAS_Q       = 300
STATE_FILE    = os.path.join(os.path.dirname(__file__), "estado.json")

APP_ID    = os.environ.get("DERIV_APP_ID", "1089")   # 1089 = app público da Deriv
TOKEN     = os.environ["DERIV_TOKEN"]
DEMO_MODE = os.environ.get("MODO", "DEMO").upper() == "DEMO"

WS_ENDPOINT = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"

GRANULARITY = {1: 60, 5: 300, 15: 900, 30: 1800, 60: 3600, 240: 14400}

# Mapeamento par → símbolo Deriv (frx = forex)
SYMBOL = {
    "EURGBP": "frxEURGBP",
    "EURUSD": "frxEURUSD",
    "EURJPY": "frxEURJPY",
    "USDJPY": "frxUSDJPY",
    "GBPUSD": "frxGBPUSD",
}

# ── Alvos monitorados: (par, timeframe_min) ───────────────────────────────────

ALVOS = [
    # M15
    ("EURGBP", 15), ("EURUSD", 15), ("EURJPY", 15), ("USDJPY", 15),
    # M30 — exclusivo Deriv (IQ Option não suporta)
    ("EURUSD", 30), ("EURJPY", 30), ("USDJPY", 30),
    # M5
    ("EURGBP",  5), ("EURUSD",  5), ("EURJPY",  5), ("GBPUSD",  5), ("USDJPY",  5),
    # M1
    ("EURGBP",  1), ("EURUSD",  1), ("EURJPY",  1), ("USDJPY",  1), ("GBPUSD",  1),
    # H1 — exclusivo Deriv
    ("EURGBP", 60), ("EURUSD", 60), ("EURJPY", 60), ("USDJPY", 60), ("GBPUSD", 60),
    # H4 — exclusivo Deriv
    ("EURUSD", 240), ("EURJPY", 240), ("USDJPY", 240), ("GBPUSD", 240),
]

# ── Regras confirmadas (sem DNC-RSI+VOL — depende de volume) ─────────────────

REGRAS = [
    # ── M15 ──────────────────────────────────────────────────────────────────
    {
        "nome": "EURGBP M15 NUVEM-NEGRA Ásia ema50=1", "par": "EURGBP", "tf": 15, "nivel": 1,
        "check": lambda i: (i["padrao"] == "NUVEM-NEGRA"
                            and i["sessao"] == "Asia"
                            and i["extremo_ema50"] == 1),
    },
    {
        "nome": "USDJPY M15 ENGOLFO-BAIXA NY ema50=1 bb=0", "par": "USDJPY", "tf": 15, "nivel": 1,
        "check": lambda i: (i["padrao"] == "ENGOLFO-BAIXA"
                            and i["sessao"] == "NY"
                            and i["extremo_ema50"] == 1
                            and i["bb_extremo"] == 0),
    },
    {
        "nome": "EURUSD M15 DOJI-EXTREMO Ásia stoch=1", "par": "EURUSD", "tf": 15, "nivel": 1,
        "check": lambda i: (i["padrao"] == "DOJI-EXTREMO"
                            and i["sessao"] == "Asia"
                            and i["stoch_extremo"] == 1),
    },
    {
        "nome": "EURJPY M15 DOJI-EXTREMO Ásia stoch=1", "par": "EURJPY", "tf": 15, "nivel": 1,
        "check": lambda i: (i["padrao"] == "DOJI-EXTREMO"
                            and i["sessao"] == "Asia"
                            and i["stoch_extremo"] == 1),
    },
    # ── M5 — validado walk-forward 2019-2025 (dados de ticks Dukascopy) ─────────
    {
        "nome": "EURGBP M5 PDV-S1 Londres stoch_virando=1", "par": "EURGBP", "tf": 5, "nivel": 1,
        "check": lambda i: (i["sinal"] == "PDV-S1"
                            and i["sessao"] == "Londres"
                            and i["stoch_virando"] == 1),
    },
    {
        "nome": "EURUSD M5 PDV-S1 NY-abertura stoch=1", "par": "EURUSD", "tf": 5, "nivel": 1,
        "check": lambda i: (i["sinal"] == "PDV-S1"
                            and i["sessao"] == "NY-abertura"
                            and i["stoch_extremo"] == 1),
    },
    {
        "nome": "EURUSD M5 PERFURACAO-ALTA NY bb=0", "par": "EURUSD", "tf": 5, "nivel": 1,
        "check": lambda i: (i["padrao"] == "PERFURACAO-ALTA"
                            and i["sessao"] == "NY"
                            and i["bb_extremo"] == 0),
    },
    {
        "nome": "EURJPY M5 EVENING-STAR Londres-abertura stoch_virando=0", "par": "EURJPY", "tf": 5, "nivel": 1,
        "check": lambda i: (i["sinal"] == "EVENING-STAR"
                            and i["sessao"] == "Londres-abertura"
                            and i["stoch_virando"] == 0),
    },
    {
        "nome": "GBPUSD M5 PDV-S2 NY-abertura stoch=1", "par": "GBPUSD", "tf": 5, "nivel": 1,
        "check": lambda i: (i["sinal"] == "PDV-S2"
                            and i["sessao"] == "NY-abertura"
                            and i["stoch_extremo"] == 1),
    },
    {
        "nome": "USDJPY M5 PDV-S1 Ásia", "par": "USDJPY", "tf": 5, "nivel": 1,
        "check": lambda i: (i["sinal"] == "PDV-S1"
                            and i["sessao"] == "Asia"),
    },
    # ── M1 ───────────────────────────────────────────────────────────────────
    {
        "nome": "EURGBP M1 NUVEM-NEGRA Londres ema50=0 stoch=0", "par": "EURGBP", "tf": 1, "nivel": 1,
        "check": lambda i: (i["padrao"] == "NUVEM-NEGRA"
                            and i["sessao"] == "Londres"
                            and i["extremo_ema50"] == 0
                            and i["stoch_virando"] == 0),
    },
    {
        "nome": "EURUSD M1 DIV-RSI-BULL NY-abertura bb=1 stoch=0", "par": "EURUSD", "tf": 1, "nivel": 1,
        "check": lambda i: (i["sinal"] == "DIV-RSI-BULL"
                            and i["sessao"] == "NY-abertura"
                            and i["bb_extremo"] == 1
                            and i["stoch_extremo"] == 0),
    },
    {
        "nome": "EURJPY M1 NUVEM-NEGRA Ásia ema50=1 bb=1", "par": "EURJPY", "tf": 1, "nivel": 1,
        "check": lambda i: (i["padrao"] == "NUVEM-NEGRA"
                            and i["sessao"] == "Asia"
                            and i["extremo_ema50"] == 1
                            and i["bb_extremo"] == 1),
    },
    {
        "nome": "EURJPY M1 HARAMI-BAIXA NY-abertura bb=1 stoch=1", "par": "EURJPY", "tf": 1, "nivel": 1,
        "check": lambda i: (i["padrao"] == "HARAMI-BAIXA"
                            and i["sessao"] == "NY-abertura"
                            and i["bb_extremo"] == 1
                            and i["stoch_extremo"] == 1),
    },
    {
        "nome": "USDJPY M1 NUVEM-NEGRA Londres stoch_extremo=1", "par": "USDJPY", "tf": 1, "nivel": 1,
        "check": lambda i: (i["padrao"] == "NUVEM-NEGRA"
                            and i["sessao"] == "Londres"
                            and i["stoch_extremo"] == 1),
    },
    {
        "nome": "USDJPY M1 NUVEM-NEGRA Londres stoch_virando=1", "par": "USDJPY", "tf": 1, "nivel": 1,
        "check": lambda i: (i["padrao"] == "NUVEM-NEGRA"
                            and i["sessao"] == "Londres"
                            and i["stoch_virando"] == 1),
    },
    {
        "nome": "GBPUSD M1 DIV-RSI-BEAR Londres-abertura bb=1 stoch=0", "par": "GBPUSD", "tf": 1, "nivel": 1,
        "check": lambda i: (i["sinal"] == "DIV-RSI-BEAR"
                            and i["sessao"] == "Londres-abertura"
                            and i["bb_extremo"] == 1
                            and i["stoch_extremo"] == 0),
    },
    {
        "nome": "GBPUSD M1 NUVEM-NEGRA NY-abertura stoch=1", "par": "GBPUSD", "tf": 1, "nivel": 1,
        "check": lambda i: (i["padrao"] == "NUVEM-NEGRA"
                            and i["sessao"] == "NY-abertura"
                            and i["stoch_extremo"] == 1),
    },
    # ── M30 — exclusivo Deriv (IQ Option não suporta) ─────────────────────────
    # Walk-forward 2019-2025, break-even 54.9%
    {
        "nome": "USDJPY M30 ENGOLFO-BAIXA Londres-abertura stoch_virando=0", "par": "USDJPY", "tf": 30, "nivel": 1,
        "check": lambda i: (i["padrao"] == "ENGOLFO-BAIXA"
                            and i["sessao"] == "Londres-abertura"
                            and i["stoch_virando"] == 0),
    },
    {
        "nome": "USDJPY M30 TRESSOLDADOS NY-abertura ema50=1", "par": "USDJPY", "tf": 30, "nivel": 1,
        "check": lambda i: (i["padrao"] == "TRESSOLDADOS"
                            and i["sessao"] == "NY-abertura"
                            and i["extremo_ema50"] == 1),
    },
    {
        "nome": "EURJPY M30 TRESSOLDADOS NY ema50=1", "par": "EURJPY", "tf": 30, "nivel": 1,
        "check": lambda i: (i["padrao"] == "TRESSOLDADOS"
                            and i["sessao"] == "NY"
                            and i["extremo_ema50"] == 1),
    },
    {
        "nome": "EURJPY M30 TRESSOLDADOS NY", "par": "EURJPY", "tf": 30, "nivel": 1,
        "check": lambda i: (i["padrao"] == "TRESSOLDADOS"
                            and i["sessao"] == "NY"),
    },
    {
        "nome": "EURJPY M30 MORNING-STAR Londres", "par": "EURJPY", "tf": 30, "nivel": 1,
        "check": lambda i: (i["padrao"] == "MORNING-STAR"
                            and i["sessao"] == "Londres"),
    },
    {
        "nome": "EURUSD M30 TRESCORVOS Londres-abertura stoch=0", "par": "EURUSD", "tf": 30, "nivel": 1,
        "check": lambda i: (i["padrao"] == "TRESCORVOS"
                            and i["sessao"] == "Londres-abertura"
                            and i["stoch_extremo"] == 0),
    },
    # ── H1 — exclusivo Deriv ──────────────────────────────────────────────────
    # Walk-forward 2019-2025, break-even 54.9%
    {
        "nome": "USDJPY H1 MORNING-STAR Ásia macd=0", "par": "USDJPY", "tf": 60, "nivel": 2,
        "check": lambda i: (i["padrao"] == "MORNING-STAR"
                            and i["sessao"] == "Asia"
                            and i["macd_confirmado"] == 0),
    },
    {
        "nome": "EURJPY H1 ENGOLFO-BAIXA Ásia ema50=1", "par": "EURJPY", "tf": 60, "nivel": 1,
        "check": lambda i: (i["padrao"] == "ENGOLFO-BAIXA"
                            and i["sessao"] == "Asia"
                            and i["extremo_ema50"] == 1),
    },
    {
        "nome": "USDJPY H1 EVENING-STAR Londres-abertura bb=0", "par": "USDJPY", "tf": 60, "nivel": 1,
        "check": lambda i: (i["padrao"] == "EVENING-STAR"
                            and i["sessao"] == "Londres-abertura"
                            and i["bb_extremo"] == 0),
    },
    {
        "nome": "USDJPY H1 HARAMI-ALTA NY", "par": "USDJPY", "tf": 60, "nivel": 1,
        "check": lambda i: (i["padrao"] == "HARAMI-ALTA"
                            and i["sessao"] == "NY"),
    },
    {
        "nome": "EURUSD H1 TRESCORVOS Ásia macd=0", "par": "EURUSD", "tf": 60, "nivel": 1,
        "check": lambda i: (i["padrao"] == "TRESCORVOS"
                            and i["sessao"] == "Asia"
                            and i["macd_confirmado"] == 0),
    },
    {
        "nome": "GBPUSD H1 HARAMI-ALTA Ásia macd=0", "par": "GBPUSD", "tf": 60, "nivel": 1,
        "check": lambda i: (i["padrao"] == "HARAMI-ALTA"
                            and i["sessao"] == "Asia"
                            and i["macd_confirmado"] == 0),
    },
    {
        "nome": "EURJPY H1 TRESSOLDADOS Ásia", "par": "EURJPY", "tf": 60, "nivel": 1,
        "check": lambda i: (i["padrao"] == "TRESSOLDADOS"
                            and i["sessao"] == "Asia"),
    },
    {
        "nome": "EURGBP H1 MORNING-STAR Ásia macd=0", "par": "EURGBP", "tf": 60, "nivel": 1,
        "check": lambda i: (i["padrao"] == "MORNING-STAR"
                            and i["sessao"] == "Asia"
                            and i["macd_confirmado"] == 0),
    },
    # ── H4 — exclusivo Deriv ──────────────────────────────────────────────────
    # Walk-forward 2019-2025, break-even 54.9%
    {
        "nome": "USDJPY H4 MORNING-STAR Ásia ema50=0", "par": "USDJPY", "tf": 240, "nivel": 1,
        "check": lambda i: (i["padrao"] == "MORNING-STAR"
                            and i["sessao"] == "Asia"
                            and i["extremo_ema50"] == 0),
    },
    {
        "nome": "EURJPY H4 EVENING-STAR Ásia stoch_virando=0", "par": "EURJPY", "tf": 240, "nivel": 1,
        "check": lambda i: (i["padrao"] == "EVENING-STAR"
                            and i["sessao"] == "Asia"
                            and i["stoch_virando"] == 0),
    },
    {
        "nome": "EURUSD H4 TRESCORVOS Ásia", "par": "EURUSD", "tf": 240, "nivel": 1,
        "check": lambda i: (i["padrao"] == "TRESCORVOS"
                            and i["sessao"] == "Asia"),
    },
    # ── H1 novos — busca ampla 2019-2025 ─────────────────────────────────────
    {
        "nome": "GBPUSD H1 DIV-RSI-BULL NY", "par": "GBPUSD", "tf": 60, "nivel": 2,
        "check": lambda i: (i["sinal"] == "DIV-RSI-BULL"
                            and i["sessao"] == "NY"),
    },
    {
        "nome": "USDJPY H1 DIV-RSI-BULL Ásia bb=1", "par": "USDJPY", "tf": 60, "nivel": 2,
        "check": lambda i: (i["sinal"] == "DIV-RSI-BULL"
                            and i["sessao"] == "Asia"
                            and i["bb_extremo"] == 1),
    },
    {
        "nome": "EURUSD H1 MORNING-STAR Londres-abertura bb=0", "par": "EURUSD", "tf": 60, "nivel": 1,
        "check": lambda i: (i["padrao"] == "MORNING-STAR"
                            and i["sessao"] == "Londres-abertura"
                            and i["bb_extremo"] == 0),
    },
    {
        "nome": "EURUSD H1 DIV-RSI-BEAR Ásia ema50=1", "par": "EURUSD", "tf": 60, "nivel": 1,
        "check": lambda i: (i["sinal"] == "DIV-RSI-BEAR"
                            and i["sessao"] == "Asia"
                            and i["extremo_ema50"] == 1),
    },
    {
        "nome": "USDJPY H1 PDV-S4-RSI Londres", "par": "USDJPY", "tf": 60, "nivel": 1,
        "check": lambda i: (i["sinal"] == "PDV-S4-RSI"
                            and i["sessao"] == "Londres"),
    },
    # ── H4 novos — busca ampla 2019-2025 ─────────────────────────────────────
    {
        "nome": "GBPUSD H4 DIV-RSI-BULL Ásia", "par": "GBPUSD", "tf": 240, "nivel": 1,
        "check": lambda i: (i["sinal"] == "DIV-RSI-BULL"
                            and i["sessao"] == "Asia"),
    },
    {
        "nome": "EURUSD H4 DIV-RSI-BEAR Londres-abertura", "par": "EURUSD", "tf": 240, "nivel": 1,
        "check": lambda i: (i["sinal"] == "DIV-RSI-BEAR"
                            and i["sessao"] == "Londres-abertura"),
    },
    {
        "nome": "USDJPY H4 PDV-S4-RSI Londres-abertura macd=0", "par": "USDJPY", "tf": 240, "nivel": 1,
        "check": lambda i: (i["sinal"] == "PDV-S4-RSI"
                            and i["sessao"] == "Londres-abertura"
                            and i["macd_confirmado"] == 0),
    },
    {
        "nome": "EURJPY H4 PDV-S4-RSI NY-abertura", "par": "EURJPY", "tf": 240, "nivel": 1,
        "check": lambda i: (i["sinal"] == "PDV-S4-RSI"
                            and i["sessao"] == "NY-abertura"),
    },
    {
        "nome": "USDJPY H4 PIN-CALL Ásia macd=0", "par": "USDJPY", "tf": 240, "nivel": 1,
        "check": lambda i: (i["sinal"] == "PIN-CALL"
                            and i["sessao"] == "Asia"
                            and i["macd_confirmado"] == 0),
    },
]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%d/%m %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "bot_deriv.log"),
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger(__name__)


# ── Divergência RSI (live) ────────────────────────────────────────────────────

def _divergencia_rsi_live(close: pd.Series, rsi: pd.Series, janela: int = 20) -> tuple:
    cls = close.iloc[-janela:].values
    rst = rsi.iloc[-janela:].values
    if len(cls) < 10 or np.any(np.isnan(rst)):
        return "null", "NENHUM"
    cur_c, cur_r = cls[-1], rst[-1]
    prev = cls[:-3]
    if len(prev) == 0:
        return "null", "NENHUM"
    min_i = int(np.argmin(prev))
    max_i = int(np.argmax(prev))
    if cur_c <= prev[min_i] and rst[min_i] < cur_r and cur_r < 40:
        return "call", "DIV-RSI-BULL"
    if cur_c >= prev[max_i] and rst[max_i] > cur_r and cur_r > 60:
        return "put", "DIV-RSI-BEAR"
    return "null", "NENHUM"


# ── Indicadores + padrões ─────────────────────────────────────────────────────

def calcular_tudo(velas: list):
    """
    Recebe lista de velas no formato Deriv normalizado:
    [{"open", "close", "high", "low", "volume", "epoch"}, ...]
    """
    if len(velas) < 210:
        return None

    close  = pd.Series([v["close"]  for v in velas], dtype=float)
    high   = pd.Series([v["high"]   for v in velas], dtype=float)
    low    = pd.Series([v["low"]    for v in velas], dtype=float)
    volume = pd.Series([v["volume"] for v in velas], dtype=float)  # sempre 0 em forex Deriv
    open_  = pd.Series([v["open"]   for v in velas], dtype=float)

    rsi14   = ta.momentum.RSIIndicator(close, window=14).rsi()
    stoch   = ta.momentum.StochasticOscillator(high, low, close, 14, 3)
    stoch_k = stoch.stoch()
    stoch_d = stoch.stoch_signal()
    macd_i  = ta.trend.MACD(close)
    macd    = macd_i.macd()
    macd_s  = macd_i.macd_signal()
    bb      = ta.volatility.BollingerBands(close, 20, 2)
    bb_u    = bb.bollinger_hband()
    bb_l    = bb.bollinger_lband()
    ema20   = ta.trend.EMAIndicator(close, 20).ema_indicator()
    ema50   = ta.trend.EMAIndicator(close, 50).ema_indicator()
    ema200  = ta.trend.EMAIndicator(close, 200).ema_indicator()

    i = -2  # última vela fechada
    c   = close.iloc[i]
    rsi = rsi14.iloc[i]
    sk  = stoch_k.iloc[i]
    sd  = stoch_d.iloc[i]

    if pd.isna(rsi) or pd.isna(ema200.iloc[i]):
        return None

    sk_p = stoch_k.iloc[i - 1]
    sd_p = stoch_d.iloc[i - 1]
    stoch_virando = int(
        (sk_p < sd_p and sk > sd and sk_p < 20) or
        (sk_p > sd_p and sk < sd and sk_p > 80)
    )
    stoch_extremo = int(sk > 80 or sk < 20)

    bb_pct    = (c - bb_l.iloc[i]) / (bb_u.iloc[i] - bb_l.iloc[i] + 1e-9)
    bb_extremo = int(bb_pct > 0.85 or bb_pct < 0.15)

    mv, ms     = macd.iloc[i], macd_s.iloc[i]
    mv_p, ms_p = macd.iloc[i - 1], macd_s.iloc[i - 1]
    macd_confirmado = int((mv > ms and mv_p > ms_p) or (mv < ms and mv_p < ms_p))

    e50 = ema50.iloc[i]
    extremo_ema50 = int(c > e50 * 1.003 or c < e50 * 0.997)

    vol_medio = volume.rolling(20).mean().iloc[i]
    vol_v2    = volume.iloc[i]
    vol_v3    = volume.iloc[i - 1]

    def vela(idx):
        return {
            "open":  open_.iloc[idx],
            "close": close.iloc[idx],
            "high":  high.iloc[idx],
            "low":   low.iloc[idx],
        }

    c2, c3, c4 = vela(i), vela(i - 1), vela(i - 2)
    corv2 = cor_vela(c2["open"], c2["close"])
    corv3 = cor_vela(c3["open"], c3["close"])
    corv4 = cor_vela(c4["open"], c4["close"])

    padrao, direcao_padrao = detectar_padrao_confirmado(
        corv2, c2["open"], c2["close"], c2["low"], c2["high"],
        corv3, c3["open"], c3["close"],
        corv4, c4["open"], c4["close"],
    )

    if padrao in ("ALEATORIO", "NENHUM"):
        mes_dir, mes_nome = detectar_morning_evening_star(c2, c3, c4)
        if mes_dir != "null":
            padrao, direcao_padrao = mes_nome, mes_dir

    pin_dir, pin_sinal = detectar_pin_bar(c2["open"], c2["high"], c2["low"], c2["close"])

    direcao_ok, sinal = sinais_padrao_vela(rsi, direcao_padrao, vol_medio, vol_v2, vol_v3, corv2, corv3)

    if direcao_ok == "null":
        if padrao in ("MORNING-STAR", "EVENING-STAR"):
            direcao_ok, sinal = direcao_padrao, padrao
        elif pin_dir != "null":
            direcao_ok, sinal = pin_dir, pin_sinal
        else:
            direcao_ok, sinal = sinais_dinamicos(rsi, vol_medio, vol_v2, vol_v3, corv2, corv3)

    if direcao_ok == "null":
        doji_dir, doji_nome = detectar_doji_extremo(c2, rsi)
        if doji_dir != "null":
            direcao_ok, sinal = doji_dir, doji_nome
            padrao = doji_nome

    if direcao_ok == "null":
        div_dir, div_sinal = _divergencia_rsi_live(close, rsi14)
        if div_dir != "null":
            direcao_ok, sinal = div_dir, div_sinal

    hora_utc = datetime.fromtimestamp(velas[i]["epoch"], tz=timezone.utc).hour

    return {
        "padrao":          padrao,
        "sinal":           sinal,
        "direcao":         direcao_ok,
        "rsi":             float(rsi),
        "stoch_k":         float(sk),
        "bb_pct":          float(bb_pct),
        "hora":            hora_utc,
        "sessao":          classificar_sessao(hora_utc),
        "stoch_virando":   stoch_virando,
        "stoch_extremo":   stoch_extremo,
        "bb_extremo":      bb_extremo,
        "macd_confirmado": macd_confirmado,
        "extremo_ema50":   extremo_ema50,
    }


# ── Gestão de banca ───────────────────────────────────────────────────────────

class GestorBanca:
    def __init__(self, frac: float, stop_pct: float):
        self.frac              = frac
        self.stop_pct          = stop_pct
        self.banca_ini_dia     = None
        self.perda_dia         = 0.0
        self.lucro_dia         = 0.0
        self.em_recuperacao    = False
        self.nivel_recuperacao = 0
        self.valor_recuperar   = 0.0

    def iniciar_dia(self, banca: float):
        self.banca_ini_dia     = banca
        self.perda_dia         = 0.0
        self.lucro_dia         = 0.0
        self.em_recuperacao    = False
        self.nivel_recuperacao = 0
        self.valor_recuperar   = 0.0

    def pode_operar(self) -> bool:
        if self.banca_ini_dia is None:
            return True
        return self.perda_dia < self.banca_ini_dia * self.stop_pct

    def proxima_aposta(self, banca_atual: float, nivel: int) -> float:
        if not self.em_recuperacao:
            return max(round(banca_atual * self.frac, 2), 1.0)
        return max(round(self.valor_recuperar / 2 * 1.3, 2), 1.0)

    def registrar_resultado(self, lucro: float, nivel: int):
        if lucro > 0:
            self.lucro_dia += lucro
            if self.em_recuperacao:
                self.nivel_recuperacao -= 1
                if self.nivel_recuperacao <= 0:
                    self.em_recuperacao  = False
                    self.valor_recuperar = 0.0
        else:
            self.perda_dia += abs(lucro)
            max_niveis = 2 if nivel >= 1 else 1
            if self.nivel_recuperacao < max_niveis:
                self.em_recuperacao     = True
                self.nivel_recuperacao += 1
                self.valor_recuperar   += abs(lucro)
            else:
                self.em_recuperacao    = False
                self.nivel_recuperacao = 0
                self.valor_recuperar   = 0.0

    @property
    def saldo_dia(self) -> float:
        return self.lucro_dia - self.perda_dia

    def to_dict(self) -> dict:
        return {
            "banca_ini_dia":     self.banca_ini_dia,
            "perda_dia":         self.perda_dia,
            "lucro_dia":         self.lucro_dia,
            "em_recuperacao":    self.em_recuperacao,
            "nivel_recuperacao": self.nivel_recuperacao,
            "valor_recuperar":   self.valor_recuperar,
        }

    def from_dict(self, d: dict):
        self.banca_ini_dia     = d.get("banca_ini_dia")
        self.perda_dia         = d.get("perda_dia", 0.0)
        self.lucro_dia         = d.get("lucro_dia", 0.0)
        self.em_recuperacao    = d.get("em_recuperacao", False)
        self.nivel_recuperacao = d.get("nivel_recuperacao", 0)
        self.valor_recuperar   = d.get("valor_recuperar", 0.0)


# ── Bot principal ─────────────────────────────────────────────────────────────

class DerivBot:
    def __init__(self):
        self.gestor      = GestorBanca(FRAC_BANCA, STOP_LOSS_PCT)
        self.ultima_vela = {}   # (par, tf) → epoch da última vela processada
        self.ops_total   = 0
        self.wins        = 0
        self.currency    = "USD"
        self.ws          = None
        self._req_id     = 0

        self._regras_idx: dict = {}
        for r in REGRAS:
            self._regras_idx.setdefault((r["par"], r["tf"]), []).append(r)

        self._carregar_estado()

    # ── WebSocket ─────────────────────────────────────────────────────────────

    async def _req(self, payload: dict) -> dict:
        self._req_id += 1
        payload["req_id"] = self._req_id
        await self.ws.send(json.dumps(payload))
        while True:
            raw = await self.ws.recv()
            msg = json.loads(raw)
            if msg.get("req_id") == self._req_id:
                return msg

    async def conectar(self):
        log.info("Conectando à Deriv...")
        self.ws = await websockets.connect(WS_ENDPOINT, ping_interval=30, ping_timeout=10)

        resp = await self._req({"authorize": TOKEN})
        if "error" in resp:
            sys.exit(f"Erro de autenticação: {resp['error']['message']}")

        auth = resp["authorize"]
        self.currency = auth["currency"]
        banca = float(auth["balance"])
        modo  = "DEMO" if DEMO_MODE else "REAL"

        self.gestor.iniciar_dia(banca)
        log.info(
            f"Conectado! Conta: {auth['loginid']} | Modo: {modo} | "
            f"Banca: {self.currency} {banca:.2f} | "
            f"Aposta: {self.currency} {banca * FRAC_BANCA:.2f} | "
            f"Stop diário: {self.currency} {banca * STOP_LOSS_PCT:.2f}"
        )

    async def _buscar_velas(self, par: str, tf: int) -> list:
        symbol = SYMBOL[par]
        resp = await self._req({
            "ticks_history": symbol,
            "count":         VELAS_Q,
            "end":           "latest",
            "granularity":   GRANULARITY[tf],
            "style":         "candles",
        })
        if "error" in resp:
            raise ValueError(resp["error"]["message"])
        # Normaliza para formato interno
        return [{
            "open":   float(c["open"]),
            "close":  float(c["close"]),
            "high":   float(c["high"]),
            "low":    float(c["low"]),
            "volume": 0.0,
            "epoch":  int(c["epoch"]),
        } for c in resp["candles"]]

    async def _comprar(self, par: str, tf: int, direcao: str, aposta: float) -> float:
        """Abre contrato e aguarda resultado. Retorna lucro (positivo ou negativo)."""
        symbol = SYMBOL[par]
        contract_type = "CALL" if direcao == "call" else "PUT"

        # Proposal — verificar payout antes de comprar
        prop_resp = await self._req({
            "proposal":       1,
            "amount":         aposta,
            "basis":          "stake",
            "contract_type":  contract_type,
            "currency":       self.currency,
            "duration":       tf,
            "duration_unit":  "m",
            "symbol":         symbol,
        })

        if "error" in prop_resp:
            log.error(f"Proposal error {par} M{tf}: {prop_resp['error']['message']}")
            return 0.0

        prop       = prop_resp["proposal"]
        ask_price  = float(prop["ask_price"])
        payout_val = float(prop["payout"])
        payout_pct = (payout_val - ask_price) / ask_price

        if payout_pct < PAYOUT_MIN:
            log.warning(
                f"Payout {payout_pct:.1%} < mínimo {PAYOUT_MIN:.1%} em {par} M{tf} — ignorando"
            )
            return 0.0

        # Comprar
        buy_resp = await self._req({
            "buy":   prop["id"],
            "price": aposta,
        })

        if "error" in buy_resp:
            log.error(f"Buy error {par} M{tf}: {buy_resp['error']['message']}")
            return 0.0

        contract_id = buy_resp["buy"]["contract_id"]
        log.info(
            f"  Aberto #{contract_id} | payout {payout_pct:.1%} | "
            f"expira em {tf}min"
        )

        # Aguardar resultado
        while True:
            await asyncio.sleep(5)
            chk = await self._req({
                "proposal_open_contract": 1,
                "contract_id":            contract_id,
            })
            if "error" in chk:
                await asyncio.sleep(10)
                continue
            poc = chk.get("proposal_open_contract", {})
            if poc.get("is_expired") or poc.get("is_sold"):
                return float(poc.get("profit", 0))

    async def _executar(self, par: str, tf: int, nivel: int, direcao: str, nome: str):
        if not self.gestor.pode_operar():
            log.warning(
                f"Stop-loss diário atingido "
                f"(perda {self.currency} {self.gestor.perda_dia:.2f} / "
                f"limite {self.currency} {self.gestor.banca_ini_dia * STOP_LOSS_PCT:.2f})"
            )
            return

        banca_resp = await self._req({"balance": 1})
        banca      = float(banca_resp["balance"]["balance"])
        aposta     = self.gestor.proxima_aposta(banca, nivel)

        log.info(
            f"▶ [{nivel}] {nome}  {direcao.upper()}  "
            f"{self.currency} {aposta:.2f}  M{tf}  banca={self.currency} {banca:.2f}"
        )

        lucro = await self._comprar(par, tf, direcao, aposta)
        if lucro == 0.0 and not self.gestor.em_recuperacao:
            return  # proposta recusada ou erro — não registrar como loss

        lucro = round(lucro, 2)
        self.gestor.registrar_resultado(lucro, nivel)
        self.ops_total += 1
        if lucro > 0:
            self.wins += 1

        wr_str = f"{self.wins/self.ops_total:.1%} ({self.wins}/{self.ops_total})"
        if lucro > 0:
            log.info(f"  ✔ WIN  +{self.currency} {lucro:.2f} | dia: {self.gestor.saldo_dia:+.2f} | WR: {wr_str}")
        else:
            log.info(f"  ✘ LOSS  {self.currency} {lucro:.2f} | dia: {self.gestor.saldo_dia:+.2f} | WR: {wr_str}")
            if self.gestor.em_recuperacao:
                log.info(
                    f"  ↩ Recuperação nível {self.gestor.nivel_recuperacao} "
                    f"(recuperar {self.currency} {self.gestor.valor_recuperar:.2f})"
                )

        self._salvar_estado()

    # ── Persistência ──────────────────────────────────────────────────────────

    def _salvar_estado(self):
        estado = {
            "gestor":    self.gestor.to_dict(),
            "ops_total": self.ops_total,
            "wins":      self.wins,
            "ultima_vela": {f"{p}|{t}": v for (p, t), v in self.ultima_vela.items()},
            "dia":       datetime.now().day,
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(estado, f)
        except Exception as e:
            log.warning(f"Falha ao salvar estado: {e}")

    def _carregar_estado(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                estado = json.load(f)
        except Exception:
            return
        if estado.get("dia") != datetime.now().day:
            log.info("Estado salvo é de outro dia — iniciando zerado.")
            return
        self.gestor.from_dict(estado.get("gestor", {}))
        self.ops_total = estado.get("ops_total", 0)
        self.wins      = estado.get("wins", 0)
        for key, val in estado.get("ultima_vela", {}).items():
            par, tf_str = key.split("|")
            self.ultima_vela[(par, int(tf_str))] = val
        if self.gestor.em_recuperacao:
            log.info(
                f"Estado restaurado — Recuperação nível {self.gestor.nivel_recuperacao} "
                f"(recuperar {self.currency} {self.gestor.valor_recuperar:.2f})"
            )
        else:
            log.info(
                f"Estado restaurado — ops={self.ops_total} wins={self.wins} "
                f"saldo_dia={self.gestor.saldo_dia:+.2f}"
            )

    # ── Loop principal ────────────────────────────────────────────────────────

    async def loop(self):
        await self.conectar()
        log.info(f"Monitorando {len(ALVOS)} alvos | {len(REGRAS)} regras")
        log.info(f"Aposta: {FRAC_BANCA*100:.2f}% da banca | Stop: {STOP_LOSS_PCT*100:.0f}% | Payout mín: {PAYOUT_MIN*100:.0f}%")
        log.info("=" * 60)

        ultimo_dia = datetime.now().day

        while True:
            # Reset diário
            dia_atual = datetime.now().day
            if dia_atual != ultimo_dia:
                banca_resp = await self._req({"balance": 1})
                banca = float(banca_resp["balance"]["balance"])
                self.gestor.iniciar_dia(banca)
                self.ops_total = 0
                self.wins      = 0
                ultimo_dia     = dia_atual
                self._salvar_estado()
                log.info(
                    f"── Novo dia | Banca: {self.currency} {banca:.2f} | "
                    f"Aposta: {self.currency} {banca*FRAC_BANCA:.2f} | "
                    f"Stop: {self.currency} {banca*STOP_LOSS_PCT:.2f} ──"
                )

            for par, tf in ALVOS:
                regras_alvo = self._regras_idx.get((par, tf))
                if not regras_alvo:
                    continue

                try:
                    velas = await self._buscar_velas(par, tf)
                except Exception as e:
                    log.debug(f"{par} M{tf}: erro ao buscar velas — {e}")
                    continue

                # Detecta vela nova pelo epoch
                key   = (par, tf)
                epoch = velas[-2]["epoch"]
                if self.ultima_vela.get(key) == epoch:
                    continue
                self.ultima_vela[key] = epoch

                ind = calcular_tudo(velas)
                if ind is None or ind["direcao"] == "null":
                    continue

                matches = []
                for regra in regras_alvo:
                    try:
                        if regra["check"](ind):
                            matches.append(regra)
                    except Exception:
                        pass

                if not matches:
                    continue

                regra = max(matches, key=lambda r: r["nivel"])
                await self._executar(par, tf, regra["nivel"], ind["direcao"], regra["nome"])

            now_str = datetime.now().strftime("%H:%M:%S")
            print(
                f"  {now_str}  dia: {self.gestor.saldo_dia:+.2f}  "
                f"ops: {self.ops_total}  WR: {self.wins/max(self.ops_total,1):.1%}",
                end="\r",
            )
            await asyncio.sleep(10)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    bot = DerivBot()
    try:
        await bot.loop()
    except KeyboardInterrupt:
        log.info(
            f"\nBot encerrado. Ops: {bot.ops_total} | Wins: {bot.wins} | "
            f"Saldo dia: {bot.currency} {bot.gestor.saldo_dia:+.2f}"
        )
    except websockets.exceptions.ConnectionClosed as e:
        log.error(f"Conexão encerrada: {e} — reiniciando em 30s")
        await asyncio.sleep(30)
        await main()


if __name__ == "__main__":
    asyncio.run(main())
