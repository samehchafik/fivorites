"""Les poids internes : `axes ≈ intercept + coef · embedding`.

C'est l'apprenti du processus d'entraînement. Le LLM juge ; cette régression
n'a jamais de jugement — elle interpole entre les jugements déjà rendus. Une
ridge en forme fermée suffit : sur des vecteurs de 256 dimensions et quelques
centaines d'exemples, `(XᵀX + λI)⁻¹ Xᵀy` se calcule en millisecondes, sans
dépendance au-delà de numpy.

La régularisation est ce qui rend le démarrage à 50 œuvres possible : avec
moins d'exemples que de dimensions, la solution sans λ mémoriserait le lot au
lieu de généraliser. Attendre des premiers lots qu'ils « divergent » n'est pas
un échec, c'est la courbe d'apprentissage qui monte.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# λ de la ridge. Volontairement fort : mieux vaut des poids trop prudents qui
# convergent lot après lot que des poids qui épousent les 50 premières œuvres.
RIDGE_LAMBDA = 10.0

SCALE_MIN, SCALE_MAX = 1.0, 10.0


@dataclass(frozen=True, slots=True)
class AxisWeights:
    axe: str
    intercept: float
    coef: list[float]
    trained_on: int
    mae_fit: float


def train_axis(axe: str, vectors: list[list[float]], values: list[float]) -> AxisWeights:
    """Ajuste un axe. `vectors` et `values` vont par paires, sans null."""
    x = np.asarray(vectors, dtype=np.float64)
    y = np.asarray(values, dtype=np.float64)
    n, dims = x.shape

    # Centrage : l'intercept absorbe la moyenne, la ridge ne pénalise que les
    # écarts. Sans ça, λ tirerait les prédictions vers 0 — hors de l'échelle.
    x_mean = x.mean(axis=0)
    y_mean = float(y.mean())
    xc, yc = x - x_mean, y - y_mean

    identity = np.eye(dims)
    coef = np.linalg.solve(xc.T @ xc + RIDGE_LAMBDA * identity, xc.T @ yc)
    intercept = y_mean - float(x_mean @ coef)

    fitted = np.clip(x @ coef + intercept, SCALE_MIN, SCALE_MAX)
    mae = float(np.abs(fitted - y).mean())

    return AxisWeights(
        axe=axe,
        intercept=intercept,
        coef=[float(c) for c in coef],
        trained_on=n,
        mae_fit=round(mae, 3),
    )


def predict(vector: list[float], intercept: float, coef: list[float]) -> float:
    """La note interne d'un axe, bornée à l'échelle."""
    raw = intercept + float(np.asarray(vector, dtype=np.float64) @ np.asarray(coef))
    return round(float(np.clip(raw, SCALE_MIN, SCALE_MAX)), 1)
