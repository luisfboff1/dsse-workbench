"""Log de resultados de experimentos -- ver
docs/estudos/estimacao_estado/resultados_classificacao/README.md.

Cada chamada a `log_resultado` acrescenta UMA linha JSON a um arquivo
`.jsonl` (JSON Lines) **versionado no git**. E o registro que fica quando um
script de varredura, um notebook de validacao ou um teste de regressao
termina -- em vez do numero morrer no terminal ou numa conversa, ele fica no
historico do repositorio: dado de entrada, dado de saida, script que gerou,
commit, timestamp.

Por que JSON Lines e nao CSV: os experimentos daqui tem parametros e saidas
de forma DIFERENTE entre si (um erro de parametro tem `dg_pct`/`db_pct`; um
erro de topologia so tem a linha alvo). CSV exigiria uma coluna por
combinacao possivel de todo script que algum dia escrever aqui, ou uma
explosao de colunas vazias. JSONL mantem um nucleo fixo (`script`, `cenario`,
`rede`, `passou`) e o resto solto em `params`/`saida`/`esperado`, sem forcar
um schema global -- e cada linha ainda e texto, entao `git diff`/`git log -p`
continuam legiveis sem ferramenta especial. Ler tudo em pandas:
`pd.read_json(caminho, lines=True)`.

Por que nao um script separado por experimento: um log central deixa
"mostrar a evolucao" ser uma consulta (`df[df.cenario==...].sort_values
('timestamp')`), nao uma caca por commits antigos ou por scroll de
conversa.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import DOCS_DIR

DEFAULT_LOG_PATH = (
    DOCS_DIR
    / "estudos"
    / "estimacao_estado"
    / "resultados_classificacao"
    / "log_experimentos.jsonl"
)


def _git_commit() -> str:
    """Hash curto do commit atual, ou "sujo"/"desconhecido" se nao der pra saber.

    "sujo" quando ha mudancas nao commitadas -- o numero registrado ainda nao
    corresponde a nenhum estado que outra pessoa consiga `git checkout`.
    """
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout
        return f"{commit}+sujo" if status.strip() else commit
    except Exception:
        return "desconhecido"


def log_resultado(
    *,
    script: str,
    cenario: str,
    rede: str,
    params: dict[str, Any] | None = None,
    saida: dict[str, Any] | None = None,
    esperado: dict[str, Any] | None = None,
    passou: bool | None = None,
    notas: str = "",
    log_path: Path | str | None = None,
) -> dict[str, Any]:
    """Acrescenta um registro ao log de experimentos (JSON Lines).

    Parametros
    ----------
    script: caminho relativo (ou `arquivo.py::teste`) de quem gerou o
        resultado -- ex. "tests/test_signature_classification.py::
        test_topology_fechamento_tie_switch_case33bw".
    cenario: nome curto e estavel do cenario -- o mesmo nome ao longo do
        tempo e o que permite comparar "antes x depois" numa consulta.
    rede: rede usada (ex. "case33bw", "case9").
    params: parametros de entrada (seed, magnitude, linha alvo, etc.).
    saida: o que o metodo devolveu (tipo, linha, mag_dp, J, limiar...).
    esperado: o que era esperado, quando o cenario tem verdade conhecida.
    passou: True/False se houver criterio de sucesso; None se so
        exploratorio (varredura sem "certo/errado", so medicao).
    notas: texto livre -- por que esse cenario, o que mudou desde a ultima
        entrada, etc.
    log_path: destino alternativo, usado so em teste do proprio logger.

    Retorna o registro escrito, para quem chama tambem poder imprimir ou
    validar sem reabrir o arquivo.
    """
    registro: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "script": script,
        "cenario": cenario,
        "rede": rede,
        "params": params or {},
        "saida": saida or {},
        "esperado": esperado or {},
        "passou": passou,
        "notas": notas,
    }

    path = Path(log_path) if log_path is not None else DEFAULT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro
