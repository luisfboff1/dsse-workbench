"""Ferramentas locais para a tese DSSE + IA.

Estrutura de dominios (cada subpacote tem um README explicando o escopo):

- ``estimacao_estado``: estimadores estaticos (WLS Gauss-Newton, DC linear, AC).
- ``geracao_dados``: pipeline de dados sinteticos/medicoes.
- ``observabilidade``: analise de observabilidade e placement de medidores.
- ``sistemas_dinamicos``: estimadores dinamicos (Kalman/EKF/UKF, FASE).
- ``seguranca``: cyber security — ataques (FDIA) e defesa.
- ``deteccao_anomalias``: bad data e deteccao de anomalias.

Convencao transversal de auditoria: ``auditoria.AuditTrail`` da a todas as
funcoes pesadas um ``verbose`` padronizado (passo a passo dos calculos).
"""

from .auditoria import AuditStep, AuditTrail, resolve_audit

__version__ = "0.1.0"

__all__ = [
    "AuditStep",
    "AuditTrail",
    "resolve_audit",
    "__version__",
]
