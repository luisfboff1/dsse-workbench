"""Carga do corpus bibliográfico a partir de uma coleção do Zotero.

Devolve um ``DataFrame`` normalizado (uma linha por trabalho) com cache em disco,
para que o notebook rode offline depois da primeira execução.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..zotero_integration import conectar_zotero

RAIZ = Path(__file__).resolve().parents[3]
DADOS = RAIZ / "pesquisa" / "revisao_bibliografica" / "data"

TIPOS_IGNORADOS = {"attachment", "note", "annotation"}


def _ano(data: str) -> int | None:
    m = re.search(r"(19|20)\d{2}", data or "")
    return int(m.group(0)) if m else None


def _doi(d: dict) -> str:
    doi = (d.get("DOI") or "").strip().lower()
    if not doi:
        m = re.search(r"10\.\d{4,9}/[^\s\"<>]+", d.get("url", "") + " " + d.get("extra", ""))
        doi = m.group(0).lower() if m else ""
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)


def _autores(d: dict) -> list[str]:
    out = []
    for c in d.get("creators", []):
        nome = c.get("name") or f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
        if nome:
            out.append(nome)
    return out


def _coletar_subcolecoes(zot, chave: str) -> list[str]:
    """Chave da coleção + todas as descendentes."""
    todas = zot.everything(zot.collections())
    filhos: dict[str, list[str]] = {}
    for c in todas:
        pai = c["data"].get("parentCollection")
        if pai:
            filhos.setdefault(pai, []).append(c["key"])
    fila, achadas = [chave], []
    while fila:
        atual = fila.pop()
        achadas.append(atual)
        fila.extend(filhos.get(atual, []))
    return achadas


def carregar_colecao(
    colecao: str = "VFE4S2IH",
    incluir_subcolecoes: bool = True,
    cache: bool = True,
    atualizar: bool = False,
) -> pd.DataFrame:
    """Lê itens de uma coleção Zotero (padrão: *State Estimation*).

    ``cache``/``atualizar``: usa/ignora o CSV em ``pesquisa/revisao_bibliografica/data``.
    """
    DADOS.mkdir(parents=True, exist_ok=True)
    arq = DADOS / f"corpus_zotero_{colecao}.json"
    if cache and arq.exists() and not atualizar:
        return pd.read_json(arq, orient="records")

    zot = conectar_zotero()
    chaves = _coletar_subcolecoes(zot, colecao) if incluir_subcolecoes else [colecao]
    vistos: dict[str, dict] = {}
    for ch in chaves:
        for it in zot.everything(zot.collection_items_top(ch)):
            d = it["data"]
            if d["itemType"] in TIPOS_IGNORADOS or not d.get("title"):
                continue
            vistos[it["key"]] = dict(
                key=it["key"],
                itemType=d["itemType"],
                title=d["title"].strip(),
                year=_ano(d.get("date", "")),
                doi=_doi(d),
                url=d.get("url", ""),
                venue=(d.get("publicationTitle") or d.get("proceedingsTitle")
                       or d.get("conferenceName") or d.get("bookTitle") or "").strip(),
                abstract=(d.get("abstractNote") or "").strip(),
                authors=_autores(d),
                tags=[t["tag"] for t in d.get("tags", [])],
            )
    df = pd.DataFrame(vistos.values()).sort_values(["year", "title"]).reset_index(drop=True)
    if cache:
        df.to_json(arq, orient="records", force_ascii=False, indent=1)
    return df

