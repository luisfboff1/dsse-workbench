"""Bibliometria (estilo Biblioshiny): Zotero → OpenAlex → classificação → gráficos."""
from . import classificacao, corpus, graficos, openalex  # noqa: F401
from .classificacao import classificar
from .corpus import carregar_colecao
from .openalex import enriquecer

__all__ = ["carregar_colecao", "enriquecer", "classificar", "graficos"]

