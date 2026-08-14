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
import contextlib
import json
import sys
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


class Journal:
    """Duplique la sortie vers un fichier, en plus du terminal.

    Le conteneur se lance avec `--rm` : à sa sortie, `docker logs` n'a plus
    rien à montrer. Vingt heures de calcul dont on ne peut plus lire la cause
    d'échec, c'est ce qui est arrivé au premier essai — l'export ONNX a raté et
    le message est parti avec le conteneur.

    Le fichier vit dans le volume, donc il survit.
    """

    def __init__(self, chemin: Path) -> None:
        self.terminal = sys.stdout
        self.fichier = chemin.open("a", encoding="utf-8")

    def write(self, texte: str) -> None:
        self.terminal.write(texte)
        self.fichier.write(texte)
        self.fichier.flush()

    def flush(self) -> None:
        self.terminal.flush()
        self.fichier.flush()


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
    métrique dont personne ne se sert.

    Sur le point de départ, une correction : deux encodeurs entraînés
    séparément n'ont **aucune** base commune. Mesuré, le cosinus de départ vaut
    −0,002 — l'alignement de deux directions sans rapport. L'élève n'a donc pas
    à ajuster une représentation déjà proche, il a tout un changement de repère
    à apprendre. C'est faisable, c'est même l'exercice ordinaire de la
    distillation, mais ça demande de laisser assez de couches libres : geler
    presque tout ne laisserait pas de quoi tourner l'espace.

    Le terme quadratique, à faible poids, tient les normes pendant que le
    cosinus s'occupe des directions.
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


def _poids_exporte(sortie: Path) -> int:
    """Le poids reel de l'export, fichiers de donnees externes compris.

    `model.onnx` seul ne pese qu'un megaoctet : au-dela de 2 Go, protobuf
    refuse d'embarquer les tenseurs et ONNX les ecrit a cote, dans
    `model.onnx.data`. Annoncer la taille du seul graphe donne « 1 Mo » pour un
    modele de 130 — le meme genre de chiffre faux que celui qui a laisse croire
    au retaillage d'ALiBi : exact sur ce qu'il mesure, trompeur sur ce qu'il
    pretend dire.
    """
    return sum(f.stat().st_size for f in sortie.glob("model.onnx*"))


def _retailler_alibi(modele, longueur: int) -> tuple[int, int]:
    """Ramene le biais ALiBi a `longueur` positions, et verifie que c'est fait.

    Appeler `rebuild_alibi_tensor` ne suffit pas : la premiere version de ce
    code l'appelait, annoncait fierement « retaille a 256 positions », et
    produisait quand meme un fichier de 2,27 Go. Le compte tombait juste — 8
    tetes x 8 192 x 8 192 flottants font 537 M de valeurs, plus les 33 M de
    parametres du modele — donc le tenseur n'avait pas bouge.

    D'ou cette version, qui ne fait pas confiance a l'appel : elle parcourt les
    tampons et les attributs, decoupe tout ce qui porte « alibi » et depasse la
    longueur voulue, et **rend les tailles avant et apres** pour qu'on puisse
    le lire au lieu de l'esperer. Un retaillage qu'on annonce sans le mesurer
    ne vaut rien — celui-la a coute un export de 2,27 Go et une comparaison
    perdue.
    """
    encodeur = getattr(modele, "encoder", None)
    rebatir = getattr(encodeur, "rebuild_alibi_tensor", None)
    if callable(rebatir):
        try:
            rebatir(size=longueur)
        except TypeError:
            with contextlib.suppress(Exception):
                rebatir(longueur)

    avant = apres = 0
    for module in modele.modules():
        candidats = list(module._buffers.items()) + [
            (nom, valeur)
            for nom, valeur in vars(module).items()
            if isinstance(valeur, torch.Tensor)
        ]
        for nom, valeur in candidats:
            if valeur is None or "alibi" not in nom.lower() or valeur.dim() < 2:
                continue
            avant += valeur.numel() * valeur.element_size()
            if valeur.shape[-1] > longueur:
                petit = valeur[..., :longueur, :longueur].contiguous()
                if nom in module._buffers:
                    module._buffers[nom] = petit
                else:
                    setattr(module, nom, petit)
                valeur = petit
            apres += valeur.numel() * valeur.element_size()
    return avant, apres


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

    # Retailler le biais ALiBi AVANT de tracer, sans quoi l'export echoue sur
    # « larger than the 2GiB limit imposed by protobuf » — pour un modele de
    # 33 M de parametres, ce qui a de quoi surprendre.
    #
    # L'explication : jina v2 n'a pas de plongements de position, il ajoute un
    # biais d'attention precalcule pour ses 8 192 positions maximales. Le
    # tenseur fait 8 tetes x 8 192 x 8 192 x 4 octets, soit 2,1 Go, et le trace
    # le fige en constante dans le graphe. A 256 tokens il tombe a 2 Mo.
    #
    # Consequence a ne pas perdre de vue : le graphe exporte n'accepte plus que
    # `longueur` tokens. C'est pour ca que la borne part avec lui dans
    # `fivorites.json` — la deviner cote production serait une erreur muette,
    # le modele rendrait des vecteurs sur un texte tronque sans le dire.
    avant_octets, apres_octets = _retailler_alibi(modele, longueur)
    if avant_octets:
        print(
            f"biais ALiBi : {avant_octets / 1e6:.0f} Mo -> {apres_octets / 1e6:.1f} Mo"
            f" ({longueur} positions)"
        )

    exemple = tokenizer(
        ["texte d'exemple pour figer les axes"],
        padding="max_length",
        truncation=True,
        max_length=min(longueur, 128),
        return_tensors="pt",
    )
    # `.eval()` sur l'ENVELOPPE, pas seulement sur le corps. Un module qu'on
    # vient de construire naît en mode entraînement, et `torch.onnx.export`
    # regarde le module du dessus : sans ça il avertit « exporting a model
    # while it is in training mode », ce qui est vrai et trompeur à la fois —
    # le corps, lui, était bien en eval.
    enveloppe = AvecPooling(modele).cpu().eval()
    entrees = (exemple["input_ids"].cpu(), exemple["attention_mask"].cpu())
    axes = {
        "input_ids": {0: "lot", 1: "tokens"},
        "attention_mask": {0: "lot", 1: "tokens"},
        "vecteur": {0: "lot"},
    }

    # Deux exportateurs, essayes dans cet ordre. Le recent (dynamo) comprend
    # mieux le Python moderne ; l'ancien (TorchScript) trace l'execution et se
    # moque de la facon dont le modele est ecrit — ce qui compte face a une
    # implementation d'attention apportee par le modele lui-meme, que personne
    # n'a ecrite en pensant a l'export.
    #
    # Les deux echouent parfois pour des raisons opposees, d'ou la cascade
    # plutot qu'un choix. Et les erreurs sont reunies : une seule des deux ne
    # dirait pas si le probleme vient du modele ou de l'exportateur.
    echecs: list[str] = []
    for nom, options in (("dynamo", {"dynamo": True}), ("torchscript", {"dynamo": False})):
        try:
            torch.onnx.export(
                enveloppe,
                entrees,
                str(sortie / "model.onnx"),
                input_names=["input_ids", "attention_mask"],
                output_names=["vecteur"],
                dynamic_axes=axes,
                # 18 et non 14 : l'exportateur récent produit du 18 puis tente
                # de redescendre, échoue sur `axes_input_to_attribute`, et
                # garde le 18 de toute façon. Autant le demander et se passer
                # d'une conversion qui ne sert à rien. `onnxruntime` le lit
                # depuis sa version 1.15.
                opset_version=18,
                **options,
            )
            print(f"export ONNX reussi ({nom})")
            break
        except Exception as exc:  # noqa: BLE001 — on veut la cause, quelle qu'elle soit
            echecs.append(f"{nom} : {type(exc).__name__} — {exc}")
    else:
        raise RuntimeError("aucun exportateur ONNX n'a abouti.\n  " + "\n  ".join(echecs))

    # Un elève de 33 M de parametres pese ~130 Mo. Bien au-dela, c'est qu'une
    # constante geante a suivi dans le graphe — et l'export precedent l'a
    # prouve : 2,27 Go, dont 2,1 de biais ALiBi non retaille. Le dire ici evite
    # de le decouvrir au chargement, par un message d'onnxruntime qui ne
    # nommera pas la cause.
    poids = _poids_exporte(sortie)
    if poids > 500e6:
        print(
            f"⚠ {poids / 1e6:.0f} Mo exportes pour un modele qui en pese ~130."
            " Une constante geante a suivi — verifier le retaillage d'ALiBi."
        )

    tokenizer.save_pretrained(sortie)
    # La borne en tokens voyage avec le modele : le graphe la porte en dur
    # depuis le retaillage d'ALiBi, et la production doit la respecter.
    (sortie / "fivorites.json").write_text(
        json.dumps({"maxTokens": longueur, "dimensions": 512}, indent=2), encoding="utf-8"
    )


def geler(modele, couches: int) -> tuple[int, int]:
    """Gèle les plongements et les `couches` premières couches de l'encodeur.

    Sur processeur, c'est le réglage qui décide de la faisabilité. La passe
    avant reste entière — il faut bien traverser tout le réseau — mais la passe
    arrière ne remonte plus que jusqu'à la première couche entraînée, et elle
    pèse les deux tiers du calcul.

    Ce qu'on perd : les couches basses d'un encodeur portent la syntaxe et le
    vocabulaire, les hautes le sens de l'énoncé. C'est le sens qu'on veut
    déplacer ici, donc les geler coûte peu — mais ce n'est pas gratuit, et sur
    GPU il n'y a aucune raison de le faire.

    **`jina-v2-small` n'a que quatre couches.** Le nombre demandé est donc
    plafonné pour en laisser au moins une entraînable : `--geler 4` gelait
    l'intégralité du réseau, ne laissant que le pooler — que ce script
    n'utilise même pas, puisqu'il fait sa propre moyenne masquée. Résultat, un
    graphe sans le moindre paramètre à dériver et un `backward` qui échoue au
    premier lot, une heure après le lancement.
    """
    if couches <= 0:
        return 0, sum(p.numel() for p in modele.parameters())
    bloc = getattr(getattr(modele, "encoder", None), "layer", None)
    if bloc is None:
        print("⚠ structure de couches non reconnue — rien n'est gelé.")
        return 0, sum(p.numel() for p in modele.parameters())

    profondeur = len(list(bloc))
    demande, couches = couches, min(couches, profondeur - 1)
    if demande != couches:
        print(
            f"⚠ le modèle n'a que {profondeur} couches : --geler {demande} les gèlerait"
            f" toutes. Ramené à {couches}, pour en laisser une entraînable."
        )

    figes = []
    if hasattr(modele, "embeddings"):
        figes.extend(modele.embeddings.parameters())
    for couche in list(bloc)[:couches]:
        figes.extend(couche.parameters())
    for parametre in figes:
        parametre.requires_grad_(False)
    entrainables = sum(p.numel() for p in modele.parameters() if p.requires_grad)
    return sum(p.numel() for p in figes), entrainables


def sauver_reprise(
    chemin: Path, modele, optimiseur, planning, etat: dict, meilleurs_poids: dict | None
) -> None:
    """Écrit l'état complet, par un fichier temporaire renommé.

    Le renommage est atomique sur le même système de fichiers. Écrire
    directement sur la reprise exposerait à la perdre entièrement si la
    machine tombait pendant les quelques secondes de l'écriture — soit
    précisément le scénario contre lequel elle existe.
    """
    provisoire = chemin.with_suffix(".tmp")
    torch.save(
        {
            "modele": modele.state_dict(),
            "optimiseur": optimiseur.state_dict(),
            "planning": planning.state_dict(),
            "meilleurs_poids": meilleurs_poids,
            **etat,
        },
        provisoire,
    )
    provisoire.replace(chemin)


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--corpus", type=Path, default=Path("corpus.jsonl"))
    parseur.add_argument("--sortie", type=Path, default=Path("eleve-distille"))
    parseur.add_argument("--epoques", type=int, default=3)
    parseur.add_argument("--lot", type=int, default=8)
    # Sur GPU, 1 024 : l'attention coûte le carré de la longueur, et le dossier
    # place en tête ce qui porte le ton — genres, mots-clés, synopsis,
    # Wikipédia. Ce qui se fait couper est la fin d'une liste de synopsis
    # d'épisodes répétitifs.
    #
    # Sur processeur, descendre à 384 ou 256 : le facteur est quadratique, donc
    # passer de 1 024 à 256 divise le temps par bien plus que quatre. La tête du
    # dossier tient dans 256 tokens, et c'est elle qui porte le ton.
    parseur.add_argument("--longueur", type=int, default=1024)
    parseur.add_argument("--pas", type=float, default=2e-5)
    parseur.add_argument("--patience", type=int, default=2)
    parseur.add_argument(
        "--limite", type=int, default=0, help="Plafonne le corpus. 0 = tout prendre."
    )
    parseur.add_argument(
        "--geler", type=int, default=0, help="Couches basses gelées (utile sur processeur)."
    )
    parseur.add_argument("--fils", type=int, default=0, help="Fils de calcul. 0 = laisser torch.")
    parseur.add_argument(
        "--reprise", type=Path, default=Path("reprise.pt"), help="Fichier d'état pour reprendre."
    )
    parseur.add_argument("--tous-les", type=int, default=200, help="Sauver l'état tous les N lots.")
    parseur.add_argument(
        "--exporter-seulement",
        action="store_true",
        help="Relire la reprise et rejouer l'export, sans entraîner.",
    )
    args = parseur.parse_args()

    sys.stdout = Journal(args.sortie.parent / "journal.txt")

    if args.fils > 0:
        torch.set_num_threads(args.fils)
    appareil = "cuda" if torch.cuda.is_available() else "cpu"
    if appareil == "cpu":
        print(
            "⚠ aucun GPU — comptez des dizaines d'heures.\n"
            "  Détacher le processus (nohup, tmux), et laisser la reprise faire son travail :\n"
            "  une coupure ne coûte au pire que les derniers lots.\n"
            "  Réglages conseillés : --longueur 256 --geler 1 --lot 16 --fils 4"
        )

    apprentissage, surveillance = charger(args.corpus)
    if args.limite > 0:
        apprentissage = apprentissage[: args.limite]
    print(f"{len(apprentissage)} paires d'apprentissage, {len(surveillance)} de surveillance")
    if len(apprentissage) < 1000:
        print("⚠ corpus très court : élargir avec `training corpus --limit 20000` d'abord.")

    tokenizer = AutoTokenizer.from_pretrained(ELEVE, trust_remote_code=True)
    modele = AutoModel.from_pretrained(ELEVE, trust_remote_code=True).to(appareil)

    # L'export seul. Il existe pour une raison precise : un entrainement de
    # vingt heures dont l'ECRITURE echoue laisse ses poids dans la reprise —
    # ils ne sont pas perdus, seulement pas encore sortis. Refaire les vingt
    # heures pour rejouer trente secondes d'export serait absurde, et l'erreur
    # redevient visible en quelques secondes au lieu d'une nuit.
    if args.exporter_seulement:
        if not args.reprise.exists():
            print(f"ERREUR : {args.reprise} introuvable — rien a exporter.")
            return
        etat = torch.load(args.reprise, map_location="cpu", weights_only=False)
        poids = etat.get("meilleurs_poids") or etat["modele"]
        quels = "meilleurs" if etat.get("meilleurs_poids") else "derniers (aucun meilleur retenu)"
        modele.load_state_dict(poids)
        print(f"poids {quels}, cosinus {etat.get('meilleur', float('nan')):.4f} — export…")
        exporter_onnx(modele, tokenizer, args.sortie, args.longueur)
        print(f"ecrit dans {args.sortie} ({_poids_exporte(args.sortie) / 1e6:.0f} Mo)")
        return

    if args.geler > 0:
        figes, entrainables = geler(modele, args.geler)
        print(f"{figes / 1e6:.1f} M de paramètres gelés, {entrainables / 1e6:.1f} M entraînables")
    # Le garde-fou qui a manqué : sans lui, `backward` échoue au premier lot
    # avec « element 0 of tensors does not require grad », message qui ne dit
    # nulle part que le vrai problème est un gel trop large. Et il échoue
    # APRÈS le cosinus de départ, donc après plusieurs minutes de calcul.
    a_deriver = [p for p in modele.parameters() if p.requires_grad]
    if not a_deriver:
        print("ERREUR : plus aucun paramètre entraînable — baisser --geler.")
        return

    def charge(lignes: list[dict], melange: bool, graine: int = 0) -> DataLoader:
        # Le mélange est semé par l'époque, pas laissé au hasard : la reprise
        # doit retrouver EXACTEMENT la même suite de lots pour pouvoir sauter
        # ceux qui sont déjà passés. Sans ça, reprendre au lot 3 000 rejouerait
        # d'autres exemples et l'époque serait à la fois incomplète et
        # partiellement doublée.
        generateur = torch.Generator().manual_seed(graine) if melange else None
        return DataLoader(
            Paires(lignes),
            batch_size=args.lot,
            shuffle=melange,
            generator=generateur,
            collate_fn=lambda lot: collationner(lot, tokenizer, args.longueur),
        )

    veille = charge(surveillance, False)
    lots_par_epoque = max((len(apprentissage) + args.lot - 1) // args.lot, 1)

    optimiseur = torch.optim.AdamW(a_deriver, lr=args.pas, weight_decay=0.01)
    planning = torch.optim.lr_scheduler.OneCycleLR(
        optimiseur, max_lr=args.pas, total_steps=lots_par_epoque * args.epoques, pct_start=0.1
    )

    debut_epoque, debut_lot, meilleurs_poids = 1, 0, None
    if args.reprise.exists():
        etat = torch.load(args.reprise, map_location=appareil, weights_only=False)
        modele.load_state_dict(etat["modele"])
        optimiseur.load_state_dict(etat["optimiseur"])
        planning.load_state_dict(etat["planning"])
        meilleurs_poids = etat["meilleurs_poids"]
        debut_epoque, debut_lot = etat["epoque"], etat["lot"]
        depart, meilleur, sterile = etat["depart"], etat["meilleur"], etat["sterile"]
        print(
            f"reprise depuis {args.reprise} : époque {debut_epoque}, lot {debut_lot},"
            f" meilleur cosinus {meilleur:.4f}"
        )
    else:
        depart = surveiller(modele, veille, appareil)
        meilleur, sterile = depart, 0
        print(f"cosinus au départ, sans entraînement : {depart:.4f}")

    for epoque in range(debut_epoque, args.epoques + 1):
        train = charge(apprentissage, True, graine=epoque)
        cumul, lots = 0.0, 0
        for encodage, cibles in train:
            lots += 1
            # Les lots déjà passés sont retraversés mais pas recalculés : la
            # tokenisation d'un lot coûte des millisecondes, l'entraînement des
            # secondes. C'est le prix d'une reprise exacte, et il est dérisoire.
            if lots <= debut_lot:
                continue
            encodage = {c: v.to(appareil) for c, v in encodage.items()}
            valeur = perte(vecteur(modele, encodage), cibles.to(appareil))
            valeur.backward()
            torch.nn.utils.clip_grad_norm_([p for p in modele.parameters() if p.requires_grad], 1.0)
            optimiseur.step()
            planning.step()
            optimiseur.zero_grad(set_to_none=True)
            # `.detach()` explicite : `float()` le fait tout seul, mais en
            # avertissant — et un avertissement dans un journal de vingt heures
            # finit par ressembler à un symptôme.
            cumul += float(valeur.detach())
            vus = lots - debut_lot
            if lots % 50 == 0:
                print(
                    f"  époque {epoque} · lot {lots}/{lots_par_epoque}"
                    f" · perte {cumul / max(vus, 1):.4f}",
                    flush=True,
                )
            if lots % args.tous_les == 0:
                sauver_reprise(
                    args.reprise,
                    modele,
                    optimiseur,
                    planning,
                    {
                        "epoque": epoque,
                        "lot": lots,
                        "depart": depart,
                        "meilleur": meilleur,
                        "sterile": sterile,
                    },
                    meilleurs_poids,
                )
        debut_lot = 0

        score = surveiller(modele, veille, appareil)
        print(
            f"époque {epoque} — perte {cumul / max(lots, 1):.4f}, cosinus hors-tranche {score:.4f}",
            flush=True,
        )

        # Arrêt précoce : sans lui, l'élève finit par apprendre ses exemples
        # par cœur et rend un cosinus d'apprentissage flatteur pour un vecteur
        # inutile sur une œuvre jamais vue.
        if score > meilleur + 1e-4:
            meilleur, sterile = score, 0
            meilleurs_poids = {c: v.detach().cpu().clone() for c, v in modele.state_dict().items()}
        else:
            sterile += 1
        sauver_reprise(
            args.reprise,
            modele,
            optimiseur,
            planning,
            {
                "epoque": epoque + 1,
                "lot": 0,
                "depart": depart,
                "meilleur": meilleur,
                "sterile": sterile,
            },
            meilleurs_poids,
        )
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
    print(f"écrit dans {args.sortie} ({_poids_exporte(args.sortie) / 1e6:.0f} Mo)")
    print("\nÀ copier dans l'image admin, puis :")
    print(f"  EMBEDDER=local:/opt/models/{args.sortie.name}")
    print("  docker compose run --rm admin training encodeurs \\")
    print(f"      --modeles local:/opt/models/{args.sortie.name},openai/text-embedding-3-large@512")
    print("\nDéployer seulement si l'élève tient la comparaison sur les œuvres notées.")


if __name__ == "__main__":
    main()
