"""
sinais.py — Funções de detecção de padrões de vela e sinais.
Extraído de analise_m15.py. Sem dependência de CSV ou análise estatística.
"""


def cor_vela(o, c):
    if o > c: return "vermelha"
    if o < c: return "verde"
    return "doji"


def detectar_padrao_confirmado(corv2, openv2, closev2, mini_v2, maxi_v2,
                                corv3, openv3, closev3,
                                corv4, openv4, closev4):
    if corv4 == "vermelha" and corv3 == "verde" and corv2 == "verde":
        if openv4 < closev3 and closev4 > openv3:
            return "ENGOLFO-ALTA", "call"
        elif openv4 > closev3 and closev4 < openv3 and closev3 > closev4:
            return "HARAMI-ALTA", "call"
        elif openv4 > closev3 and closev4 > openv3 and closev3 > (((openv4 - closev4) / 2) + closev4):
            return "PERFURACAO-ALTA", "call"
        elif openv3 < openv2 < closev3:
            return "TRESSOLDADOS", "call"
        return "ALEATORIO", "null"
    elif corv4 == "verde" and corv3 == "vermelha" and corv2 == "vermelha":
        if closev4 < openv3 and openv4 > closev3:
            return "ENGOLFO-BAIXA", "put"
        elif closev4 > openv3 and openv4 < closev3 and openv3 > openv4:
            return "HARAMI-BAIXA", "put"
        elif closev4 < openv3 and openv4 < closev3 and closev3 < ((closev4 - openv4) / 2) + openv4:
            return "NUVEM-NEGRA", "put"
        elif closev3 < openv2 and closev2 < closev3:
            return "TRESCORVOS", "put"
        return "ALEATORIO", "null"
    elif corv4 == "vermelha" and corv3 == "vermelha" and corv2 == "verde":
        corpo = closev2 - openv2
        cauda = openv2 - mini_v2
        if corpo > 0 and cauda > 0 and (cauda / corpo) >= 6 and corpo >= cauda:
            return "MARTELO", "call"
        return "ALEATORIO", "null"
    elif corv4 == "verde" and corv3 == "verde" and corv2 == "vermelha":
        corpo = openv2 - closev2
        pavio = maxi_v2 - openv2
        if corpo > 0 and pavio > 0 and (pavio / corpo) >= 6 and corpo >= (closev2 - mini_v2):
            return "MARTELO-INV", "put"
        return "ALEATORIO", "null"
    return "ALEATORIO", "null"


def sinais_padrao_vela(rsi, direcao, vol_medio, vol_v2, vol_v3, corv2, corv3):
    if direcao == "put" and 69 < rsi < 76 and vol_medio < vol_v2 > vol_v3:
        return "put", "PDV-S1"
    elif direcao == "call" and 24 < rsi < 31 and vol_medio < vol_v2 > vol_v3:
        return "call", "PDV-S1"
    elif direcao == "put" and rsi > 75 and vol_medio < vol_v2 > vol_v3:
        return "put", "PDV-S2"
    elif direcao == "call" and rsi < 31 and vol_medio < vol_v2 > vol_v3:
        return "call", "PDV-S2"
    elif direcao == "put" and vol_medio < vol_v2 > vol_v3:
        return "put", "PDV-S3-VOL"
    elif direcao == "call" and vol_medio < vol_v2 > vol_v3:
        return "call", "PDV-S3-VOL"
    elif direcao == "put" and 75 > rsi > 55:
        return "put", "PDV-S4-RSI"
    elif direcao == "call" and 45 > rsi > 35:
        return "call", "PDV-S4-RSI"
    elif direcao == "put" and rsi < 35:
        return "put", "PDV-S5-RSI-INV"
    elif direcao == "call" and rsi > 75:
        return "call", "PDV-S5-RSI-INV"
    return "null", "NENHUM"


def sinais_dinamicos(rsi, vol_medio, vol_v2, vol_v3, corv2, corv3):
    # DNC-RSI+VOL requer volume real — nunca dispara com vol=0 (Deriv forex)
    if 69 < rsi and vol_medio < vol_v2 > vol_v3:
        return "put", "DNC-RSI+VOL"
    elif rsi < 31 and vol_medio < vol_v2 > vol_v3:
        return "call", "DNC-RSI+VOL"
    return "null", "NENHUM"


def detectar_morning_evening_star(c2, c3, c4):
    corpo4 = abs(c4["close"] - c4["open"])
    corpo3 = abs(c3["close"] - c3["open"])
    corpo2 = abs(c2["close"] - c2["open"])
    if corpo4 < 1e-8:
        return "null", "NENHUM"
    if corpo3 > corpo4 * 0.35:
        return "null", "NENHUM"
    if corpo2 < corpo4 * 0.50:
        return "null", "NENHUM"
    meio_c4 = (c4["open"] + c4["close"]) / 2
    if c4["close"] < c4["open"] and c2["close"] > c2["open"] and c2["close"] > meio_c4:
        return "call", "MORNING-STAR"
    if c4["close"] > c4["open"] and c2["close"] < c2["open"] and c2["close"] < meio_c4:
        return "put", "EVENING-STAR"
    return "null", "NENHUM"


def detectar_doji_extremo(c2, rsi):
    range_total = c2["high"] - c2["low"]
    if range_total < 1e-8:
        return "null", "NENHUM"
    if abs(c2["close"] - c2["open"]) / range_total > 0.15:
        return "null", "NENHUM"
    if rsi > 70:
        return "put", "DOJI-EXTREMO"
    if rsi < 30:
        return "call", "DOJI-EXTREMO"
    return "null", "NENHUM"


def detectar_pin_bar(o, h, l, c):
    corpo       = abs(c - o)
    range_total = h - l
    if range_total < 1e-8:
        return "null", "NENHUM"
    pavio_inf = min(o, c) - l
    pavio_sup = h - max(o, c)
    corpo_pct = corpo / range_total
    if pavio_inf >= 2.5 * max(corpo, 1e-8) and pavio_inf / range_total >= 0.55 and corpo_pct <= 0.35:
        return "call", "PIN-CALL"
    if pavio_sup >= 2.5 * max(corpo, 1e-8) and pavio_sup / range_total >= 0.55 and corpo_pct <= 0.35:
        return "put", "PIN-PUT"
    return "null", "NENHUM"


def classificar_sessao(hora_utc: int) -> str:
    if hora_utc >= 22 or hora_utc < 7:  return "Asia"
    if hora_utc < 10:                    return "Londres-abertura"
    if hora_utc < 13:                    return "Londres"
    if hora_utc < 17:                    return "NY-abertura"
    return "NY"
