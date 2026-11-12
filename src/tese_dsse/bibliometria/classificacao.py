"""Classificação temática transparente (regras por regex em título+resumo+tags).

Cada dimensão é um dicionário ``rótulo -> padrão``. As regras são deliberadamente
simples e auditáveis: o notebook mostra quantos itens cada regra pegou e quais
ficaram sem classe, para você ajustar os padrões em vez de confiar numa caixa-preta.
"""
from __future__ import annotations

import re

import pandas as pd

# --- Dimensões multi-rótulo (um trabalho pode ter vários) ---------------------
METODOS = {
    "WLS / Gauss-Newton": r"\bwls\b|weighted least|least[- ]squares|gauss[- ]newton|normal equation",
    "Kalman (KF/EKF/UKF)": r"kalman|\bekf\b|\bukf\b|unscented",
    "Aprendizado de máquina / DL": r"neural|deep learning|machine learning|\bcnn\b|\blstm\b|transformer|"
                                   r"graph neural|\bgnn\b|data[- ]driven|learning[- ]based|reinforcement",
    "Bayesiano / probabilístico": r"bayes|probabilistic|monte carlo|particle filter|gaussian process",
    "Otimização / robusto (LAV, Huber)": r"\blav\b|least absolute|huber|robust|\bwlav\b|convex|sdp|semidefinite",
    "Distribuído / ADMM": r"distributed|decentrali[sz]ed|\badmm\b|consensus|multi[- ]area|federated",
    "Pseudo-medidas / baixa observab.": r"pseudo[- ]?measure|pseudo[- ]?medi|load allocation|low observab",
}

PROBLEMAS = {
    "Detecção/identificação de bad data": r"bad data|gross error|outlier|chi[- ]?square|largest normali[sz]ed|"
                                          r"residual|innovation index|measurement error",
    "Erro de topologia": r"topology (error|identification|processing|detection)|breaker status|"
                         r"switch(ing)? status|network reconfig",
    "Erro de parâmetro": r"parameter (error|estimation|identification)|line parameter|impedance error",
    "Ataque cibernético (FDIA)": r"cyber|false data|\bfdia\b|malicious|attack|adversar|security",
    "Observabilidade": r"observab",
    "PMU / µPMU / sincrofasor": r"\bpmu\b|synchrophasor|micro[- ]?pmu|\bμpmu\b|\bupmu\b|wide[- ]area",
    "Medidores inteligentes (AMI)": r"smart meter|\bami\b|advanced metering",
    "Trifásico / desbalanceado": r"three[- ]phase|unbalanced|multiphase|per[- ]phase|asymmetric",
    "Recursos distribuídos (DER/EV/PV)": r"\bder\b|distributed (energy|generation)|photovoltaic|\bpv\b|"
                                         r"electric vehicle|renewable|microgrid|inverter",
}

# --- Dimensões single-label (prioridade na ordem) -----------------------------
_PARADIGMA = [
    ("Previsão-assistida / dinâmica", r"dynamic state estimation|forecasting[- ]aided|\bdse\b|"
                                      r"tracking state|short[- ]term.*dynamic|state[- ]transition|"
                                      r"kalman|dynamic (model|estimation)|real[- ]time tracking"),
    ("Estática (snapshot WLS)", r"static state estimation|snapshot|\bwls\b|weighted least|"
                                r"state estimat"),
]

_AGENTICO = r"multi[- ]?agent|agent[- ]based|\bagentic\b|\bllm\b|large language model|autonomous agent|" \
            r"\bagents?\b|\bmas\b"

_REDE = [
    ("Distribuição", r"distribution (system|network|grid|state)|\bdsse\b|\bdsse\b|feeder|lv network|"
                     r"low[- ]voltage|medium[- ]voltage|microgrid"),
    ("Transmissão", r"transmission|power system state estimation|\bpsse\b|\bscada\b|ieee \d+[- ]bus"),
]

_TIPO_ESTUDO = [
    ("Revisão / survey", r"\breview\b|survey|state[- ]of[- ]the[- ]art|tutorial|overview"),
    ("Livro / capítulo", r"^__book__$"),
]


def _texto(df: pd.DataFrame) -> pd.Series:
    return (df["title"].fillna("") + " . " + df["abstract"].fillna("") + " . "
            + df["tags"].apply(lambda t: " ; ".join(t) if isinstance(t, list) else str(t))).str.lower()


def _flag(txt: pd.Series, padrao: str) -> pd.Series:
    rx = re.compile(padrao, re.I)
    return txt.apply(lambda s: bool(rx.search(s)))


def _primeiro(txt: pd.Series, regras, padrao: str) -> pd.Series:
    def f(s: str) -> str:
        for rot, rx in regras:
            if re.search(rx, s, re.I):
                return rot
        return padrao
    return txt.apply(f)


def classificar(df: pd.DataFrame) -> pd.DataFrame:
    """Devolve ``df`` com colunas ``metodo:*``, ``problema:*``, ``paradigma``,
    ``agentico``, ``rede`` e ``tipo_estudo``."""
    out = df.copy()
    txt = _texto(out)
    for rot, rx in METODOS.items():
        out[f"metodo:{rot}"] = _flag(txt, rx)
    for rot, rx in PROBLEMAS.items():
        out[f"problema:{rot}"] = _flag(txt, rx)
    out["paradigma"] = _primeiro(txt, _PARADIGMA, "Não classificado")
    out["agentico"] = _flag(txt, _AGENTICO).map({True: "Agêntico / multiagente", False: "Não agêntico"})
    out["rede"] = _primeiro(txt, _REDE, "Não especificado")
    out["tipo_estudo"] = _primeiro(txt, _TIPO_ESTUDO, "Artigo técnico")
    out.loc[out["itemType"] == "book", "tipo_estudo"] = "Livro / capítulo"
    return out


def colunas(df: pd.DataFrame, prefixo: str) -> list[str]:
    return [c for c in df.columns if c.startswith(prefixo + ":")]


def auditoria(df: pd.DataFrame) -> pd.DataFrame:
    """Contagem por regra, para calibrar os padrões."""
    linhas = []
    for pref in ("metodo", "problema"):
        for c in colunas(df, pref):
            linhas.append((pref, c.split(":", 1)[1], int(df[c].sum())))
    return pd.DataFrame(linhas, columns=["dimensão", "regra", "n"]).sort_values(
        ["dimensão", "n"], ascending=[True, False])

