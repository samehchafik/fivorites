"""Les poids internes : `axes ≈ intercept + coef · embedding`.

C'est l'apprenti du processus d'entraînement. Le LLM juge ; cette régression
n'a jamais de jugement — elle interpole entre les jugements déjà rendus. Une
ridge en forme fermée suffit : sur des vecteurs de 256 dimensions et quelques
centaines d'exemples, tout se calcule en millisecondes, sans dépendance
au-delà de numpy.

λ n'est PAS une constante, et c'est une leçon payée sur données réelles : un
λ=10 fixe, posé « par prudence », face à des embeddings OpenAI de norme 1
étalée sur 256 dimensions, écrasait ~97 % du signal — les valeurs propres de
XᵀX valent ~0,3, le facteur de rétrécissement 0,3/10,3. Résultat observé sur
le premier lot : les six axes prédits quasi identiques pour treize œuvres
très différentes — la régression rendait la moyenne d'entraînement, partout,
et son MAE *sur ses propres données* dépassait 1 point. λ se choisit donc par
validation croisée leave-one-out, en forme fermée elle aussi : pour une ridge,
le résidu LOO s'obtient du résidu d'ajustement divisé par (1 − hᵢᵢ), sans
réentraîner n fois.
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
    # Le λ retenu par la validation croisée, et l'erreur LOO qui l'a désigné.
    # C'est elle, la métrique honnête : le MAE d'ajustement flatte toujours.
    lam: float
    mae_loo: float


def train_axis(axe: str, vectors: list[list[float]], values: list[float]) -> AxisWeights:
    """Ajuste un axe. `vectors` et `values` vont par paires, sans null."""
    x = np.asarray(vectors, dtype=np.float64)
    y = np.asarray(values, dtype=np.float64)
    n, _dims = x.shape

    # Centrage : l'intercept absorbe la moyenne, la ridge ne pénalise que les
    # écarts. Sans ça, λ tirerait les prédictions vers 0 — hors de l'échelle.
    x_mean = x.mean(axis=0)
    y_mean = float(y.mean())
    xc, yc = x - x_mean, y - y_mean

    # Une seule SVD sert toute la grille : coefficients, ajustement et
    # leviers (h) ne dépendent de λ que par le filtre s²/(s²+λ).
    u, s, vt = np.linalg.svd(xc, full_matrices=False)
    uty = u.T @ yc

    best_lam, best_loo = LAMBDA_GRID[-1], float("inf")
    for lam in LAMBDA_GRID:
        filt = s**2 / (s**2 + lam)
        fitted_c = u @ (filt * uty)
        leverage = (u**2 * filt).sum(axis=1)
        # h → 1 signale un point que le modèle mémorise ; le plancher évite la
        # division par zéro et pénalise λ trop faibles, ce qui est le but.
        loo_residuals = (yc - fitted_c) / np.clip(1.0 - leverage, 1e-6, None)
        loo = float(np.abs(loo_residuals).mean())
        if loo < best_loo:
            best_lam, best_loo = lam, loo

    coef = vt.T @ ((s / (s**2 + best_lam)) * uty)
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
        mae_loo=round(best_loo, 3),
    )


def predict(vector: list[float], intercept: float, coef: list[float]) -> float:
    """La note interne d'un axe, bornée à l'échelle."""
    raw = intercept + float(np.asarray(vector, dtype=np.float64) @ np.asarray(coef))
    return round(float(np.clip(raw, SCALE_MIN, SCALE_MAX)), 1)
