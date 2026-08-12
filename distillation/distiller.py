"""Apprendre au petit modèle local à reproduire la représentation du gros.

C'est une **distillation** : l'élève ne voit jamais une note du juge, il voit
le vecteur que le professeur a produit sur le même dossier. Deux conséquences
qui font tout l'intérêt de la méthode ici.

La cible est un vecteur de 512 nombres, pas six notes. Chaque œuvre apporte
512 signaux au lieu de six, ce qui rend l'exercice possible sur quelques
milliers d'exemples là où une régression supervisée en demanderait des
millions.

Et le corpus n'a besoin d'**aucune étiquette**. La limite des 502 œuvres
jugées, qui borne tout le reste du projet, ne s'applique pas : n'importe quel
dossier fait l'affaire, y compris ceux de la traîne obscure — et c'est
justement la traîne que l'élève devra savoir traiter.

Ce qu'on ne fait PAS ici, et pourquoi : apprendre une projection par-dessus un
élève gelé. Ce serait trente secondes de calcul sans GPU, et ça ne servirait à
rien. Une fonction du vecteur de jina ne peut pas retrouver ce que jina a
jeté ; c'est le même argument qui a condamné le réseau à trois couches posé
derrière la régression. Il faut réentraîner le **corps** de l'encodeur, sinon
on n'a rien distillé.

Attente raisonnable : un élève de 33 M de paramètres récupère typiquement 80 à
95 % de l'écart qui le sépare du professeur. Mesuré sur 502 œuvres notées,
jina rend 1,020 de MAE et `text-embedding-3-large@512` 0,853 — viser ~0,88,
gratuit à l'usage et sans dépendance réseau.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
import torch.nn.functional as fonctions
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModel, AutoTokenizer

ELEVE = "jinaai/jina-embeddings-v2-small-en"

# La part du corpus réservée à la surveillance. Le découpage se fait sur le
# reste de l'identifiant TMDB, pas au hasard : relancer l'entraînement doit
# redonner la même partition, sans quoi comparer deux essais ne veut rien dire.
PART_SURVEILLANCE = 10


class Paires(Dataset):
    """Les paires `dossier → vecteur du professeur`, telles que l'export les rend."""

    def __init__(self, lignes: list[dict]) -> None:
        self.lignes = lignes

    def __len__(self) -> int:
        return len(self.lignes)

    def __getitem__(self, i: int) -> dict:
        return self.lignes[i]


def charger(chemin: Path) -> tuple[list[dict], list[dict]]:
    """Lit le JSONL et le coupe en apprentissage / surveillance."""
    apprentissage: list[dict] = []
    surveillance: list[dict] = []
    with chemin.open(encoding="utf-8") as fichier:
        for ligne in fichier:
            if not ligne.strip():
                continue
            paire = json.loads(ligne)
            cible = surveillance if paire["idTmdb"] % PART_SURVEILLANCE == 0 else apprentissage
            cible.append(paire)
    return apprentissage, surveillance


def collationner(lot: list[dict], tokenizer, longueur: int) -> tuple[dict, torch.Tensor]:
    encodage = tokenizer(
        [p["text"] for p in lot],
        padding=True,
        truncation=True,
        max_length=longueur,
        return_tensors="pt",
    )
    cibles = torch.tensor([p["vector"] for p in lot], dtype=torch.float32)
    return encodage, cibles


def vecteur(modele, encodage: dict) -> torch.Tensor:
    """Moyenne masquée puis normalisation — le pooling de jina v2.

    Il faut le refaire à la main ici : `AutoModel` rend les états cachés, pas
    le vecteur de phrase. Se tromper de pooling produirait un élève qui
    apprend très bien à imiter une grandeur que la production ne calcule pas.
    """
    sorties = modele(**encodage).last_hidden_state
    masque = encodage["attention_mask"].unsqueeze(-1).float()
    moyenne = (sorties * masque).sum(1) / masque.sum(1).clamp(min=1e-9)
    return fonctions.normalize(moyenne, p=2, dim=1)


def perte(eleve: torch.Tensor, professeur: torch.Tensor) -> torch.Tensor:
    """Cosinus d'abord, quadratique en appoint.

    Le cosinus parce que c'est la distance que la production utilise : un
    élève qui reproduirait les normes sans les directions serait bon sur une
    métrique dont personne ne se sert. Le terme quadratique, à faible poids,
    stabilise le début d'entraînement — le cosinus seul est plat quand les
    vecteurs sont déjà presque alignés, ce qui est le cas dès la première
    époque entre deux encodeurs entraînés sur du texte.
    """
    cible = fonctions.normalize(professeur, p=2, dim=1)
    return (
        1.0 - fonctions.cosine_similarity(eleve, cible, dim=1)
    ).mean() + 0.1 * fonctions.mse_loss(eleve, cible)


@torch.no_grad()
def surveiller(modele, chargeur, appareil: str) -> float:
    """Le cosinus moyen sur la tranche mise de côté. Plus haut est meilleur."""
    modele.eval()
    total = 0.0
    vus = 0
    for encodage, cibles in chargeur:
        encodage = {c: v.to(appareil) for c, v in encodage.items()}
        rendu = vecteur(modele, encodage)
        cible = fonctions.normalize(cibles.to(appareil), p=2, dim=1)
        total += float(fonctions.cosine_similarity(rendu, cible, dim=1).sum())
        vus += len(cibles)
    modele.train()
    return total / max(vus, 1)


def exporter_onnx(modele, tokenizer, sortie: Path, longueur: int) -> None:
    """Écrit le modèle en ONNX, format que la production sait déjà servir.

    Le pooling et la normalisation sont **inclus dans le graphe** : sinon il
    faudrait les réécrire côté `embed.py`, à l'identique, et la moindre
    divergence entre les deux implémentations produirait des vecteurs
    silencieusement différents de ceux qu'on vient d'apprendre.
    """

    class AvecPooling(torch.nn.Module):
        def __init__(self, corps) -> None:
            super().__init__()
            self.corps = corps

        def forward(self, input_ids, attention_mask):
            sorties = self.corps(
                input_ids=input_ids, attention_mask=attention_mask
            ).last_hidden_state
            masque = attention_mask.unsqueeze(-1).float()
            moyenne = (sorties * masque).sum(1) / masque.sum(1).clamp(min=1e-9)
            return fonctions.normalize(moyenne, p=2, dim=1)

    sortie.mkdir(parents=True, exist_ok=True)
    modele.eval()
    exemple = tokenizer(
        ["texte d'exemple pour figer les axes"],
        padding="max_length",
        truncation=True,
        max_length=min(longueur, 128),
        return_tensors="pt",
    )
    torch.onnx.export(
        AvecPooling(modele).cpu(),
        (exemple["input_ids"].cpu(), exemple["attention_mask"].cpu()),
        str(sortie / "model.onnx"),
        input_names=["input_ids", "attention_mask"],
        output_names=["embedding"],
        dynamic_axes={
            "input_ids": {0: "lot", 1: "tokens"},
            "attention_mask": {0: "lot", 1: "tokens"},
            "embedding": {0: "lot"},
        },
        opset_version=14,
    )
    tokenizer.save_pretrained(sortie)


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--corpus", type=Path, default=Path("corpus.jsonl"))
    parseur.add_argument("--sortie", type=Path, default=Path("eleve-distille"))
    parseur.add_argument("--epoques", type=int, default=3)
    parseur.add_argument("--lot", type=int, default=8)
    # 1 024 plutôt que les 8 192 que jina accepte : l'attention coûte le carré
    # de la longueur, et le dossier place en tête ce qui porte le ton — genres,
    # mots-clés, synopsis, Wikipédia. Ce qui se fait couper est la fin d'une
    # liste de synopsis d'épisodes répétitifs.
    parseur.add_argument("--longueur", type=int, default=1024)
    parseur.add_argument("--pas", type=float, default=2e-5)
    parseur.add_argument("--patience", type=int, default=2)
    args = parseur.parse_args()

    appareil = "cuda" if torch.cuda.is_available() else "cpu"
    if appareil == "cpu":
        print("⚠ aucun GPU détecté — comptez des heures plutôt que des minutes.")

    apprentissage, surveillance = charger(args.corpus)
    print(f"{len(apprentissage)} paires d'apprentissage, {len(surveillance)} de surveillance")
    if len(apprentissage) < 1000:
        print("⚠ corpus très court : élargir avec `training corpus --limit 20000` d'abord.")

    tokenizer = AutoTokenizer.from_pretrained(ELEVE, trust_remote_code=True)
    modele = AutoModel.from_pretrained(ELEVE, trust_remote_code=True).to(appareil)

    def charge(lignes: list[dict], melange: bool) -> DataLoader:
        return DataLoader(
            Paires(lignes),
            batch_size=args.lot,
            shuffle=melange,
            collate_fn=lambda lot: collationner(lot, tokenizer, args.longueur),
        )

    train = charge(apprentissage, True)
    veille = charge(surveillance, False)

    optimiseur = torch.optim.AdamW(modele.parameters(), lr=args.pas, weight_decay=0.01)
    total = max(len(train) * args.epoques, 1)
    planning = torch.optim.lr_scheduler.OneCycleLR(
        optimiseur, max_lr=args.pas, total_steps=total, pct_start=0.1
    )

    depart = surveiller(modele, veille, appareil)
    print(f"cosinus au départ, sans entraînement : {depart:.4f}")

    meilleur, meilleurs_poids, sterile = depart, None, 0
    for epoque in range(1, args.epoques + 1):
        cumul, lots = 0.0, 0
        for encodage, cibles in train:
            encodage = {c: v.to(appareil) for c, v in encodage.items()}
            valeur = perte(vecteur(modele, encodage), cibles.to(appareil))
            valeur.backward()
            torch.nn.utils.clip_grad_norm_(modele.parameters(), 1.0)
            optimiseur.step()
            planning.step()
            optimiseur.zero_grad(set_to_none=True)
            cumul += float(valeur)
            lots += 1
            if lots % 50 == 0:
                print(f"  époque {epoque} · lot {lots}/{len(train)} · perte {cumul / lots:.4f}")

        score = surveiller(modele, veille, appareil)
        print(
            f"époque {epoque} — perte {cumul / max(lots, 1):.4f}, cosinus hors-tranche {score:.4f}"
        )

        # Arrêt précoce : sans lui, l'élève finit par apprendre ses exemples
        # par cœur et rend un cosinus d'apprentissage flatteur pour un vecteur
        # inutile sur une œuvre jamais vue.
        if score > meilleur + 1e-4:
            meilleur, sterile = score, 0
            meilleurs_poids = {c: v.detach().cpu().clone() for c, v in modele.state_dict().items()}
        else:
            sterile += 1
            if sterile >= args.patience:
                print(f"aucun gain depuis {sterile} époque(s) — arrêt.")
                break

    if meilleurs_poids is not None:
        modele.load_state_dict(meilleurs_poids)
    print(f"\nmeilleur cosinus hors-tranche : {meilleur:.4f} (départ {depart:.4f})")
    if meilleur <= depart + 1e-3:
        print("⚠ aucun gain sur la tranche de surveillance — ne pas déployer cet élève.")
        return

    exporter_onnx(modele, tokenizer, args.sortie, args.longueur)
    taille = (args.sortie / "model.onnx").stat().st_size / 1e6
    print(f"écrit dans {args.sortie} ({taille:.0f} Mo)")
    print("\nÀ copier dans l'image admin, puis :")
    print(f"  EMBEDDER=local:/opt/models/{args.sortie.name}")
    print("  docker compose run --rm admin training encodeurs \\")
    print(f"      --modeles local:/opt/models/{args.sortie.name},openai/text-embedding-3-large@512")
    print("\nDéployer seulement si l'élève tient la comparaison sur les œuvres notées.")


if __name__ == "__main__":
    main()
