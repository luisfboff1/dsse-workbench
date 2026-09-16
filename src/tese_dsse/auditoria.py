"""Trilha de auditoria reutilizavel para os algoritmos da tese DSSE + IA.

Objetivo
--------
Dar a TODA funcao "pesada" (estimadores, observabilidade, sistemas dinamicos,
deteccao de anomalias, ataques/defesa cyber) um mesmo padrao de `verbosity`:

- Se ``verbose=False`` (padrao): a funcao roda silenciosa e rapida.
- Se ``verbose=True``: a funcao registra e imprime, passo a passo, as variaveis
  criadas, as formulas usadas e os valores numericos. Isso serve de auditoria
  ("o que esta sendo calculado e por que") e mantem as celulas de notebook
  limpas, porque o detalhe vive aqui e nas funcoes ``.py``.

A trilha tambem fica *gravada* em memoria. Mesmo sem imprimir, o objeto
``AuditTrail`` guarda os passos e pode ser inspecionado depois
(``trail.to_records()`` ou ``trail.to_dataframe()``), o que ajuda em testes de
regressao e em relatorios.

Padrao de uso recomendado nas funcoes
-------------------------------------
>>> def minha_funcao(x, *, verbose=False, audit=None):
...     audit = resolve_audit(audit, verbose, title="minha_funcao")
...     y = audit.step("y = 2*x", 2 * x, formula="y = 2x")
...     with audit.section("bloco interno"):
...         z = audit.step("z = y + 1", y + 1)
...     return z

O ``resolve_audit`` deixa as funcoes aceitarem tanto ``verbose=True`` (cria uma
trilha nova) quanto ``audit=<trilha existente>`` (encadeia varias funcoes na
mesma auditoria). Quando ``verbose=False`` e ``audit=None``, devolve uma trilha
desativada cujos metodos sao no-op (custo desprezivel).
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import numpy as np

__all__ = [
    "AuditStep",
    "AuditTrail",
    "resolve_audit",
]


def _format_value(value: Any, *, precision: int, max_items: int) -> str:
    """Formata um valor numerico/array para leitura humana e compacta."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{precision}g}"
    if isinstance(value, (complex, np.complexfloating)):
        c = complex(value)
        return f"{c.real:.{precision}g}{c.imag:+.{precision}g}j"
    if isinstance(value, np.ndarray):
        shape = "x".join(str(dim) for dim in value.shape) or "escalar"
        with np.printoptions(
            precision=precision,
            suppress=False,
            threshold=max_items,
            edgeitems=3,
            linewidth=120,
        ):
            corpo = np.array2string(value, separator=", ")
        return f"shape[{shape}] {corpo}"
    if isinstance(value, (list, tuple)):
        arr = np.asarray(value)
        if arr.dtype != object:
            return _format_value(arr, precision=precision, max_items=max_items)
        return repr(value)
    return repr(value)


@dataclass
class AuditStep:
    """Um registro unico da trilha de auditoria."""

    depth: int
    label: str
    kind: str  # "section" | "step" | "note"
    formula: str | None = None
    value_repr: str = ""
    unit: str | None = None
    note: str | None = None
    raw_value: Any = field(default=None, repr=False)


class AuditTrail:
    """Coletor de passos de calculo, com impressao opcional formatada.

    Parameters
    ----------
    enabled:
        Liga/desliga a trilha. Quando ``False``, todos os metodos viram no-op
        baratos e nada e impresso nem armazenado.
    title:
        Titulo opcional impresso/registrado como primeira secao.
    printer:
        Funcao usada para imprimir (default ``print``). Permite redirecionar
        para um logger ou para um buffer em testes.
    precision:
        Casas significativas na formatacao de floats e arrays.
    max_items:
        Limite de elementos mostrados antes de resumir arrays grandes.
    indent:
        String de indentacao por nivel de secao.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        title: str | None = None,
        printer: Callable[[str], Any] = print,
        precision: int = 4,
        max_items: int = 8,
        indent: str = "  ",
    ) -> None:
        self.enabled = bool(enabled)
        self.steps: list[AuditStep] = []
        self._depth = 0
        self._printer = printer
        self._precision = int(precision)
        self._max_items = int(max_items)
        self._indent = indent
        if self.enabled and title:
            self._open_section(title, None)

    # -- API publica --------------------------------------------------------

    def __bool__(self) -> bool:
        return self.enabled

    @contextmanager
    def section(self, title: str, value: Any = None) -> Iterator["AuditTrail"]:
        """Abre uma secao (bloco logico) que indenta os passos internos."""

        if not self.enabled:
            yield self
            return
        self._open_section(title, value)
        self._depth += 1
        try:
            yield self
        finally:
            self._depth -= 1

    def step(
        self,
        label: str,
        value: Any = None,
        *,
        formula: str | None = None,
        unit: str | None = None,
        note: str | None = None,
    ) -> Any:
        """Registra (e imprime, se ativo) uma variavel/passo de calculo.

        Devolve ``value`` para permitir uso inline:

        >>> gain = audit.step("G = HᵀWH", H.T @ W @ H)
        """

        if not self.enabled:
            return value
        value_repr = _format_value(
            value, precision=self._precision, max_items=self._max_items
        )
        record = AuditStep(
            depth=self._depth,
            label=label,
            kind="step",
            formula=formula,
            value_repr=value_repr,
            unit=unit,
            note=note,
            raw_value=value,
        )
        self.steps.append(record)
        self._print_step(record)
        return value

    def note(self, text: str) -> None:
        """Registra um comentario livre na trilha."""

        if not self.enabled:
            return
        record = AuditStep(depth=self._depth, label=text, kind="note")
        self.steps.append(record)
        self._printer(f"{self._indent * self._depth}# {text}")

    def to_records(self) -> list[dict[str, Any]]:
        """Exporta a trilha como lista de dicts (sem o valor cru)."""

        return [
            {
                "depth": s.depth,
                "kind": s.kind,
                "label": s.label,
                "formula": s.formula,
                "value": s.value_repr,
                "unit": s.unit,
                "note": s.note,
            }
            for s in self.steps
        ]

    def to_dataframe(self):
        """Exporta a trilha como ``pandas.DataFrame`` (import tardio)."""

        import pandas as pd

        return pd.DataFrame(self.to_records())

    # -- internos -----------------------------------------------------------

    def _open_section(self, title: str, value: Any) -> None:
        value_repr = (
            _format_value(value, precision=self._precision, max_items=self._max_items)
            if value is not None
            else ""
        )
        record = AuditStep(
            depth=self._depth,
            label=title,
            kind="section",
            value_repr=value_repr,
            raw_value=value,
        )
        self.steps.append(record)
        prefix = self._indent * self._depth
        suffix = f" = {value_repr}" if value_repr else ""
        self._printer(f"{prefix}> {title}{suffix}")

    def _print_step(self, record: AuditStep) -> None:
        prefix = self._indent * record.depth
        partes = [record.label]
        if record.formula and record.formula != record.label:
            partes.append(f"[{record.formula}]")
        linha = "  ".join(partes)
        if record.value_repr:
            linha = f"{linha} = {record.value_repr}"
        if record.unit:
            linha = f"{linha} {record.unit}"
        if record.note:
            linha = f"{linha}  ({record.note})"
        self._printer(f"{prefix}{linha}")


def resolve_audit(
    audit: AuditTrail | None,
    verbose: bool,
    *,
    title: str | None = None,
    **kwargs: Any,
) -> AuditTrail:
    """Resolve a trilha a usar dentro de uma funcao.

    Regras:

    - Se ``audit`` ja foi passado, ele e reaproveitado (encadeamento entre
      funcoes na mesma auditoria). ``verbose`` e ignorado nesse caso.
    - Caso contrario, cria uma ``AuditTrail`` nova com ``enabled=verbose``.

    Assim cada funcao publica pode expor apenas ``verbose: bool = False`` para o
    usuario comum e ``audit: AuditTrail | None = None`` para uso avancado.
    """

    if audit is not None:
        return audit
    return AuditTrail(enabled=bool(verbose), title=title if verbose else None, **kwargs)
