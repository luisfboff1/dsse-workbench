"""Enriquecimento via OpenAlex: países/instituições, citações, keywords, referências.

O Zotero não guarda afiliação, então o mapa de países e a rede de
acoplamento bibliográfico dependem desta etapa. Resultados ficam em cache JSON
por item (``data/openalex_cache``), de modo que reexecuções são instantâneas.
"""
from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher

import pandas as pd
import requests

from .corpus import DADOS

API = "https://api.openalex.org/works"
CAMPOS = ("id,doi,title,publication_year,cited_by_count,type,authorships,keywords,"
          "topics,referenced_works,primary_location,open_access")
CACHE = DADOS / "openalex_cache"


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()


def _buscar(row: pd.Series, email: str | None) -> dict | None:
    params = {"select": CAMPOS}
    if email:
        params["mailto"] = email
    if row.doi:
        r = requests.get(f"{API}/doi:{row.doi}", params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
    # fallback: busca por título e confere similaridade
    p = dict(params, filter=f"title.search:{_norm(row.title)[:200]}", **{"per-page": 3})
    r = requests.get(API, params=p, timeout=30)
    if r.status_code == 200:
        for w in r.json().get("results", []):
            sim = SequenceMatcher(None, _norm(w.get("title")), _norm(row.title)).ratio()
            if sim > 0.9:
                return w
    return None


def _resumir(w: dict | None) -> dict:
    if not w:
        return dict(oa_id=None, cited_by=None, paises=[], instituicoes=[], oa_keywords=[],
                    oa_topics=[], referencias=[], oa_ok=False)
    inst, paises = [], []
    for a in w.get("authorships", []):
        for i in a.get("institutions", []):
            inst.append(i.get("display_name"))
            if i.get("country_code"):
                paises.append(i["country_code"])
        paises += [c for c in a.get("countries", []) if c]
    return dict(
        oa_id=w["id"].rsplit("/", 1)[-1],
        cited_by=w.get("cited_by_count"),
        paises=sorted(set(paises)),
        instituicoes=sorted({i for i in inst if i}),
        oa_keywords=[k["display_name"] for k in w.get("keywords", [])],
        oa_topics=[t["display_name"] for t in w.get("topics", [])],
        referencias=[r.rsplit("/", 1)[-1] for r in w.get("referenced_works", [])],
        oa_ok=True,
    )


def enriquecer(df: pd.DataFrame, email: str | None = None, atualizar: bool = False,
               pausa: float = 0.12) -> pd.DataFrame:
    """Anexa colunas OpenAlex a ``df`` (uma consulta por item, com cache)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    extra = []
    for row in df.itertuples():
        arq = CACHE / f"{row.key}.json"
        if arq.exists() and not atualizar:
            extra.append(json.loads(arq.read_text(encoding="utf-8")))
            continue
        try:
            res = _resumir(_buscar(pd.Series(row._asdict()), email))
        except requests.RequestException:
            res = _resumir(None)
            res["erro_rede"] = True
        if not res.get("erro_rede"):
            arq.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        extra.append(res)
        time.sleep(pausa)
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(extra)], axis=1)

