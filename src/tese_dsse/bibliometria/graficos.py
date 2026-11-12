"""Gráficos bibliométricos (estilo Biblioshiny) em Plotly + nuvem de palavras.

Todas as funções devolvem uma ``plotly.graph_objects.Figure`` (exceto
``nuvem_palavras``, que devolve ``matplotlib.figure.Figure``) e usam o mesmo
tema; ``salvar`` exporta HTML interativo e, se houver kaleido, PNG/SVG/PDF.
"""
from __future__ import annotations

import re
from collections import Counter
from itertools import combinations
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

PALETA = ["#1f4e79", "#e07b39", "#2a9d8f", "#c0392b", "#8e6bbf", "#7f8c8d",
          "#d4a017", "#17a2b8", "#6c8e3e", "#b5517a"]

pio.templates["tese"] = go.layout.Template(layout=dict(
    font=dict(family="Segoe UI, Helvetica, Arial", size=13, color="#222"),
    colorway=PALETA, paper_bgcolor="white", plot_bgcolor="white",
    title=dict(font=dict(size=18), x=0.01, xanchor="left"),
    xaxis=dict(showgrid=False, linecolor="#999", ticks="outside"),
    yaxis=dict(gridcolor="#eee", linecolor="#999", ticks="outside"),
    margin=dict(l=60, r=30, t=70, b=50), hoverlabel=dict(font_size=12),
))
pio.templates.default = "plotly_white+tese"

STOP = set("""the and for with from using based approach method methods analysis in of to a an on by via as at
is are be this that these those its their our we it or not can has have been which than into over under between
paper propose proposed presents present show shows results result study novel new also two one such both
different case cases system systems power electric electrical network networks grid grids model models
de da do dos das em para com uma um por como ao os as se que e o a use used used than more most
read carried out part real-life medical services ieee-""".split())
TAGS_RUIDO = {"to be read", "read", "toread", "unread"}  # etiquetas de fluxo do Zotero, não de conteúdo


# ------------------------------------------------------------------ utilitários
def salvar(fig, nome: str, pasta: str | Path, png: bool = True) -> None:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    if hasattr(fig, "write_html"):
        fig.write_html(pasta / f"{nome}.html", include_plotlyjs="cdn")
        if png:
            for ext in ("png", "svg", "pdf"):
                try:
                    fig.write_image(pasta / f"{nome}.{ext}", scale=2)
                except Exception:  # kaleido/Chrome ausente: só o HTML
                    break
    else:  # matplotlib
        for ext in ("png", "svg", "pdf"):
            fig.savefig(pasta / f"{nome}.{ext}", dpi=200, bbox_inches="tight")


def tokens(texto: str, ngram: int = 1) -> list[str]:
    pal = [p for p in re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", texto.lower())]
    if ngram == 1:
        return [p for p in pal if p not in STOP]
    out = []
    for i in range(len(pal) - ngram + 1):
        g = pal[i:i + ngram]
        if g[0] in STOP or g[-1] in STOP:
            continue
        out.append(" ".join(g))
    return out


def termos_por_doc(df: pd.DataFrame, ngram: int = 2, fontes=("title", "tags", "abstract"),
                   sinonimos: dict[str, str] | None = None) -> list[set[str]]:
    """Conjunto de termos por trabalho (presença, não frequência)."""
    sin = sinonimos or {}
    docs = []
    for _, r in df.iterrows():
        t: list[str] = []
        for f in fontes:
            v = r[f]
            v = "; ".join(v) if isinstance(v, list) else str(v or "")
            if f == "tags":  # tags já são termos curados
                t += [x.strip().lower() for x in v.split(";")
                      if x.strip() and x.strip().lower() not in TAGS_RUIDO]
            else:
                t += tokens(v, ngram)
        docs.append({sin.get(x, x) for x in t})
    return docs


def _contagem(series_of_lists) -> pd.Series:
    c = Counter(x for l in series_of_lists for x in set(l))
    return pd.Series(c).sort_values(ascending=False)


# ------------------------------------------------------------------ produção
def producao_anual(df: pd.DataFrame) -> go.Figure:
    s = df["year"].dropna().astype(int).value_counts().sort_index()
    s = s.reindex(range(s.index.min(), s.index.max() + 1), fill_value=0)
    fig = go.Figure()
    fig.add_bar(x=s.index, y=s.values, name="Publicações/ano", marker_color=PALETA[0])
    fig.add_scatter(x=s.index, y=s.cumsum(), name="Acumulado", yaxis="y2",
                    line=dict(color=PALETA[1], width=3))
    fig.update_layout(title=f"Produção científica anual (n = {int(s.sum())})",
                      yaxis_title="Publicações", yaxis2=dict(overlaying="y", side="right",
                      title="Acumulado", showgrid=False), legend=dict(orientation="h", y=1.1, x=0.6))
    return fig


def barras_top(contagem: pd.Series, titulo: str, n: int = 15, cor: str = PALETA[0]) -> go.Figure:
    c = contagem.head(n)[::-1]
    fig = go.Figure(go.Bar(x=c.values, y=[(i[:60] + "…") if len(i) > 60 else i for i in c.index],
                           orientation="h", marker_color=cor, text=c.values, textposition="outside",
                           hovertext=list(c.index)))
    fig.update_layout(title=titulo, height=max(320, 26 * len(c) + 140), xaxis_title="Nº de trabalhos",
                      yaxis=dict(showgrid=False), margin=dict(l=300))
    return fig


def lei_lotka(df: pd.DataFrame) -> go.Figure:
    c = Counter(a for l in df["authors"] for a in l)
    freq = pd.Series(Counter(c.values())).sort_index()
    fig = go.Figure(go.Bar(x=freq.index, y=freq.values / freq.sum() * 100, marker_color=PALETA[2]))
    fig.update_layout(title="Produtividade dos autores (Lei de Lotka)",
                      xaxis_title="Nº de trabalhos do autor", yaxis_title="% dos autores",
                      yaxis_type="log")
    return fig


# ------------------------------------------------------------------ palavras
def nuvem_palavras(df: pd.DataFrame, ngram: int = 1, max_palavras: int = 120, sinonimos=None):
    import matplotlib.pyplot as plt
    from wordcloud import WordCloud
    cont = Counter(t for d in termos_por_doc(df, ngram, sinonimos=sinonimos) for t in d)
    cont = {k: v for k, v in cont.items() if v >= 2}
    wc = WordCloud(width=1600, height=800, background_color="white", colormap="viridis",
                   max_words=max_palavras, prefer_horizontal=0.9, relative_scaling=0.6,
                   collocations=False).generate_from_frequencies(cont)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title(f"Nuvem de {'palavras' if ngram == 1 else 'termos'} (resumo + título + tags)",
                 loc="left", fontsize=14)
    return fig


def tendencia_termos(df: pd.DataFrame, termos: list[str], ngram=2, sinonimos=None) -> go.Figure:
    """Evolução cumulativa de termos selecionados ao longo dos anos."""
    docs = termos_por_doc(df, ngram, sinonimos=sinonimos)
    anos = sorted(df["year"].dropna().astype(int).unique())
    fig = go.Figure()
    for t in termos:
        tem = np.array([t in d for d in docs])
        ys = [int(tem[(df["year"] <= a).values].sum()) for a in anos]
        fig.add_scatter(x=anos, y=ys, name=t, mode="lines+markers")
    fig.update_layout(title="Evolução temática (ocorrências cumulativas)", yaxis_title="Trabalhos")
    return fig


# ------------------------------------------------------------------ redes
def _rede_plotly(G: nx.Graph, titulo: str, rotulos_min_grau: int = 2) -> go.Figure:
    pos = nx.spring_layout(G, k=1.4 / np.sqrt(max(len(G), 1)), seed=7, weight="weight", iterations=200)
    comunidades = list(nx.community.greedy_modularity_communities(G, weight="weight"))
    cor = {n: PALETA[i % len(PALETA)] for i, c in enumerate(comunidades) for n in c}
    ex, ey = [], []
    for a, b in G.edges:
        ex += [pos[a][0], pos[b][0], None]
        ey += [pos[a][1], pos[b][1], None]
    fig = go.Figure(go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=0.6, color="#bbb"),
                               hoverinfo="none"))
    nodes = list(G.nodes)
    peso = np.array([G.nodes[n].get("freq", 1) for n in nodes], float)
    fig.add_scatter(x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes],
                    mode="markers+text",
                    marker=dict(size=10 + 28 * peso / peso.max(), color=[cor[n] for n in nodes],
                                line=dict(width=1, color="white"), opacity=0.9),
                    text=[n if G.degree[n] >= rotulos_min_grau else "" for n in nodes],
                    textposition="top center", textfont=dict(size=11),
                    hovertext=[f"{n}<br>{int(G.nodes[n].get('freq', 1))} trabalhos · grau {G.degree[n]}"
                               for n in nodes], hoverinfo="text")
    fig.update_layout(title=titulo, showlegend=False, height=720,
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def rede_coocorrencia(df: pd.DataFrame, ngram=1, top: int = 45, min_aresta: int = 2,
                      sinonimos=None, fontes=("title", "tags")) -> go.Figure:
    docs = termos_por_doc(df, ngram, fontes=fontes, sinonimos=sinonimos)
    freq = Counter(t for d in docs for t in d)
    manter = {t for t, _ in freq.most_common(top)}
    pares = Counter()
    for d in docs:
        for a, b in combinations(sorted(d & manter), 2):
            pares[(a, b)] += 1
    G = nx.Graph()
    for t in manter:
        G.add_node(t, freq=freq[t])
    G.add_weighted_edges_from([(a, b, w) for (a, b), w in pares.items() if w >= min_aresta])
    G.remove_nodes_from([n for n in list(G) if G.degree[n] == 0])
    return _rede_plotly(G, "Rede de co-ocorrência de termos (cores = comunidades temáticas)")


def rede_coautoria(df: pd.DataFrame, min_trabalhos: int = 2) -> go.Figure:
    n_aut = Counter(a for l in df["authors"] for a in set(l))
    manter = {a for a, c in n_aut.items() if c >= min_trabalhos}
    G = nx.Graph()
    for l in df["authors"]:
        for a, b in combinations(sorted(set(l) & manter), 2):
            w = G.get_edge_data(a, b, {"weight": 0})["weight"] + 1
            G.add_edge(a, b, weight=w)
    for a in G:
        G.nodes[a]["freq"] = n_aut[a]
    G.remove_nodes_from([n for n in list(G) if G.degree[n] == 0])
    return _rede_plotly(G, f"Rede de coautoria (autores com ≥ {min_trabalhos} trabalhos)", 1)


def acoplamento_bibliografico(df: pd.DataFrame, min_refs: int = 3) -> go.Figure:
    """Trabalhos ligados por referências em comum (requer enriquecimento OpenAlex)."""
    d = df[df["referencias"].apply(lambda r: isinstance(r, list) and len(r) > 0)]
    G = nx.Graph()
    for (_, a), (_, b) in combinations(d.iterrows(), 2):
        w = len(set(a.referencias) & set(b.referencias))
        if w >= min_refs:
            G.add_edge(a.key, b.key, weight=w)
    for k in G:
        r = d[d.key == k].iloc[0]
        G.nodes[k]["freq"] = max(r.cited_by or 1, 1)
    rot = {k: f"{d[d.key == k].iloc[0].authors[0].split()[-1] if d[d.key == k].iloc[0].authors else '?'} "
              f"{int(d[d.key == k].iloc[0].year)}" for k in G}
    G = nx.relabel_nodes(G, rot)
    return _rede_plotly(G, f"Acoplamento bibliográfico (≥ {min_refs} referências comuns)", 1)


# ------------------------------------------------------------------ geografia
def _iso3(cc: str) -> str | None:
    import pycountry
    try:
        return pycountry.countries.get(alpha_2=cc).alpha_3
    except AttributeError:
        return None


def mapa_paises(df: pd.DataFrame) -> go.Figure:
    c = _contagem(df["paises"].apply(lambda x: x if isinstance(x, list) else []))
    if c.empty:
        return go.Figure().update_layout(title="Sem dados de afiliação (rode o enriquecimento OpenAlex)")
    d = pd.DataFrame({"cc": c.index, "n": c.values})
    d["iso3"] = d.cc.map(_iso3)
    import pycountry
    d["pais"] = d.cc.map(lambda x: getattr(pycountry.countries.get(alpha_2=x), "name", x))
    fig = go.Figure(go.Choropleth(locations=d.iso3, z=d.n, text=d.pais, colorscale="Blues",
                                  marker_line_color="white", colorbar_title="Trabalhos",
                                  hovertemplate="%{text}: %{z} trabalhos<extra></extra>"))
    fig.update_layout(title="Origem geográfica das publicações (país das afiliações)",
                      geo=dict(showframe=False, projection_type="natural earth", showcountries=True,
                               countrycolor="#ddd", showland=True, landcolor="#f6f6f6"), height=520)
    return fig


def colaboracao_paises(df: pd.DataFrame, top: int = 15) -> go.Figure:
    """Matriz de colaboração entre países (coautoria internacional)."""
    pares, tot = Counter(), Counter()
    for l in df["paises"]:
        l = l if isinstance(l, list) else []
        tot.update(l)
        for a, b in combinations(sorted(l), 2):
            pares[(a, b)] += 1
    paises = [p for p, _ in tot.most_common(top)]
    m = pd.DataFrame(0, index=paises, columns=paises)
    for (a, b), w in pares.items():
        if a in m.index and b in m.index:
            m.loc[a, b] = m.loc[b, a] = w
    fig = go.Figure(go.Heatmap(z=m.values, x=paises, y=paises, colorscale="Blues",
                               hovertemplate="%{y} × %{x}: %{z}<extra></extra>"))
    fig.update_layout(title="Colaboração internacional (coautoria entre países)", height=560,
                      yaxis=dict(autorange="reversed"))
    return fig


# ------------------------------------------------------------------ taxonomias
def rosca(df: pd.DataFrame, coluna: str, titulo: str) -> go.Figure:
    c = df[coluna].value_counts()
    fig = go.Figure(go.Pie(labels=c.index, values=c.values, hole=0.55, sort=False,
                           marker=dict(colors=PALETA), textinfo="label+percent+value"))
    fig.update_layout(title=titulo, showlegend=False)
    return fig


def empilhado_por_ano(df: pd.DataFrame, coluna: str, titulo: str, passo: int = 5) -> go.Figure:
    d = df.dropna(subset=["year"]).copy()
    d["periodo"] = (d["year"].astype(int) // passo * passo).astype(str)
    t = pd.crosstab(d["periodo"], d[coluna])
    fig = go.Figure([go.Bar(name=c, x=t.index + "–", y=t[c]) for c in t.columns])
    fig.update_layout(barmode="stack", title=titulo, yaxis_title="Trabalhos",
                      xaxis_title=f"Período ({passo} anos)", legend=dict(orientation="h", y=1.12))
    return fig


def barras_flags(df: pd.DataFrame, prefixo: str, titulo: str) -> go.Figure:
    cols = [c for c in df.columns if c.startswith(prefixo + ":")]
    s = pd.Series({c.split(":", 1)[1]: int(df[c].sum()) for c in cols}).sort_values(ascending=False)
    return barras_top(s, titulo, n=len(s))


def heatmap_cruzado(df: pd.DataFrame, prefixo: str, coluna: str, titulo: str) -> go.Figure:
    cols = [c for c in df.columns if c.startswith(prefixo + ":")]
    t = pd.DataFrame({c.split(":", 1)[1]: df.groupby(coluna)[c].sum() for c in cols}).T
    fig = go.Figure(go.Heatmap(z=t.values, x=list(t.columns), y=list(t.index), colorscale="Blues",
                               text=t.values, texttemplate="%{text}",
                               hovertemplate="%{y} × %{x}: %{z}<extra></extra>"))
    fig.update_layout(title=titulo, height=60 * len(t) + 180, margin=dict(l=260),
                      yaxis=dict(autorange="reversed"))
    return fig


def citacoes(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["year", "cited_by"])
    fig = go.Figure(go.Scatter(
        x=d["year"], y=d["cited_by"].clip(lower=0) + 1, mode="markers",
        marker=dict(size=10, color=[PALETA.index(PALETA[0])] * len(d), opacity=0.7,
                    line=dict(width=1, color="white")),
        text=d["title"].str.slice(0, 80), hovertemplate="%{text}<br>%{x} · %{customdata} citações<extra></extra>",
        customdata=d["cited_by"]))
    fig.update_layout(title="Impacto: ano × citações (escala log)", yaxis_type="log",
                      xaxis_title="Ano", yaxis_title="Citações + 1")
    return fig


def sunburst_taxonomia(df: pd.DataFrame) -> go.Figure:
    """Hierarquia rede → paradigma → agêntico (visão geral do estado da arte)."""
    c = df.groupby(["rede", "paradigma", "agentico"]).size().reset_index(name="n")
    ids, labels, parents, values = [], [], [], []
    for r, g in c.groupby("rede"):
        ids.append(r); labels.append(r); parents.append(""); values.append(g.n.sum())
        for p, gg in g.groupby("paradigma"):
            ids.append(f"{r}/{p}"); labels.append(p); parents.append(r); values.append(gg.n.sum())
            for _, row in gg.iterrows():
                ids.append(f"{r}/{p}/{row.agentico}"); labels.append(row.agentico)
                parents.append(f"{r}/{p}"); values.append(row.n)
    fig = go.Figure(go.Sunburst(ids=ids, labels=labels, parents=parents, values=values,
                                branchvalues="total", marker=dict(colors=None)))
    fig.update_layout(title="Taxonomia: rede → paradigma → agêntico", height=620)
    return fig
