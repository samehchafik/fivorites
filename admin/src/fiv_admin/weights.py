"""Les poids internes : `axes ≈ intercept + coef · embedding`.

C'est l'apprenti du processus d'entraînement. Le LLM juge ; cette régression
n'a jamais de jugement — elle interpole entre les jugements déjà rendus. Une
ridge en forme fermée suffit : sur des vecteurs de quelques centaines de
dimensions et autant d'exemples, tout se calcule en millisecondes, sans
dépendance au-delà de numpy.

λ n'est PAS une constante, et c'est une leçon payée sur données réelles : un
λ=10 fixe, posé « par prudence », face à des embeddings OpenAI de norme 1
étalée sur 256 dimensions, écrasait ~97 % du signal — les valeurs propres de
XᵀX valent ~0,3, le facteur de rétrécissement 0,3/10,3. Résultat observé sur
le premier lot : les six axes prédits quasi identiques pour treize œuvres
très différentes — la régression rendait la moyenne d'entraînement, partout,
et son MAE *sur ses propres données* dépassait 1 point. λ se choisit donc par
validation croisée, en réajustant sur chaque pli — la forme fermée du LOO,
essayée d'abord, dégénère quand les exemples sont moins nombreux que les
dimensions (voir `_erreur_croisee`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# La grille de λ explorée par la validation croisée. Large de quatre ordres de
# grandeur, parce que la bonne valeur dépend de l'échelle des vecteurs — c'est
# précisément ce qu'une constante ne peut pas savoir.
LAMBDA_GRID = (1e-3, 3e-3, 1e-2, 3e-2, 0.1, 0.3, 1.0, 3.0, 10.0)

SCALE_MIN, SCALE_MAX = 1.0, 10.0


@dataclass(frozen=True, slots=True)
class AxisWeights:
    axe: str
    intercept: float
    coef: list[float]
    trained_on: int
    mae_fit: float
    # Le λ retenu, et l'erreur de validation croisée qui l'a désigné. C'est
    # elle, la métrique honnête : le MAE d'ajustement flatte toujours, et il
    # flatte d'autant plus qu'on a moins d'exemples que de dimensions.
    lam: float
    mae_cv: float


def _fit(xc: np.ndarray, yc: np.ndarray, lam: float) -> np.ndarray:
    """Les coefficients ridge sur des données déjà centrées."""
    u, s, vt = np.linalg.svd(xc, full_matrices=False)
    return vt.T @ ((s / (s**2 + lam)) * (u.T @ yc))


def _erreur_croisee(
    x: np.ndarray, y: np.ndarray, lam: float, plis: int, x_eval: np.ndarray | None = None
) -> float:
    """L'erreur sur des points que le modèle n'a pas vus.

    Réajustée à chaque pli, exprès. La forme fermée du LOO — résidu divisé par
    (1 − hᵢᵢ) — est exacte en théorie et inutilisable ici : dès que les
    exemples sont moins nombreux que les dimensions, un λ minuscule interpole
    les données, le résidu tombe à zéro ET le levier tend vers 1. Le calcul
    devient 0/0, rend numériquement ~0, et désigne le pire λ en croyant élire
    le meilleur. C'est exactement ce qui s'est produit sur le premier vrai
    lot : 41 œuvres, 256 dimensions, une régression qui recopiait le juge à la
    virgule près. Mesurer sur des points réellement écartés ne peut pas
    dégénérer de cette façon.
    """
    # `x_eval` sert au diagnostic des visuels : on apprend sur une
    # représentation et on évalue sur une autre, pour chiffrer ce que coûte
    # d'appliquer des poids entraînés sur dossiers enrichis à des dossiers
    # nus. Sans lui, on ne mesure jamais ce décalage-là.
    cible = x if x_eval is None else x_eval
    erreurs: list[np.ndarray] = []
    for pli in range(plis):
        # Découpage par pas plutôt qu'en blocs : sans mélange aléatoire, des
        # blocs contigus suivraient l'ordre d'insertion en base, qui n'a
        # aucune raison d'être neutre (popularité décroissante, par exemple).
        test = np.arange(pli, len(y), plis)
        if len(test) == 0 or len(test) == len(y):
            continue
        garde = np.ones(len(y), dtype=bool)
        garde[test] = False

        x_mean, y_mean = x[garde].mean(axis=0), float(y[garde].mean())
        coef = _fit(x[garde] - x_mean, y[garde] - y_mean, lam)
        pred = np.clip((cible[test] - x_mean) @ coef + y_mean, SCALE_MIN, SCALE_MAX)
        erreurs.append(np.abs(pred - y[test]))

    return float(np.concatenate(erreurs).mean()) if erreurs else float("inf")


def train_axis(axe: str, vectors: list[list[float]], values: list[float]) -> AxisWeights:
    """Ajuste un axe. `vectors` et `values` vont par paires, sans null."""
    x = np.asarray(vectors, dtype=np.float64)
    y = np.asarray(values, dtype=np.float64)
    n, _dims = x.shape

    # Un pli par exemple tant que ça reste peu coûteux — c'est le découpage le
    # moins arbitraire ; au-delà, dix plis suffisent et bornent le calcul.
    plis = n if n <= 60 else 10

    best_lam, best_cv = LAMBDA_GRID[-1], float("inf")
    for lam in LAMBDA_GRID:
        erreur = _erreur_croisee(x, y, lam, plis)
        if erreur < best_cv:
            best_lam, best_cv = lam, erreur

    # Centrage : l'intercept absorbe la moyenne, la ridge ne pénalise que les
    # écarts. Sans ça, λ tirerait les prédictions vers 0 — hors de l'échelle.
    x_mean = x.mean(axis=0)
    y_mean = float(y.mean())
    coef = _fit(x - x_mean, y - y_mean, best_lam)
    intercept = y_mean - float(x_mean @ coef)

    fitted = np.clip(x @ coef + intercept, SCALE_MIN, SCALE_MAX)
    mae = float(np.abs(fitted - y).mean())

    return AxisWeights(
        axe=axe,
        intercept=intercept,
        coef=[float(c) for c in coef],
        trained_on=n,
        mae_fit=round(mae, 3),
        lam=best_lam,
        mae_cv=round(best_cv, 3),
    )


def predict(vector: list[float], intercept: float, coef: list[float]) -> float:
    """La note interne d'un axe, bornée à l'échelle."""
    raw = intercept + float(np.asarray(vector, dtype=np.float64) @ np.asarray(coef))
    return round(float(np.clip(raw, SCALE_MIN, SCALE_MAX)), 1)


def diagnostic_visuels(
    vecteurs_avec: list[list[float]], vecteurs_sans: list[list[float]], values: list[float]
) -> dict[str, float]:
    """Ce que les légendes visuelles apportent, en trois chiffres.

    Deux questions distinctes, qu'on confond facilement :

    * `avec` contre `sans` — les visuels enrichissent-ils la représentation ?
      Les deux régimes sont entraînés ET évalués sur la même matière, donc
      l'écart mesure l'apport réel des légendes.
    * `decale` — que coûte d'appliquer des poids appris sur dossiers enrichis
      à une œuvre qui n'a pas de légendes ? C'est la situation exacte de la
      traîne si l'on décide de ne pas la légender, et elle ne se déduit
      d'aucune des deux premières.

    Le λ est choisi indépendamment pour chaque régime, comme le ferait un
    entraînement réel ; pour le décalé, on garde celui du régime « avec »,
    puisque c'est bien ce modèle-là qu'on appliquerait.
    """
    x_avec = np.asarray(vecteurs_avec, dtype=np.float64)
    x_sans = np.asarray(vecteurs_sans, dtype=np.float64)
    y = np.asarray(values, dtype=np.float64)
    plis = len(y) if len(y) <= 60 else 10

    def meilleur(x: np.ndarray) -> tuple[float, float]:
        lam, err = LAMBDA_GRID[-1], float("inf")
        for candidat in LAMBDA_GRID:
            e = _erreur_croisee(x, y, candidat, plis)
            if e < err:
                lam, err = candidat, e
        return lam, err

    lam_avec, err_avec = meilleur(x_avec)
    _, err_sans = meilleur(x_sans)
    err_decale = _erreur_croisee(x_avec, y, lam_avec, plis, x_eval=x_sans)
    return {
        "avec": round(err_avec, 3),
        "sans": round(err_sans, 3),
        "decale": round(err_decale, 3),
    }
