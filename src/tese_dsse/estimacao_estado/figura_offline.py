"""Figura interativa da etapa offline do GLRT: S_l, M = (I-K) S_l e delta_l no
diagrama unifilar da rede, no mesmo desenho do app (ELK layered, ortogonal).

Uma fonte so para o notebook `notebooks/bad_data/2026-10-28_laco_bad_data_IEEE14_57.ipynb`
(`display(HTML(figura_offline(...)))`) e para o guia
`temas/bad_data/guia_metodo_glrt.html` (injetada por `scripts/figura_offline_glrt.py`).
O HTML/JS fica em `figura_offline.html`, ao lado; aqui so os dados. O layout sai de
`scripts/layout_unifilar_elk.mjs` (precisa de Node e de `app/frontend/node_modules`).
"""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import chi2

from .bad_data import hat_matrix
from .benchmark_identificacao import estimar

RAIZ = Path(__file__).resolve().parents[3]
TEMPLATE = Path(__file__).with_name("figura_offline.html")


def layout_unifilar(barras: list[int], ramos: list[dict], slack: int) -> dict:
    """`{"nos": {id: [x, y, w]}, "ramos": {key: [[x, y]...]}}` pelo ELK do app."""
    entrada = json.dumps({"barras": barras, "ramos": ramos, "slack": slack})
    out = subprocess.run(["node", str(RAIZ / "scripts" / "layout_unifilar_elk.mjs")], input=entrada,
                         capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


def dados_offline(net: Any, plan: list, S: dict[int, np.ndarray], delta: dict[int, float],
                  t_ref: float = 0.1, layout: dict | None = None,
                  rot_barra: dict[int, str] | None = None, rot_linha: dict[int, str] | None = None,
                  rot_trafo: dict[int, str] | None = None) -> dict:
    """Tudo o que a figura desenha, em JSON simples.

    `s` e `M` saem em desvios-padrao de cada medidor para um erro de `t_ref`
    (10%) no cadastro da linha: `t_ref * S_l 1 / sigma` e `t_ref * (I-K) S_l 1 / sigma`.
    `K` vem do estado verdadeiro (estimacao com as medidas sem ruido).
    Os fluxos do modo delta sao a coluna do PTDF DC para 1 MW entre as pontas da linha.
    `layout` no formato de `layout_unifilar` (o app manda o do proprio ELK; sem
    ele, chama o Node). `rot_barra`/`rot_linha`: numero exibido de cada barra e
    linha (o app numera a partir de 1); padrao, o indice do pandapower.
    """
    import pandapower as pp
    from pandapower.pypower.makePTDF import makePTDF

    mdl, _, H, W, _, _ = estimar(net, plan)
    sig = np.asarray(mdl.sigma, dtype=float)
    IK = np.eye(len(plan)) - hat_matrix(H, W)

    medidores = [{"k": m.kind, "e": int(m.element), "lado": m.side, "ramo": m.branch_kind} for m in plan]
    ramos = [{"key": f"L{l}", "tipo": "line", "id": int(l), "de": int(r.from_bus), "para": int(r.to_bus)}
             for l, r in net.line.iterrows() if r.in_service]
    ramos += [{"key": f"T{t}", "tipo": "trafo", "id": int(t), "de": int(r.hv_bus), "para": int(r.lv_bus)}
              for t, r in net.trafo.iterrows() if r.in_service]
    slack = int(net.ext_grid.bus.iloc[0])
    lay = layout or layout_unifilar([int(b) for b in net.bus.index],
                                    [{k: r[k] for k in ("key", "de", "para")} for r in ramos], slack)
    for r in ramos:  # ramo sem rota no layout recebido: reta entre as barras
        (x1, y1, w1), (x2, y2, w2) = lay["nos"][str(r["de"])], lay["nos"][str(r["para"])]
        r["rota"] = lay["ramos"].get(r["key"]) or [[x1 + w1 / 2, y1 + 8], [x2 + w2 / 2, y2]]

    # PTDF DC, na mesma ordem de `ramos`
    dc = deepcopy(net)
    pp.rundcpp(dc)
    ppc = dc._ppc
    ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"])
    lk = dc._pd2ppc_lookups["branch"]
    linha_ppc = {int(l): lk["line"][0] + k for k, l in enumerate(dc.line.index)}
    trafo_ppc = {int(t): lk["trafo"][0] + k for k, t in enumerate(dc.trafo.index)} if "trafo" in lk else {}
    idx_ppc = [linha_ppc[r["id"]] if r["tipo"] == "line" else trafo_ppc[r["id"]] for r in ramos]

    linhas = {}
    for l, Sl in S.items():
        s = Sl @ np.ones(Sl.shape[1])
        k = linha_ppc[int(l)]
        f, t = int(ppc["branch"][k, 0].real), int(ppc["branch"][k, 1].real)
        fluxos = ptdf[idx_ppc, f] - ptdf[idx_ppc, t]  # 1 MW entra em f e sai em t
        linhas[int(l)] = {"s": np.round(t_ref * s / sig, 3).tolist(),
                          "M": np.round(t_ref * (IK @ s) / sig, 3).tolist(),
                          "delta": round(float(delta[l]), 4),
                          "P_MW": round(float(net.res_line.at[l, "p_from_mw"]), 2),
                          "fluxos": np.round(fluxos, 3).tolist()}
    return {"nos": lay["nos"], "slack": slack,
            "rb": {str(b): str((rot_barra or {}).get(int(b), b)) for b in net.bus.index},
            "rl": {str(l): str((rot_linha or {}).get(int(l), l)) for l in net.line.index},
            # trafo: o app mostra o ramo com o id de linha do frontend (L..); sem mapa, T{indice}
            "rt": {str(t): ("L" + str(rot_trafo[int(t)]) if rot_trafo and int(t) in rot_trafo else "T" + str(t))
                   for t in net.trafo.index}, "geradores": sorted({int(b) for b in net.gen.bus}),
            "cargas": sorted({int(b) for b in net.load.bus}), "medidores": medidores, "ramos": ramos,
            "linhas": linhas, "t_ref": t_ref, "m": int(H.shape[0]), "n": int(H.shape[1]),
            "limiar": float(chi2.ppf(0.95, H.shape[0] - H.shape[1])),
            "unid": "pu" if float(net.sn_mva) == 1.0 else "MW"}  # a rede do app tem base 1 MVA: potencias em pu


def figura_offline(net: Any, plan: list, S: dict[int, np.ndarray], delta: dict[int, float],
                   uid: str = "nb", **kw) -> str:
    """HTML autocontido da figura (para `IPython.display.HTML` ou para colar numa pagina)."""
    dados = json.dumps(dados_offline(net, plan, S, delta, **kw), ensure_ascii=False)
    return TEMPLATE.read_text(encoding="utf-8").replace("__UID__", uid).replace("__DADOS__", dados)
