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

# En dessous, une pente estimée sur les prédictions hors-pli est du bruit :
# on ne calibre pas, on garde la prédiction prudente.
MIN_CALIBRATION = 30


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
    # Le facteur de recalibration appliqué (1,0 = aucun) : la ridge comprime
    # l'échelle vers la moyenne, la pente mesurée sur les prédictions
    # hors-pli sert à la redilater. Replié dans coef/intercept.
    pente: float = 1.0


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
    preds = _predictions_croisees(x, y, lam, plis, x_eval=x_eval)
    ok = ~np.isnan(preds)
    if not ok.any():
        return float("inf")
    return float(np.abs(np.clip(preds[ok], SCALE_MIN, SCALE_MAX) - y[ok]).mean())


def _predictions_croisees(
    x: np.ndarray, y: np.ndarray, lam: float, plis: int, x_eval: np.ndarray | None = None
) -> np.ndarray:
    """Les prédictions hors-pli, NaN pour les points jamais mis de côté.

    Non bornées à l'échelle, exprès : la calibration mesure la compression sur
    la prédiction brute, et borner d'abord fausserait la pente aux extrêmes —
    là où, précisément, la compression se voit.
    """
    preds = np.full(len(y), np.nan)
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
        cible = x if x_eval is None else x_eval
        preds[test] = (cible[test] - x_mean) @ coef + y_mean
    return preds


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

    # La recalibration. Une ridge tire ses prédictions vers la moyenne — c'est
    # le mécanisme même de la régularisation — et la compression se paie aux
    # extrêmes : les « 8 » du juge ressortaient à 6, et une œuvre très
    # contrastée comme Game of Thrones rendait six valeurs tassées autour de 6.
    #
    # On égalise l'**écart-type**, pas la pente. La nuance décide de tout : la
    # pente de régression `cov(y,p)/var(p)` est celle qui minimise l'erreur
    # quadratique, et elle laisse par construction `sd(prédit) = r · sd(juge)`.
    # Avec un r de 0,84 à 0,93 selon l'axe, il manque encore 7 à 16 % d'
    # amplitude après correction — mesuré sur 502 œuvres : l'écart-type prédit
    # valait 75 à 87 % de celui du juge, et l'amplitude moyenne par œuvre 4,5
    # contre 5,4.
    #
    # Ce qu'on croyait payer ne se paie pas. Redilater redilate le bruit, donc
    # le MAE devait remonter — mesuré, il ne bouge pas (et descend sur `reve`,
    # de 0,85 à 0,74). La raison est que l'erreur d'une prédiction trop tassée
    # est déjà systématique aux extrêmes : la dilatation corrige un biais avant
    # d'ajouter de la variance.
    #
    # Et ce qui se gagne compte, parce que la distance sera un cosine : la
    # similarité moyenne entre œuvres tombe de 0,902 à 0,860, où le juge est à
    # 0,853. Sans cette correction, tout se ressemble.
    #
    # Ridge et correction étant linéaires toutes deux, la correction se replie
    # dans les coefficients : rien ne change ni au schéma ni à la prédiction,
    # qui reste `intercept + coef · x`.
    preds = _predictions_croisees(x, y, best_lam, plis)
    ok = ~np.isnan(preds)
    pente = 1.0
    if ok.sum() >= MIN_CALIBRATION:
        p, cible = preds[ok], y[ok]
        ecart = float(p.std())
        corr = float(np.corrcoef(p, cible)[0, 1]) if ecart > 1e-6 else 0.0
        if corr > 0.2:
            # Bornée : un facteur démesuré signale des prédictions presque
            # plates (le régime « moyenne partout » déjà rencontré), et
            # l'amplifier fabriquerait du délire calibré.
            pente = float(np.clip(float(cible.std()) / ecart, 1.0, 2.5))
    if pente != 1.0:
        recentrage = float(y.mean()) - pente * float(np.nanmean(preds))
        coef = coef * pente
        intercept = intercept * pente + recentrage
        best_cv = float(
            np.abs(np.clip(preds[ok] * pente + recentrage, SCALE_MIN, SCALE_MAX) - y[ok]).mean()
        )

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
        pente=round(pente, 2),
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


# Les tailles de voisinage explorées. Trop petit, la prédiction recopie une
# œuvre et hérite de son bruit ; trop grand, elle retombe sur la moyenne du
# corpus, c'est-à-dire sur le défaut qu'on cherche justement à corriger.
VOISINS_GRID = (3, 5, 10, 20, 40)


def _predictions_voisins(x: np.ndarray, y: np.ndarray, k: int, plis: int) -> np.ndarray:
    """Prédictions hors-pli par les k plus proches voisins, en cosine.

    Même découpage que la ridge — le même `plis`, le même pas — sans quoi les
    deux erreurs ne seraient pas comparables et la comparaison ne dirait rien.

    Le cosine et non l'euclidien : c'est la distance dans laquelle vivent les
    embeddings, et celle que la couche produit utilisera.
    """
    normes = np.linalg.norm(x, axis=1, keepdims=True)
    xn = x / np.where(normes > 1e-12, normes, 1.0)
    preds = np.full(len(y), np.nan)
    for pli in range(plis):
        test = np.arange(pli, len(y), plis)
        if len(test) == 0 or len(test) == len(y):
            continue
        garde = np.ones(len(y), dtype=bool)
        garde[test] = False
        similarites = xn[test] @ xn[garde].T
        voisins = np.argsort(-similarites, axis=1)[:, :k]
        proches = np.take_along_axis(similarites, voisins, axis=1)
        # Pondération par la similarité, ramenée à zéro au-delà du voisinage :
        # une moyenne simple donnerait autant de poids au 40ᵉ voisin qu'au 1ᵉʳ,
        # ce qui reproduit la moyenne du corpus dès que k grandit.
        poids = np.clip(proches - proches[:, -1:], 0, None)
        somme = poids.sum(axis=1, keepdims=True)
        poids = np.where(somme > 1e-12, poids / np.where(somme > 1e-12, somme, 1.0), 1.0 / k)
        preds[test] = (poids * y[garde][voisins]).sum(axis=1)
    return preds


def comparer_modeles(
    axe: str, vectors: list[list[float]], values: list[float]
) -> dict[str, object]:
    """Ridge contre plus proches voisins, sur le même découpage.

    La question que ça tranche : le plafond vient-il de la matière, ou de la
    **forme** du modèle ? Une ridge est linéaire ; un espace d'embeddings ne
    l'est pas. « Cette série est drôle malgré son intrigue de policier
    surnaturel » n'est probablement pas une projection linéaire, mais c'est
    exactement ce que dit un voisinage — à condition que les voisins soient les
    bons.

    On rend aussi l'écart-type restitué : une erreur moyenne identique peut
    cacher deux comportements opposés, l'un qui range tout au centre et l'autre
    qui ose les extrêmes. C'est cette seconde propriété qui fait un vecteur de
    goût utilisable en cosine.
    """
    x = np.asarray(vectors, dtype=np.float64)
    y = np.asarray(values, dtype=np.float64)
    plis = len(y) if len(y) <= 60 else 10

    ridge = train_axis(axe, vectors, values)
    preds_ridge = _predictions_croisees(x, y, ridge.lam, plis) * ridge.pente
    ok = ~np.isnan(preds_ridge)
    if ok.any():
        preds_ridge[ok] += float(y.mean()) - float(np.nanmean(preds_ridge))
    preds_ridge = np.clip(preds_ridge, SCALE_MIN, SCALE_MAX)

    voisins: dict[str, object] = {}
    for k in VOISINS_GRID:
        if k >= len(y):
            continue
        r = _resume(_predictions_voisins(x, y, k, plis), y, voisins=k)
        if not voisins or float(r["maeCv"]) < float(voisins["maeCv"]):  # type: ignore[arg-type]
            voisins = r

    noyau: dict[str, object] = {}
    for echelle in GAMMA_GRID:
        for lam in (0.03, 0.1, 0.3, 1.0):
            r = _resume(
                _predictions_noyau(x, y, echelle, lam, plis), y, echelle=echelle, lam=lam
            )
            if not noyau or float(r["maeCv"]) < float(noyau["maeCv"]):  # type: ignore[arg-type]
                noyau = r

    reseau = _resume(_predictions_reseau(x, y, plis), y, caches="32-16")

    return {
        "axe": axe,
        "oeuvres": len(y),
        "ridge": _resume(preds_ridge, y, lam=ridge.lam),
        "voisins": voisins,
        "noyau": noyau,
        "reseau": reseau,
    }


# La largeur du noyau, en multiples de la distance médiane entre œuvres. La
# médiane est l'échelle naturelle du nuage : trop étroit, chaque œuvre n'est
# proche que d'elle-même et le modèle recopie ; trop large, tout se ressemble
# et on retombe sur la moyenne.
GAMMA_GRID = (0.25, 0.5, 1.0, 2.0)


def _noyau(a: np.ndarray, b: np.ndarray, gamma: float) -> np.ndarray:
    d2 = np.maximum(
        (a * a).sum(1)[:, None] + (b * b).sum(1)[None, :] - 2.0 * (a @ b.T),
        0.0,
    )
    return np.exp(-gamma * d2)


def _predictions_noyau(
    x: np.ndarray, y: np.ndarray, echelle: float, lam: float, plis: int
) -> np.ndarray:
    """Ridge à noyau gaussien, hors-pli.

    Non linéaire, mais en forme close : à 502 exemples la matrice de Gram fait
    502×502 et s'inverse instantanément. C'est le bon outil quand les exemples
    sont peu nombreux — là où un réseau n'a pas de quoi apprendre ses poids.
    """
    preds = np.full(len(y), np.nan)
    for pli in range(plis):
        test = np.arange(pli, len(y), plis)
        if len(test) == 0 or len(test) == len(y):
            continue
        garde = np.ones(len(y), dtype=bool)
        garde[test] = False
        xa, ya = x[garde], y[garde]
        # L'échelle se mesure sur le pli d'entraînement seul : la calculer sur
        # tout le jeu ferait fuiter les points de test dans le modèle.
        d2 = np.maximum(
            (xa * xa).sum(1)[:, None] + (xa * xa).sum(1)[None, :] - 2.0 * (xa @ xa.T), 0.0
        )
        mediane = float(np.median(d2[d2 > 0])) if (d2 > 0).any() else 1.0
        gamma = echelle / max(mediane, 1e-9)
        k = _noyau(xa, xa, gamma)
        moyenne = float(ya.mean())
        alpha = np.linalg.solve(k + lam * np.eye(len(ya)), ya - moyenne)
        preds[test] = _noyau(x[test], xa, gamma) @ alpha + moyenne
    return preds


def _predictions_reseau(
    x: np.ndarray,
    y: np.ndarray,
    plis: int,
    *,
    caches: tuple[int, int] = (32, 16),
    epoques: int = 1500,
) -> np.ndarray:
    """Un perceptron à trois couches, hors-pli. Écrit à la main : le projet n'a
    ni torch ni scikit-learn, et n'en veut pas pour un essai.

    Entrées centrées-réduites, deux couches cachées en tanh, sortie linéaire,
    descente de gradient avec inertie et décroissance des poids. L'a priori
    reste défavorable — 502 exemples pour 512 entrées, c'est le régime où un
    réseau apprend le bruit — mais c'est mesurable, donc mesuré.
    """
    rng = np.random.default_rng(7)
    preds = np.full(len(y), np.nan)
    n1, n2 = caches
    for pli in range(plis):
        test = np.arange(pli, len(y), plis)
        if len(test) == 0 or len(test) == len(y):
            continue
        garde = np.ones(len(y), dtype=bool)
        garde[test] = False
        # Centrage seul, sans réduction. Les embeddings sont homogènes — même
        # échelle sur toutes les dimensions par construction — et diviser par
        # l'écart-type y amplifierait les directions les moins porteuses de
        # signal jusqu'au niveau des autres. Mesuré sur le contrôle : avec
        # réduction, le réseau apprenait son pli par cœur et rendait 3,1
        # hors-pli là où un noyau rendait 0,28.
        mu = x[garde].mean(0)
        xt = x[test] - mu
        # Arrêt précoce, sans quoi le test serait truqué : avec 1 568 poids
        # pour une centaine d'exemples, le réseau apprend son pli par cœur —
        # mesuré sur le XOR de contrôle, 0,000 d'erreur d'entraînement et 3,1
        # hors-pli. On garde donc une tranche du pli d'entraînement pour
        # surveiller, et on retient les poids du meilleur passage.
        tous = np.arange(garde.sum())
        surveille = tous % 7 == 0
        xa = (x[garde] - mu)[~surveille]
        ya = y[garde][~surveille]
        xv, yv = (x[garde] - mu)[surveille], y[garde][surveille]
        cible = ya.mean()

        d = xa.shape[1]
        w1 = rng.normal(0, np.sqrt(1.0 / d), (d, n1))
        w2 = rng.normal(0, np.sqrt(1.0 / n1), (n1, n2))
        w3 = rng.normal(0, np.sqrt(1.0 / n2), (n2, 1))
        b1, b2 = np.zeros(n1), np.zeros(n2)
        b3 = np.zeros(1)
        # Adam plutôt qu'une descente à inertie : sur un XOR de contrôle, la
        # seconde plafonnait à 1,6 de MAE après dix mille époques là où Adam
        # descend à 0,3 en mille. Un réseau qui n'apprend pas rendrait la
        # comparaison inutile — il « perdrait » sans qu'on sache si c'est la
        # méthode ou l'optimiseur.
        moments = [np.zeros_like(p) for p in (w1, b1, w2, b2, w3, b3)]
        carres = [np.zeros_like(p) for p in (w1, b1, w2, b2, w3, b3)]
        pas, b_1, b_2, eps, decroissance = 0.01, 0.9, 0.999, 1e-8, 1e-3
        meilleur, meilleurs_poids = float("inf"), None

        for pas_num in range(1, epoques + 1):
            h1 = np.tanh(xa @ w1 + b1)
            h2 = np.tanh(h1 @ w2 + b2)
            sortie = (h2 @ w3 + b3).ravel() + cible
            erreur = (sortie - ya) / len(ya)
            g3 = h2.T @ erreur[:, None] + decroissance * w3
            gb3 = np.array([erreur.sum()])
            d2_ = (erreur[:, None] @ w3.T) * (1 - h2**2)
            g2 = h1.T @ d2_ + decroissance * w2
            gb2 = d2_.sum(0)
            d1_ = (d2_ @ w2.T) * (1 - h1**2)
            g1 = xa.T @ d1_ + decroissance * w1
            gb1 = d1_.sum(0)
            for param, grad, m, v in zip(
                (w1, b1, w2, b2, w3, b3),
                (g1, gb1, g2, gb2, g3, gb3),
                moments,
                carres,
                strict=True,
            ):
                m *= b_1
                m += (1 - b_1) * grad
                v *= b_2
                v += (1 - b_2) * grad * grad
                mc = m / (1 - b_1**pas_num)
                vc = v / (1 - b_2**pas_num)
                param -= pas * mc / (np.sqrt(vc) + eps)

            if pas_num % 25 == 0:
                hv = np.tanh(np.tanh(xv @ w1 + b1) @ w2 + b2)
                erreur_v = float(np.abs((hv @ w3 + b3).ravel() + cible - yv).mean())
                if erreur_v < meilleur:
                    meilleur = erreur_v
                    meilleurs_poids = [p.copy() for p in (w1, b1, w2, b2, w3, b3)]

        if meilleurs_poids is not None:
            w1, b1, w2, b2, w3, b3 = meilleurs_poids

        h1 = np.tanh(xt @ w1 + b1)
        preds[test] = (np.tanh(h1 @ w2 + b2) @ w3 + b3).ravel() + cible
    return preds


def _resume(p: np.ndarray, y: np.ndarray, **extra: object) -> dict[str, object]:
    m = ~np.isnan(p)
    if not m.any():
        return {"maeCv": float("inf"), "dispersion": 0.0, "correlation": 0.0, **extra}
    pc = np.clip(p[m], SCALE_MIN, SCALE_MAX)
    return {
        "maeCv": round(float(np.abs(pc - y[m]).mean()), 3),
        "dispersion": round(float(pc.std() / y[m].std()), 2) if y[m].std() > 1e-9 else 0.0,
        "correlation": round(float(np.corrcoef(pc, y[m])[0, 1]), 2) if pc.std() > 1e-9 else 0.0,
        **extra,
    }
