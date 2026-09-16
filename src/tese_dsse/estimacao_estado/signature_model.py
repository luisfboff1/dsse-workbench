"""Classificador APRENDIDO de assinatura de ataque -- substituto candidato
do limiar fixo de `ac_bad_data.classify_attack_signature` (objetivo O2).

Motivacao direta de `docs/visao/narrativa_tese.md` secao 1.4: o baseline
decide por UM limiar escolhido a mao (`line_fraction_threshold=0.5`) sobre
UMA estatistica escalar (a fracao de medidas proprias flagradas da linha
vencedora). Isso e literalmente um corte por reta num espaco de uma
dimensao. As tres razoes pelas quais isso falha -- fronteira subjetiva,
assinaturas que colidem (multi-medida imita parametro) e indices classicos
que degradam quando `H` esta errada -- sao todas razoes para trocar o corte
escalar por um separador nao-linear sobre o vetor de features de
`signature_sweep.signature_features`.

Tres niveis sao expostos de proposito, para que a comparacao da tese seja
honesta e nao "ML ganha porque e ML":

1. **Limiar fixo** (baseline do artigo) -- ja medido em `signature_sweep`.
2. **Linear** (`LogisticRegression` sobre as mesmas features) -- mostra
   quanto do ganho vem so de usar MAIS informacao, ainda com fronteira
   reta.
3. **Nao-linear** (`HistGradientBoostingClassifier`) -- mostra quanto do
   ganho exige de fato uma fronteira curva.

A avaliacao NUNCA e um split aleatorio de linhas do dataframe: cada trial
Monte Carlo do mesmo (linha, magnitude, ruido) e quase-duplicado, entao um
split aleatorio superestima. Use `leave_one_line_out` (generaliza para uma
linha nunca vista) e `cross_network` (treina no 5-bus, testa no 14-bus) --
e a mesma exigencia de caso de CONTROLE ja registrada em
`docs/governanca/decisoes_tecnicas.md` (2026-07-21): nunca declarar
generalizacao sem testar fora da zona onde ja se espera funcionar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

__all__ = [
    "METADATA_COLUMNS",
    "feature_columns",
    "make_model",
    "SplitReport",
    "evaluate_split",
    "leave_one_line_out",
    "cross_network",
    "random_split_report",
    "permutation_importances",
    "SignatureClassifier",
    "fit_signature_classifier",
]

#: Colunas do CSV da varredura que descrevem a VERDADE ou o cenario -- nunca
#: podem entrar como feature (seriam vazamento: em operacao ninguem sabe a
#: magnitude do ataque nem quantas medidas foram atacadas).
METADATA_COLUMNS: frozenset[str] = frozenset({
    "network", "true_type", "true_line", "scenario_line", "pred_type", "pred_line",
    "correct_type", "correct_line", "magnitude", "n_attacked", "target_mode",
    "coherent_signs", "noise_level", "seed", "n_attacked_effective", "param_mode",
})

#: Colunas que descrevem o resultado do DETECTOR, e nao a verdade -- essas
#: PODEM entrar como feature (sao observaveis em operacao).
OBSERVABLE_FLAGS: frozenset[str] = frozenset({"detected_cme", "detected_res", "converged"})


def feature_columns(df: Any) -> list[str]:
    """Colunas numericas usaveis como feature: tudo que nao e metadata de
    verdade/cenario."""

    return [
        c for c in df.columns
        if c not in METADATA_COLUMNS
        and (c in OBSERVABLE_FLAGS or np.issubdtype(df[c].dtype, np.number))
    ]


def _as_xy(df: Any, cols: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    X = df[list(cols)].astype(float).to_numpy()
    y = df["true_type"].to_numpy()
    return X, y


def make_model(kind: str = "gbm", *, random_state: int = 0, class_weight: str | None = "balanced") -> Any:
    """`"gbm"` (nao-linear, default), `"linear"` (regressao logistica
    padronizada) ou `"tree"` (arvore rasa, para LER a regra aprendida e
    comparar com o limiar de 0.5 do artigo)."""

    if kind == "gbm":
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(
            max_iter=400, learning_rate=0.08, max_depth=None, max_leaf_nodes=31,
            l2_regularization=1.0, early_stopping=True, validation_fraction=0.15,
            class_weight=class_weight, random_state=random_state,
        )
    if kind == "linear":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        return make_pipeline(
            StandardScaler(),
            LogisticRegression(
                max_iter=5000, C=1.0, class_weight=class_weight, random_state=random_state
            ),
        )
    if kind == "tree":
        from sklearn.tree import DecisionTreeClassifier

        return DecisionTreeClassifier(
            max_depth=4, min_samples_leaf=25, class_weight=class_weight,
            random_state=random_state,
        )
    raise ValueError(f"kind invalido: {kind!r}")


@dataclass
class SplitReport:
    """Resultado de um split de avaliacao, sempre lado a lado com o baseline
    NAS MESMAS LINHAS de teste -- comparar contra a acuracia global do
    baseline em outro conjunto seria comparacao torta."""

    label: str
    n_train: int
    n_test: int
    classes: list[str]
    feature_names: list[str]
    accuracy_model: float
    accuracy_baseline: float
    confusion_model: Any
    confusion_baseline: Any
    per_class_recall_model: dict[str, float]
    per_class_recall_baseline: dict[str, float]
    y_true: np.ndarray
    y_pred: np.ndarray
    proba: np.ndarray
    model: Any

    def summary(self) -> str:
        delta = self.accuracy_model - self.accuracy_baseline
        return (
            f"{self.label}: n_train={self.n_train} n_test={self.n_test} | "
            f"baseline {self.accuracy_baseline:.3f} -> modelo {self.accuracy_model:.3f} "
            f"({delta:+.3f})"
        )


def _confusion(y_true: np.ndarray, y_pred: np.ndarray, classes: Sequence[str]) -> Any:
    import pandas as pd

    return pd.crosstab(
        pd.Series(y_true, name="verdade"), pd.Series(y_pred, name="predito")
    ).reindex(index=list(classes), columns=list(classes), fill_value=0)


def _recalls(cm: Any, classes: Sequence[str]) -> dict[str, float]:
    out = {}
    for c in classes:
        total = float(cm.loc[c].sum())
        out[c] = float(cm.loc[c, c] / total) if total else float("nan")
    return out


def evaluate_split(
    df_train: Any,
    df_test: Any,
    *,
    label: str,
    cols: Sequence[str] | None = None,
    kind: str = "gbm",
    random_state: int = 0,
    classes: Sequence[str] = ("none", "measurement", "parameter", "topology"),
) -> SplitReport:
    """Treina em `df_train`, avalia em `df_test`, e reporta o baseline nas
    MESMAS linhas de teste (coluna `pred_type`, ja gravada pela varredura)."""

    cols = list(cols) if cols is not None else feature_columns(df_train)
    X_tr, y_tr = _as_xy(df_train, cols)
    X_te, y_te = _as_xy(df_test, cols)

    model = make_model(kind, random_state=random_state)
    model.fit(X_tr, y_tr)
    y_pred = model.predict(X_te)
    proba = model.predict_proba(X_te)
    y_base = df_test["pred_type"].to_numpy()

    present = [c for c in classes if c in set(y_te) | set(y_pred) | set(y_base)]
    cm_model = _confusion(y_te, y_pred, present)
    cm_base = _confusion(y_te, y_base, present)
    return SplitReport(
        label=label,
        n_train=len(df_train),
        n_test=len(df_test),
        classes=present,
        feature_names=list(cols),
        accuracy_model=float(np.mean(y_pred == y_te)),
        accuracy_baseline=float(np.mean(y_base == y_te)),
        confusion_model=cm_model,
        confusion_baseline=cm_base,
        per_class_recall_model=_recalls(cm_model, present),
        per_class_recall_baseline=_recalls(cm_base, present),
        y_true=y_te,
        y_pred=y_pred,
        proba=proba,
        model=model,
    )


def leave_one_line_out(
    df: Any, *, cols: Sequence[str] | None = None, kind: str = "gbm",
    lines: Iterable[int] | None = None, random_state: int = 0,
) -> list[SplitReport]:
    """Para cada linha `L`: treina em tudo que NAO envolve `L` e testa nos
    casos de `L`. E o teste de generalizacao estrutural -- o modelo tem que
    reconhecer a assinatura de um erro de parametro numa linha cuja
    topologia local ele nunca viu no treino.

    Um caso "envolve `L`" se `scenario_line == L` e o cenario foi montado em
    torno dessa linha: erro de parametro/topologia NELA, ou ataque de medida
    montado em cima das medidas proprias DELA (`target_mode ==
    "line_cluster"`). Casos `none` e ataques de medida com alvo `random`
    ficam sempre no treino, porque nao pertencem a nenhuma linha.

    A coluna usada e `scenario_line`, nao `true_line`: `true_line` so e
    preenchida para `parameter`/`topology`, entao filtrar por ela deixaria os
    ataques MULTI-MEDIDA daquela linha no treino -- vazamento estrutural
    exatamente no caso mais dificil, que e o que a §1.4 chama de colisao de
    assinatura.
    """

    key = "scenario_line" if "scenario_line" in df.columns else "true_line"
    lines = sorted({int(v) for v in df[key].dropna().unique()}) if lines is None else list(lines)
    reports: list[SplitReport] = []
    for line in lines:
        touches = (df[key] == line) & (
            df["true_type"].isin(["parameter", "topology"])
            | (df["target_mode"] == "line_cluster")
        )
        df_te = df[touches]
        df_tr = df[~touches]
        if df_te.empty or df_tr.empty or df_tr["true_type"].nunique() < 2:
            continue
        reports.append(
            evaluate_split(df_tr, df_te, label=f"linha {line} fora do treino",
                           cols=cols, kind=kind, random_state=random_state)
        )
    return reports


def cross_network(
    df_train: Any, df_test: Any, *, cols: Sequence[str] | None = None,
    kind: str = "gbm", random_state: int = 0,
) -> SplitReport:
    """Treina numa rede e testa em OUTRA -- o teste mais duro, e o unico que
    justifica chamar as features de "invariantes ao tamanho da rede"."""

    net_tr = df_train["network"].iloc[0]
    net_te = df_test["network"].iloc[0]
    cols = list(cols) if cols is not None else sorted(
        set(feature_columns(df_train)) & set(feature_columns(df_test))
    )
    return evaluate_split(df_train, df_test, label=f"treino {net_tr} -> teste {net_te}",
                          cols=cols, kind=kind, random_state=random_state)


def random_split_report(
    df: Any, *, test_size: float = 0.3, cols: Sequence[str] | None = None,
    kind: str = "gbm", random_state: int = 0,
) -> SplitReport:
    """Split aleatorio -- reportado so como TETO OTIMISTA. Trials Monte Carlo
    do mesmo cenario sao quase-duplicados, entao esta acuracia e inflada;
    nunca cite este numero sozinho."""

    from sklearn.model_selection import train_test_split

    idx_tr, idx_te = train_test_split(
        np.arange(len(df)), test_size=test_size, random_state=random_state,
        stratify=df["true_type"].to_numpy(),
    )
    return evaluate_split(df.iloc[idx_tr], df.iloc[idx_te], label="split aleatorio (otimista)",
                          cols=cols, kind=kind, random_state=random_state)


def permutation_importances(
    report: SplitReport, df_test: Any, *, cols: Sequence[str] | None = None,
    n_repeats: int = 10, random_state: int = 0,
) -> Any:
    """Importancia por permutacao NO CONJUNTO DE TESTE (nao a importancia
    interna do GBM, que e enviesada para features de alta cardinalidade).

    `df_test` precisa ser o MESMO conjunto avaliado em `report` -- a ordem das
    colunas vem de `report.feature_names`, nao das colunas do dataframe."""

    import pandas as pd
    from sklearn.inspection import permutation_importance

    cols = list(cols) if cols is not None else report.feature_names
    X_te, y_te = _as_xy(df_test, cols)
    res = permutation_importance(
        report.model, X_te, y_te, n_repeats=n_repeats, random_state=random_state,
        scoring="accuracy",
    )
    return (
        pd.DataFrame({
            "feature": list(cols),
            "importancia": res.importances_mean,
            "desvio": res.importances_std,
        })
        .sort_values("importancia", ascending=False)
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Uso em producao: o classificador como componente do agente de assinatura
# ---------------------------------------------------------------------------


@dataclass
class SignatureClassifier:
    """Modelo treinado + os nomes das features, pronto para substituir
    `classify_attack_signature` dentro do pipeline.

    Diferenca operacional para o baseline: devolve uma DISTRIBUICAO de
    probabilidade sobre os quatro tipos, nao um rotulo duro. Isso e o que
    remove a subjetividade apontada na secao 1.4 -- em vez de um
    `line_fraction_threshold` escolhido a mao, o operador (ou o agente
    coordenador) escolhe um nivel de confianca, e abaixo dele o agente
    ABSTEM em vez de chutar. Abster e o comportamento "agentic" da secao
    5.7: reconhecer que a evidencia atual nao basta e ir buscar mais
    (rodar outro diagnostico, pedir dado ao agente vizinho) em vez de
    aplicar a correcao errada e divergir.
    """

    model: Any
    feature_names: list[str]
    abstain_threshold: float = 0.0

    @property
    def classes_(self) -> np.ndarray:
        return self.model.classes_

    def predict_proba(self, features: dict[str, float]) -> dict[str, float]:
        x = np.array([[float(features[name]) for name in self.feature_names]])
        p = self.model.predict_proba(x)[0]
        return {str(c): float(v) for c, v in zip(self.model.classes_, p)}

    def classify(self, features: dict[str, float]) -> tuple[str, float, dict[str, float]]:
        """Retorna `(tipo, confianca, distribuicao)`. Se a confianca ficar
        abaixo de `abstain_threshold`, o tipo vira `"uncertain"` -- o
        pipeline deve tratar isso como "nao aplicar correcao ainda"."""

        proba = self.predict_proba(features)
        best = max(proba, key=proba.__getitem__)
        conf = proba[best]
        if conf < self.abstain_threshold:
            return "uncertain", conf, proba
        return best, conf, proba

    def classify_from_state(
        self, measurements: Sequence[Any], net: Any, geo: Any, bus_degree: dict[int, int],
        *, j_res_ratio: float, j_cme_ratio: float, threshold: float = 3.0,
    ) -> tuple[str, float, dict[str, float]]:
        """Extrai as features da estimacao atual e classifica -- assinatura
        equivalente a `classify_attack_signature`, para o pipeline poder
        trocar um pelo outro."""

        from .signature_sweep import signature_features

        feats = signature_features(
            list(measurements), net, geo, bus_degree,
            j_res_ratio=j_res_ratio, j_cme_ratio=j_cme_ratio, threshold=threshold,
        )
        return self.classify(feats)


def fit_signature_classifier(
    df: Any, *, cols: Sequence[str] | None = None, kind: str = "gbm",
    abstain_threshold: float = 0.0, random_state: int = 0,
) -> SignatureClassifier:
    """Treina no dataframe inteiro (uso final, depois de a generalizacao ja
    ter sido medida por `leave_one_line_out`/`cross_network`)."""

    cols = list(cols) if cols is not None else feature_columns(df)
    X, y = _as_xy(df, cols)
    model = make_model(kind, random_state=random_state)
    model.fit(X, y)
    return SignatureClassifier(model=model, feature_names=cols, abstain_threshold=abstain_threshold)
