"""
Integração com a API do Zotero v3 via pyzotero.

Uso:
    from tese_dsse.zotero_integration import conectar_zotero, csv_para_itens_zotero

Credenciais são lidas de variáveis de ambiente ou de um arquivo .env na raiz do projeto.
Variáveis necessárias: ZOTERO_USER_ID, ZOTERO_API_KEY, ZOTERO_LIBRARY_TYPE (default: user).
"""

import os
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _carregar_dotenv():
    """Carrega variáveis de .env se python-dotenv estiver disponível."""
    try:
        from dotenv import load_dotenv
        raiz = Path(__file__).resolve().parent.parent.parent
        env_path = raiz / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug("Arquivo .env carregado de %s", env_path)
    except ImportError:
        pass  # python-dotenv não instalado; usar apenas variáveis de ambiente do sistema


def conectar_zotero(
    user_id: Optional[str] = None,
    api_key: Optional[str] = None,
    library_type: Optional[str] = None,
):
    """
    Retorna um cliente pyzotero autenticado.

    Parâmetros podem ser passados diretamente ou via variáveis de ambiente:
      - ZOTERO_USER_ID
      - ZOTERO_API_KEY
      - ZOTERO_LIBRARY_TYPE  (default: "user")

    Retorna:
        pyzotero.zotero.Zotero
    """
    _carregar_dotenv()
    try:
        from pyzotero import zotero
    except ImportError as exc:
        raise ImportError(
            "pyzotero não encontrado. Instale com: pip install pyzotero"
        ) from exc

    uid = user_id or os.environ.get("ZOTERO_USER_ID")
    key = api_key or os.environ.get("ZOTERO_API_KEY")
    lib_type = library_type or os.environ.get("ZOTERO_LIBRARY_TYPE", "user")

    if not uid or not key:
        raise ValueError(
            "ZOTERO_USER_ID e ZOTERO_API_KEY são obrigatórios. "
            "Defina-os no arquivo .env ou como variáveis de ambiente."
        )

    zot = zotero.Zotero(uid, lib_type, key)
    logger.info("Conectado ao Zotero (userID=%s, library_type=%s)", uid, lib_type)
    return zot


# ---------------------------------------------------------------------------
# Mapeamento de campos CSV → Zotero
# ---------------------------------------------------------------------------

# Tipos OpenAlex → tipos Zotero
_TIPO_MAP = {
    "review": "journalArticle",
    "article": "journalArticle",
    "journal-article": "journalArticle",
    "proceedings-article": "conferencePaper",
    "book": "book",
    "book-chapter": "bookSection",
    "dataset": "dataset",
    "preprint": "preprint",
    "report": "report",
    "thesis": "thesis",
}


def _tipo_zotero(tipo_openalex: str) -> str:
    return _TIPO_MAP.get(str(tipo_openalex).lower(), "journalArticle")


def _parse_autores(autores_str: str) -> list[dict]:
    """
    Converte string 'Nome Sobrenome; Nome2 Sobrenome2' em lista de creators Zotero.
    """
    creators = []
    if pd.isna(autores_str) or not autores_str:
        return creators
    for autor in str(autores_str).split(";"):
        autor = autor.strip()
        if not autor:
            continue
        partes = autor.rsplit(" ", 1)
        if len(partes) == 2:
            creators.append({
                "creatorType": "author",
                "firstName": partes[0].strip(),
                "lastName": partes[1].strip(),
            })
        else:
            creators.append({
                "creatorType": "author",
                "name": autor,
            })
    return creators


def _parse_tags(row: pd.Series) -> list[dict]:
    """Cria tags Zotero a partir de colunas de triagem e categorias."""
    tags = []

    # Decisão de triagem
    if pd.notna(row.get("screening_decision")):
        tags.append({"tag": f"screening:{row['screening_decision']}"})

    # Categorias temáticas
    if pd.notna(row.get("categories")):
        for cat in str(row["categories"]).split(";"):
            cat = cat.strip()
            if cat:
                tags.append({"tag": cat})

    # Prioridade de leitura / relevância
    score = row.get("thesis_relevance_score")
    if pd.notna(score):
        try:
            score_val = float(score)
            if score_val >= 100:
                tags.append({"tag": "relevancia:alta"})
            elif score_val >= 60:
                tags.append({"tag": "relevancia:media"})
            else:
                tags.append({"tag": "relevancia:baixa"})
        except (ValueError, TypeError):
            pass

    # Marca itens review/survey
    if str(row.get("is_review_like", "")).lower() in ("true", "1", "yes"):
        tags.append({"tag": "tipo:review"})

    return tags


def linha_para_item_zotero(row: pd.Series) -> dict:
    """
    Converte uma linha do DataFrame de bibliografia em um dict de item Zotero.
    """
    item_type = _tipo_zotero(row.get("type", "article"))

    doi_raw = str(row.get("doi", "")).strip()
    doi = doi_raw if doi_raw and doi_raw != "nan" else ""

    url = str(row.get("url", "")).strip()
    if not url or url == "nan":
        url = f"https://doi.org/{doi}" if doi else ""

    date_val = str(row.get("publication_date", row.get("year", ""))).strip()
    if date_val == "nan":
        date_val = str(row.get("year", "")).strip()

    abstract = str(row.get("abstract", "")).strip()
    if abstract == "nan":
        abstract = ""

    title = str(row.get("title", "")).strip()
    source = str(row.get("source", "")).strip()
    if source == "nan":
        source = ""

    item = {
        "itemType": item_type,
        "title": title,
        "creators": _parse_autores(row.get("authors", "")),
        "abstractNote": abstract,
        "date": date_val,
        "DOI": doi,
        "url": url,
        "tags": _parse_tags(row),
        "extra": f"openalex_id: {row.get('openalex_id', '')}",
    }

    if item_type in ("journalArticle",):
        item["publicationTitle"] = source
    elif item_type == "conferencePaper":
        item["proceedingsTitle"] = source
    elif item_type == "preprint":
        item["repository"] = source

    return item


def csv_para_itens_zotero(
    caminho_csv: str | Path,
    apenas_incluidos: bool = True,
) -> list[dict]:
    """
    Lê o CSV de bibliografia e retorna lista de dicts prontos para upload ao Zotero.

    Args:
        caminho_csv: Caminho para o arquivo CSV.
        apenas_incluidos: Se True, filtra apenas linhas com screening_decision == 'include'.
    """
    df = pd.read_csv(caminho_csv)

    if apenas_incluidos and "screening_decision" in df.columns:
        df = df[df["screening_decision"].str.lower() == "include"].copy()
        logger.info("%d itens com decisão 'include' carregados", len(df))
    else:
        logger.info("%d itens carregados (sem filtro)", len(df))

    itens = []
    for _, row in df.iterrows():
        try:
            itens.append(linha_para_item_zotero(row))
        except Exception as exc:
            logger.warning("Erro ao converter linha (title=%s): %s", row.get("title", "?"), exc)

    return itens


# ---------------------------------------------------------------------------
# Operações de leitura da biblioteca Zotero
# ---------------------------------------------------------------------------

def listar_colecoes(zot) -> pd.DataFrame:
    """Retorna um DataFrame com as coleções da biblioteca Zotero."""
    colecoes = zot.collections()
    if not colecoes:
        return pd.DataFrame()
    registros = [
        {
            "key": c["key"],
            "name": c["data"]["name"],
            "parent": c["data"].get("parentCollection", ""),
            "num_items": c.get("meta", {}).get("numItems", 0),
        }
        for c in colecoes
    ]
    return pd.DataFrame(registros)


def itens_para_dataframe(zot, colecao_key: Optional[str] = None, limite: int = 500) -> pd.DataFrame:
    """
    Baixa itens da biblioteca Zotero e retorna um DataFrame.

    Args:
        zot: Cliente pyzotero autenticado.
        colecao_key: Chave da coleção (opcional; None = toda a biblioteca).
        limite: Número máximo de itens a baixar.
    """
    if colecao_key:
        itens = zot.collection_items(colecao_key, limit=min(limite, 100))
    else:
        itens = zot.items(limit=min(limite, 100), itemType="-attachment || note")

    registros = []
    for item in itens:
        data = item.get("data", {})
        creators = data.get("creators", [])
        autores = "; ".join(
            f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
            if "lastName" in c else c.get("name", "")
            for c in creators
        )
        tags = [t["tag"] for t in data.get("tags", [])]
        registros.append({
            "key": item["key"],
            "itemType": data.get("itemType"),
            "title": data.get("title"),
            "date": data.get("date"),
            "DOI": data.get("DOI"),
            "url": data.get("url"),
            "publicationTitle": data.get("publicationTitle") or data.get("proceedingsTitle"),
            "abstractNote": data.get("abstractNote"),
            "authors": autores,
            "tags": "; ".join(tags),
        })

    return pd.DataFrame(registros)
