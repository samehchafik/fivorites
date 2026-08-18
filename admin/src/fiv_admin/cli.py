"""Point d'entrée en ligne de commande.

Les comptes se gèrent ici et nulle part ailleurs : le front n'a ni inscription
ni création d'utilisateur.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Coroutine
from pathlib import Path
from typing import Annotated, Any

import psycopg
import typer
from psycopg.rows import dict_row

from fiv_admin.config import VENDOR_DIR, get_settings
from fiv_admin.db import MigrationsNotFound, connect, migrate
from fiv_admin.redact import SecretFilter, redact_dsn
from fiv_admin.security import hash_password

app = typer.Typer(help="Administration Fivorites V2 — suivi de l'acquisition", no_args_is_help=True)
db_app = typer.Typer(help="Base de données", no_args_is_help=True)
user_app = typer.Typer(help="Comptes d'administration", no_args_is_help=True)
catalog_app = typer.Typer(help="Projection d'affichage du catalogue", no_args_is_help=True)
training_app = typer.Typer(help="Entraînement de la notation", no_args_is_help=True)
search_app = typer.Typer(help="Recherche plein texte (Elasticsearch)", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(user_app, name="user")
app.add_typer(catalog_app, name="catalog")
app.add_typer(training_app, name="training")
app.add_typer(search_app, name="search")


@training_app.command("note")
def training_note(
    limit: Annotated[
        int, typer.Option("--limit", "-n", min=1, max=500, help="Combien de séries noter.")
    ] = 10,
    bareme: Annotated[
        str | None, typer.Option("--bareme", help="Version du barème. Défaut : la plus récente.")
    ] = None,
    univers: Annotated[
        str, typer.Option("--univers", help="series (défaut) ou movies.")
    ] = "series",
    legendes: Annotated[
        bool,
        typer.Option("--legendes", help="Décrire les visuels et les joindre au dossier (payant)."),
    ] = False,
    inedites: Annotated[
        bool, typer.Option("--inedites", help="Seulement les œuvres jamais jugées, tous barèmes.")
    ] = False,
    sans_filtre: Annotated[
        bool, typer.Option("--sans-filtre", help="Ne pas exiger d'affiche.")
    ] = False,
    rejouer: Annotated[
        bool,
        typer.Option("--rejouer", help="Reprendre aussi les œuvres déjà notées sur ce barème."),
    ] = False,
    apercu: Annotated[
        bool,
        typer.Option("--apercu", help="Afficher la liste et le coût estimé, sans rien appeler."),
    ] = False,
    pause: Annotated[
        float, typer.Option("--pause", min=0.0, help="Secondes d'attente entre deux œuvres.")
    ] = 0.0,
) -> None:
    """Note les N séries les plus populaires pas encore jugées sur le barème.

    C'est le remplissage de la phase 1 : la page Training note une œuvre à la
    fois, ce que soixante œuvres rendent intenable. Même chemin exactement —
    même dossier, mêmes juges, même journal — seule l'échelle change.

    « Pas encore jugées SUR LE BARÈME » : l'entraînement des poids filtre par
    version, donc une note rendue sous un barème précédent ne nourrit pas le
    suivant. Une œuvre déjà vue en v1 revient donc dans la liste pour v2, et
    la mention « déjà v1 » le dit en clair. `--inedites` restreint aux œuvres
    jamais jugées, quand on cherche à élargir plutôt qu'à compléter.

    Les œuvres déjà notées sur ce barème-ci sont sautées, donc relancer la
    commande continue le lot au lieu de le refaire : c'est un appel payant par
    œuvre, et on ne paie jamais deux fois la même. `--rejouer` lève cette
    protection et reprend tout — après un prompt corrigé ou des légendes
    ajoutées. Rien n'est écrasé : le nouvel essai s'empile à côté de l'ancien
    dans le journal, et c'est le plus récent que l'atelier montre.

    La liste exige une affiche ; `--sans-filtre` lève cette condition. Le
    descriptif n'entre pas dans le filtre : le champ est mal calibré pour cet
    usage, et c'est la taille du dossier assemblé qui décide en aval.

    `--legendes` ajoute la description des visuels au dossier — un appel de
    vision par œuvre, plus cher que la notation elle-même. Éteint par défaut :
    on règle d'abord le barème sur du texte, on paie l'image ensuite.

    `--apercu` montre la liste et le coût estimé sans rien appeler. À utiliser
    la première fois : c'est la seule façon de voir ce qu'on s'apprête à payer.
    """
    import time

    from fiv_admin.llm import LlmError
    from fiv_admin.routes.training import (
        DossierMaigre,
        NonCollectee,
        note_work,
        works_a_noter,
    )

    settings = get_settings()
    if not settings.openai_api_key and not apercu:
        typer.echo("ERREUR : OPENAI_API_KEY absente — rien à noter sans juge.")
        typer.echo("→ la renseigner dans le .env, à côté du docker-compose.yml")
        raise typer.Exit(1)

    async def run() -> int:
        async with connect(settings.database_url, settings.sourcing_schema, "admin") as conn:
            async with conn.cursor() as cur:
                if bareme:
                    await cur.execute(
                        "select version, prompt, axes from notation.rubric where version = %s",
                        (bareme,),
                    )
                else:
                    # Sans précision, le barème le plus récent : c'est celui que
                    # l'atelier propose par défaut, et deux entrées qui
                    # noteraient sur des barèmes différents rendraient les
                    # écarts incomparables.
                    await cur.execute(
                        "select version, prompt, axes from notation.rubric"
                        " order by created_at desc limit 1"
                    )
                row = await cur.fetchone()
            if row is None:
                typer.echo(f"barème introuvable : {bareme or 'aucun barème en base'}")
                raise typer.Exit(1)
            version, prompt, axes = row

            candidates = await works_a_noter(
                conn,
                version,
                limit,
                inedites=inedites,
                filtres=not sans_filtre,
                rejouer=rejouer,
                univers=univers,
            )
            if not candidates:
                typer.echo(f"aucune œuvre à noter sur le barème {version} — tout est déjà jugé.")
                return 0

            typer.echo(f"barème {version} · {univers} · {len(candidates)} œuvre(s) à noter")
            if apercu:
                for n, c in enumerate(candidates, start=1):
                    pop = f"{c['popularity']:.1f}" if c["popularity"] is not None else "—"
                    note = f"{c['note']:.1f}" if c["note"] is not None else "—"
                    # « déjà v1 » : l'œuvre a été jugée sous un autre barème.
                    # Sans cette mention, la liste paraît proposer des séries
                    # déjà notées — elle propose en fait de les noter ICI.
                    vu = f"  [déjà {', '.join(c['deja'])}]" if c["deja"] else ""
                    typer.echo(
                        f"  {n:3d}. {c['id_tmdb']:>8}  pop {pop:>7}  note {note:>4}  "
                        f"{(c['titre'] or '')[:45]}{vu}"
                    )
                # L'ordre de grandeur, pas une facture : le dossier et les
                # légendes varient d'une série à l'autre. Assez pour décider.
                typer.echo(
                    f"\naperçu seul, rien n'a été appelé — coût estimé "
                    f"~{len(candidates) * (0.004 if legendes else 0.001):.2f} $ "
                    f"({'légendes comprises' if legendes else 'sans légendes'})"
                )
                return 0

            notees = sautees = 0
            for n, c in enumerate(candidates, start=1):
                titre = (c["titre"] or str(c["id_tmdb"]))[:45]
                try:
                    essai = await note_work(
                        conn,
                        settings,
                        id_tmdb=c["id_tmdb"],
                        rubric_version=version,
                        prompt=prompt,
                        axes=axes,
                        captions=legendes,
                        univers=univers,
                    )
                except DossierMaigre as exc:
                    typer.echo(f"  {n:3d}/{len(candidates)} ⨯ {titre} — {exc}")
                    sautees += 1
                    continue
                except (NonCollectee, LlmError) as exc:
                    # Une œuvre qui échoue ne doit pas emporter le lot : les
                    # précédentes sont déjà payées et écrites.
                    typer.echo(f"  {n:3d}/{len(candidates)} ⨯ {titre} — {exc}")
                    sautees += 1
                    continue

                scores = essai["openai"]["scores"]
                resume = " ".join(
                    f"{axe[:3]}:{scores.get(axe, {}).get('score') or '∅'}" for axe in axes
                )
                typer.echo(f"  {n:3d}/{len(candidates)} ✓ {titre:<45} {resume}")
                notees += 1
                if pause:
                    time.sleep(pause)

            typer.echo(f"\n{notees} notée(s), {sautees} sautée(s) sur le barème {version}.")
            if notees:
                typer.echo(
                    "→ prochaine étape : le bouton « Entraînement » de Training 2, "
                    "qui refait les poids et régénère les vecteurs."
                )
            return notees

    _run(run())


@training_app.command("poids")
def training_poids(
    bareme: Annotated[
        str | None, typer.Option("--bareme", help="Version du barème. Défaut : la plus récente.")
    ] = None,
) -> None:
    """Réentraîne la régression sur toutes les notes du barème.

    Le même travail que le bouton « Entraînement » de Training 2, par le même
    chemin : la régression est refaite sur tout l'historique de notes, chaque
    axe choisit son λ par validation croisée, et les vecteurs internes des
    œuvres déjà jugées sont régénérés dans la foulée — des poids neufs
    périment les prédictions faites avec les anciens.

    En ligne de commande parce que c'est long : assembler les dossiers et
    calculer les embeddings prend des minutes sur plusieurs dizaines
    d'œuvres, ce qu'une requête web supporte mal. Rien n'est appelé chez
    OpenAI si les embeddings sont déjà en cache.
    """
    from fiv_admin.llm import LlmError
    from fiv_admin.routes.training import PasAssezDOeuvres, _rubric, entrainer_poids

    settings = get_settings()
    if not settings.openai_api_key:
        typer.echo("ERREUR : OPENAI_API_KEY absente — les embeddings en dépendent.")
        raise typer.Exit(1)

    async def run() -> None:
        async with connect(settings.database_url, settings.sourcing_schema, "admin") as conn:
            if bareme:
                rubric = await _rubric(conn, bareme)
            else:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "select version, prompt, axes from notation.rubric"
                        " order by created_at desc limit 1"
                    )
                    rubric = await cur.fetchone()
                if rubric is None:
                    typer.echo("aucun barème en base.")
                    raise typer.Exit(1)

            typer.echo(f"barème {rubric['version']} — assemblage des dossiers…")
            try:
                bilan = await entrainer_poids(conn, settings, rubric)
            except PasAssezDOeuvres as exc:
                typer.echo(f"ERREUR : {exc}")
                raise typer.Exit(1) from exc
            except LlmError as exc:
                typer.echo(f"ERREUR : {exc}")
                raise typer.Exit(1) from exc

            typer.echo(f"\nentraîné sur {bilan['works']} œuvre(s) :")
            for axe in bilan["axes"]:
                if axe.get("skipped"):
                    typer.echo(f"  {axe['axe']:12s} trop peu de notes ({axe['trainedOn']})")
                else:
                    typer.echo(
                        f"  {axe['axe']:12s} MAE cv {axe['maeCv']:5.2f}"
                        f"  (ajustement {axe['maeFit']:5.2f}, lambda {axe['lambda']},"
                        f" recalibration ×{axe.get('pente', 1.0)})"
                    )
            if bilan.get("skipped"):
                typer.echo(
                    f"\n{len(bilan['skipped'])} œuvre(s) écartée(s), dossier non plongeable : "
                    + ", ".join(str(i) for i in bilan["skipped"][:10])
                )
            typer.echo(f"\n{bilan['generated']} vecteur(s) interne(s) régénéré(s).")
            typer.echo(
                "La colonne « MAE cv » est celle qui compte : elle mesure ce que les poids"
                " feraient sur une œuvre jamais vue."
            )

    _run(run())


@training_app.command("encodeurs")
def training_encodeurs(
    bareme: Annotated[
        str | None, typer.Option("--bareme", help="Version du barème. Défaut : la plus récente.")
    ] = None,
    modeles: Annotated[
        str | None,
        typer.Option("--modeles", help="Liste séparée par des virgules. Défaut : les candidats."),
    ] = None,
    apercu: Annotated[
        bool,
        typer.Option("--apercu", help="Afficher les candidats et le coût, sans rien appeler."),
    ] = False,
) -> None:
    """Compare des encodeurs sur les notes déjà rendues, et n'écrit rien.

    C'est la façon de trancher la question ouverte n°5 du plan — « quel
    encodeur pour la traîne ? » — par la mesure plutôt que par les classements
    publics, qui évaluent de la recherche documentaire et non une régression
    vers six axes de goût.

    Le protocole est celui de l'entraînement : mêmes œuvres, mêmes notes, même
    régression ; seul l'encodeur change. Le chiffre comparé est l'erreur de
    validation croisée, c'est-à-dire ce que chaque encodeur permettrait de
    prédire sur une œuvre jamais vue.

    Un candidat préfixé `openai/` passe par l'API au lieu d'un modèle local, et
    devient payant — quelques dizaines de centimes pour cinq cents dossiers.
    C'est le seul moyen de tester l'hypothèse que les quatre candidats locaux
    ne peuvent pas départager : ils s'équivalent à 0,006 près parce qu'ils sont
    de la même famille, tous petits, tous entraînés pour la similarité
    sémantique. Le voisinage de Lucifer a rendu la question concrète — le
    titre est dans le dossier, mais aucun d'eux ne sait ce qu'il désigne.

        --modeles jinaai/jina-embeddings-v2-small-en,openai/text-embedding-3-large

    Le suffixe `@512` demande à l'API un vecteur raccourci, pour comparer à
    dimension égale : sans ça, un gain pourrait ne venir que des 3 072
    dimensions face aux 512 de jina. `--apercu` chiffre la dépense sans appeler.

    Aucun poids n'est écrit ; changer d'encodeur reste un geste explicite, à
    faire dans `embed.py` au vu de ces chiffres. Les vecteurs d'API, eux, sont
    gardés sous leur propre étiquette : relancer la comparaison ne les repaie
    donc pas, et ils servent de matière à une distillation — apprendre au petit
    modèle local à reproduire la représentation du gros, sans avoir besoin
    d'une seule note du juge.
    """
    from fiv_admin.routes.training import (
        ENCODEURS_CANDIDATS,
        PasAssezDOeuvres,
        _rubric,
        apercu_encodeurs,
        comparer_encodeurs,
    )

    settings = get_settings()
    candidats = tuple(m.strip() for m in modeles.split(",")) if modeles else ENCODEURS_CANDIDATS

    async def run() -> None:
        async with connect(settings.database_url, settings.sourcing_schema, "admin") as conn:
            if bareme:
                rubric = await _rubric(conn, bareme)
            else:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "select version, prompt, axes from notation.rubric"
                        " order by created_at desc limit 1"
                    )
                    rubric = await cur.fetchone()
                if rubric is None:
                    typer.echo("aucun barème en base.")
                    raise typer.Exit(1)

            typer.echo(
                f"barème {rubric['version']} · {len(candidats)} encodeur(s) à comparer"
                " — le premier passage télécharge les modèles."
            )
            try:
                devis = await apercu_encodeurs(conn, rubric, candidats)
            except PasAssezDOeuvres as exc:
                typer.echo(f"ERREUR : {exc}")
                raise typer.Exit(1) from exc

            for m in devis["modeles"]:
                paye = m["modele"].startswith("openai/")
                reste = f"{m['aEncoder']} à encoder"
                prix = f"~{m['cout']:.2f} $" if paye else "gratuit"
                typer.echo(
                    f"  {'API' if paye else 'local':<6} {m['modele']:<38} {reste:>16}  {prix}"
                )
            cout = float(devis["cout"])
            typer.echo(
                f"\n{devis['oeuvres']} dossier(s)"
                + (
                    f" — coût estimé ~{cout:.2f} $"
                    if cout
                    else " — gratuit : tout est local ou déjà en cache"
                )
            )
            if apercu:
                typer.echo("aperçu seul, rien n'a été encodé.")
                return

            try:
                resultats = await comparer_encodeurs(conn, settings, rubric, candidats)
            except PasAssezDOeuvres as exc:
                typer.echo(f"ERREUR : {exc}")
                raise typer.Exit(1) from exc

            typer.echo("\nErreur de validation croisée — plus bas est meilleur :\n")
            for rang, r in enumerate(resultats, start=1):
                moy = f"{r['moyenne']:.3f}" if r["moyenne"] is not None else "—"
                typer.echo(f"  {rang}. {r['modele']:<40} {r['dims']:>4} dims   moyenne {moy}")
                detail = "  ".join(f"{a['axe'][:3]} {a['maeCv']:.2f}" for a in r["axes"])
                typer.echo(f"     {detail}")
            typer.echo(
                "\nLe modèle retenu se change dans admin/src/fiv_admin/embed.py"
                " (MODEL_NAME, DIMENSIONS, EMBEDDER), puis on réentraîne."
            )

    _run(run())


@training_app.command("visuels")
def training_visuels(
    bareme: Annotated[
        str | None, typer.Option("--bareme", help="Version du barème. Défaut : la plus récente.")
    ] = None,
) -> None:
    """Chiffre ce que les légendes visuelles apportent, et ce que leur absence coûte.

    Mêmes œuvres, mêmes notes, deux dossiers qui ne diffèrent que par la
    section MEDIA. Trois colonnes en sortie :

    * `avec`   — le modèle actuel, entraîné et évalué sur dossiers légendés ;
    * `sans`   — le même, entraîné et évalué sans les légendes : l'écart avec
      la première dit ce que les visuels apportent réellement ;
    * `décalé` — poids appris AVEC, appliqués à une œuvre SANS. C'est la
      situation exacte de la traîne si on décide de ne pas la légender, et
      elle ne se déduit d'aucune des deux autres.

    N'écrit rien, n'appelle aucune API : tout est local et gratuit. La
    décision — payer les légendes sur la traîne, ou non — se prend au vu de
    ces chiffres.
    """
    from fiv_admin.routes.training import PasAssezDOeuvres, _rubric, comparer_visuels

    settings = get_settings()

    async def run() -> None:
        async with connect(settings.database_url, settings.sourcing_schema, "admin") as conn:
            if bareme:
                rubric = await _rubric(conn, bareme)
            else:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "select version, prompt, axes from notation.rubric"
                        " order by created_at desc limit 1"
                    )
                    rubric = await cur.fetchone()
                if rubric is None:
                    typer.echo("aucun barème en base.")
                    raise typer.Exit(1)

            typer.echo(f"barème {rubric['version']} — assemblage des deux jeux de dossiers…")
            try:
                bilan = await comparer_visuels(conn, settings, rubric)
            except PasAssezDOeuvres as exc:
                typer.echo(f"ERREUR : {exc}")
                raise typer.Exit(1) from exc

            typer.echo(
                f"\n{bilan['oeuvres']} œuvre(s), dont {bilan['legendees']} légendée(s)."
                " Erreur de validation croisée, plus bas est meilleur :\n"
            )
            typer.echo(f"  {'axe':<12} {'avec':>7} {'sans':>7} {'décalé':>8}   apport   coût")
            apports, couts = [], []
            for a in bilan["axes"]:
                apport = a["sans"] - a["avec"]
                cout = a["decale"] - a["avec"]
                apports.append(apport)
                couts.append(cout)
                typer.echo(
                    f"  {a['axe']:<12} {a['avec']:7.3f} {a['sans']:7.3f} {a['decale']:8.3f}"
                    f"  {apport:+7.3f} {cout:+6.3f}"
                )
            if apports:
                typer.echo(
                    f"  {'MOYENNE':<12} {'':7} {'':7} {'':8}"
                    f"  {sum(apports) / len(apports):+7.3f} {sum(couts) / len(couts):+6.3f}"
                )
            typer.echo(
                "\n« apport » = ce que les légendes font gagner quand elles sont là."
                "\n« coût »   = ce que perd une œuvre non légendée jugée par ces poids."
                "\nLe second décide de la traîne : faible, elle peut rester nue."
            )

    _run(run())


@training_app.command("modeles")
def training_modeles(
    bareme: Annotated[
        str | None, typer.Option("--bareme", help="Version du barème. Défaut : la plus récente.")
    ] = None,
) -> None:
    """Ridge contre plus proches voisins, sur les mêmes œuvres et les mêmes plis.

    La question jamais posée : le plafond vient-il de la matière, ou de la
    **forme** du modèle ? Le volume a été éliminé (deux plateaux mesurés),
    l'encodeur aussi (trois candidats à 0,006 près), et la calibration restitue
    désormais 93 à 103 % de l'amplitude. Reste que la régression est linéaire,
    et qu'un espace d'embeddings ne l'est pas.

    Le cas qui l'a rendu visible : Lucifer, notée 6 en joie par le juge et 3,1
    par la ridge — classée 98ᵉ sur 502 quand le juge la met 290ᵉ. Une erreur de
    rang, qu'aucune calibration de sortie ne corrige.

    Trois colonnes par modèle :

    * `MAE cv`      — l'erreur sur des œuvres jamais vues, la seule honnête ;
    * `dispersion`  — l'écart-type rendu, rapporté à celui du juge. 100 % = le
      modèle ose autant que lui ; 60 % = il range tout au centre ;
    * `corrélation` — l'accord sur l'ordre, qui est ce qui manque à Lucifer.

    N'écrit rien et n'appelle aucune API : les embeddings sont déjà en cache.
    """
    from fiv_admin.routes.training import PasAssezDOeuvres, _rubric, comparer_modeles

    settings = get_settings()

    async def run() -> None:
        async with connect(settings.database_url, settings.sourcing_schema, "admin") as conn:
            if bareme:
                rubric = await _rubric(conn, bareme)
            else:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "select version, prompt, axes from notation.rubric"
                        " order by created_at desc limit 1"
                    )
                    rubric = await cur.fetchone()
                if rubric is None:
                    typer.echo("aucun barème en base.")
                    raise typer.Exit(1)

            typer.echo(f"barème {rubric['version']} — assemblage des dossiers…")
            try:
                bilan = await comparer_modeles(conn, settings, rubric)
            except PasAssezDOeuvres as exc:
                typer.echo(f"ERREUR : {exc}")
                raise typer.Exit(1) from exc

            typer.echo(f"\n{bilan['oeuvres']} œuvre(s). MAE cv, plus bas est meilleur.\n")
            typer.echo(
                f"  {'axe':<11}{'ridge':>21}{'voisins':>21}{'noyau RBF':>21}{'réseau 3c':>21}"
            )
            entete = f"{'MAE':>7}{'disp':>7}{'corr':>7}"
            typer.echo(f"  {'':<11}{entete}{entete}{entete}{entete}")
            gains: dict[str, list[float]] = {"voisins": [], "noyau": [], "reseau": []}
            for a in bilan["axes"]:
                ligne = f"  {a['axe']:<11}"
                for nom in ("ridge", "voisins", "noyau", "reseau"):
                    m = a[nom]
                    if not m:
                        ligne += f"{'—':>21}"
                        continue
                    ligne += f"{m['maeCv']:>7.3f}{m['dispersion']:>7.0%}{m['correlation']:>7.2f}"
                    if nom != "ridge":
                        gains[nom].append(a["ridge"]["maeCv"] - m["maeCv"])
                typer.echo(ligne)
            typer.echo("")
            for nom, valeurs in gains.items():
                if valeurs:
                    moyenne = sum(valeurs) / len(valeurs)
                    verdict = "mieux que la ridge" if moyenne > 0.02 else "pas mieux"
                    typer.echo(f"  gain moyen {nom:<9}: {moyenne:+.3f}   {verdict}")
            typer.echo(
                "\nUn gain positif dirait que la forme du modèle était le plafond."
                "\nS'ils perdent tous, il ne reste que la matière — donc l'enrichissement."
            )

    _run(run())


@training_app.command("corpus")
def training_corpus(
    limit: Annotated[
        int, typer.Option("--limit", "-n", min=1, help="Combien d'œuvres encoder, par popularité.")
    ] = 5000,
    univers: Annotated[
        str, typer.Option("--univers", help="series (défaut) ou movies.")
    ] = "series",
    modele: Annotated[
        str, typer.Option("--modele", help="L'encodeur professeur, préfixé openai/.")
    ] = "openai/text-embedding-3-large@512",
    apercu: Annotated[
        bool, typer.Option("--apercu", help="Compter et chiffrer, sans rien appeler.")
    ] = False,
) -> None:
    """Constitue le corpus de distillation : des paires dossier → vecteur professeur.

    Encode les N œuvres les plus populaires avec un encodeur d'API et range les
    vecteurs. On apprendra ensuite au petit modèle local à les reproduire.

    Pourquoi ça marche sur quelques milliers d'œuvres quand la notation en
    demanderait des millions : la cible est un vecteur de 512 nombres, pas six
    notes. Chaque œuvre apporte 512 signaux au lieu de six. Et le corpus n'a
    besoin d'aucune note du juge — la limite des 502 œuvres jugées, qui borne
    tout le reste du projet, ne s'applique pas ici.

    `@512` et non les 3 072 natives : l'élève sort 512 dimensions, et une cible
    de même forme évite d'avoir à apprendre en plus une couche de projection.

    L'écriture se fait lot par lot. Une interruption laisse en base tout ce qui
    a été encodé jusque-là, et relancer la commande reprend où elle s'était
    arrêtée au lieu de repayer. `--apercu` chiffre avant d'engager.

    Palier conseillé : 5 000 pour un premier signal, 20 000 pour un résultat
    exploitable. On ne devine pas — on distille à chaque palier et on regarde
    le MAE cv sur les œuvres notées, seul juge. Quand la courbe s'aplatit,
    c'est assez.
    """
    from fiv_admin.llm import LlmError
    from fiv_admin.routes.training import constituer_corpus

    settings = get_settings()

    async def run() -> None:
        async with connect(settings.database_url, settings.sourcing_schema, "admin") as conn:
            typer.echo(f"{modele} · {univers} · assemblage des dossiers…")

            def montrer(faits: int, total: int) -> None:
                typer.echo(f"  {faits}/{total} encodée(s)")

            try:
                bilan = await constituer_corpus(
                    conn,
                    settings,
                    modele,
                    limit=limit,
                    univers=univers,
                    apercu=apercu,
                    progres=montrer,
                )
            except LlmError as exc:
                typer.echo(f"ERREUR : {exc}")
                raise typer.Exit(1) from exc

            typer.echo(
                f"\ncandidates  : {bilan['candidates']}"
                f"\ndossiers    : {bilan['dossiers']}"
                f"\ndéjà en base: {bilan['enCache']}"
                f"\nà encoder   : {bilan['aEncoder']}  (~{bilan['cout']:.2f} $)"
            )
            if apercu:
                typer.echo("\naperçu seul, rien n'a été appelé.")
            else:
                typer.echo(f"encodées    : {bilan['encodes']}")

    _run(run())


@training_app.command("corpus-export")
def training_corpus_export(
    sortie: Annotated[Path, typer.Option("--sortie", help="Le fichier JSONL à écrire.")] = Path(
        "/tmp/corpus.jsonl"
    ),
    professeur: Annotated[
        str, typer.Option("--professeur", help="L'étiquette d'encodeur à exporter.")
    ] = "text-embedding-3-large@512",
) -> None:
    """Exporte les paires dossier → vecteur, pour entraîner l'élève ailleurs.

    La distillation ne tourne pas ici : elle demande torch, que cette image
    n'embarque pas, et une heure de GPU loué plutôt que des jours de CPU. Ce
    qu'elle demande d'ici, c'est le corpus — et le corpus doit sortir par ce
    chemin plutôt que par une requête SQL, parce que **le texte n'est pas
    stocké**. Seul son sha l'est. Le dossier se réassemble donc par le code
    qui sait le faire, avec les mêmes sections dans le même ordre.

    Le sha est revérifié paire par paire : une œuvre enrichie depuis son
    encodage a changé de dossier, son vecteur ne lui correspond plus, et la
    paire est écartée. Enseigner une correspondance périmée serait pire que
    de perdre l'exemple.

    Gratuit, aucun appel. Pour récupérer le fichier depuis le conteneur :

        docker compose run --rm -v "$PWD:/sortie" admin \\
            training corpus-export --sortie /sortie/corpus.jsonl
    """
    from fiv_admin.routes.training import exporter_corpus

    settings = get_settings()

    async def run() -> None:
        async with connect(settings.database_url, settings.sourcing_schema, "admin") as conn:
            typer.echo(f"professeur {professeur} → {sortie}")

            def montrer(faits: int, total: int) -> None:
                typer.echo(f"  {faits}/{total}")

            try:
                fichier = sortie.open("w", encoding="utf-8")
            except (PermissionError, OSError) as exc:
                # L'image tourne sous l'uid 10002, pas sous celui qui lance
                # `docker compose run`. Monter son répertoire personnel donne
                # donc un volume que le conteneur ne peut pas écrire — et la
                # trace Python parle de pathlib, ce qui n'aide personne.
                typer.echo(f"ERREUR : impossible d'écrire {sortie} — {exc}")
                typer.echo("→ le conteneur tourne sous l'uid 10002, pas sous le tien.")
                typer.echo("  mkdir -p export && sudo chown 10002:10002 export")
                typer.echo(
                    '  docker compose run --rm -v "$PWD/export:/sortie" admin \\'
                    "\n      training corpus-export --sortie /sortie/corpus.jsonl"
                )
                raise typer.Exit(1) from exc
            with fichier:
                bilan = await exporter_corpus(conn, professeur, fichier, progres=montrer)

            typer.echo(
                f"\nvecteurs en base : {bilan['candidates']}"
                f"\npaires écrites   : {bilan['ecrites']}"
                f"\ndossier périmé   : {bilan['perimees']}  (réencoder pour les récupérer)"
                f"\nnon collectées   : {bilan['introuvables']}"
            )
            if bilan["ecrites"] < 2000:
                typer.echo(
                    "\n⚠ moins de 2 000 paires : c'est peu pour distiller."
                    " Élargir le corpus d'abord (training corpus --limit 20000)."
                )

    _run(run())


@training_app.command("validite")
def training_validite(
    bareme: Annotated[
        str | None, typer.Option("--bareme", help="Version du barème. Défaut : la plus récente.")
    ] = None,
) -> None:
    """Les notes mesurent-elles quelque chose ? — la validité, pas la fidélité.

    Tout le reste du projet mesure la **fidélité** : le juge d'accord avec
    lui-même (0,37), la régression d'accord avec le juge (0,84). Ça établit
    qu'on rend toujours la même valeur, pas qu'elle soit la bonne — un
    thermomètre déréglé de trois degrés est parfaitement fidèle.

    Trois angles, gratuits, imparfaits séparément et convergents ensemble :
    les ancres du barème (le système reproduit-il ses propres définitions ?),
    les genres TMDB (critère extérieur, produit par d'autres), et le
    contre-juge Haiku (autre famille de modèle sur le même dossier).

    Aucun ne prouve la validité. Un désaccord franc sur l'un des trois la
    réfute — et c'est ce qu'on cherche : savoir si « action 5,5 » est une
    mesure ou une décoration.
    """
    from fiv_admin.routes.training import PasAssezDOeuvres, _rubric, mesurer_validite

    settings = get_settings()

    async def run() -> None:
        async with connect(settings.database_url, settings.sourcing_schema, "admin") as conn:
            if bareme:
                rubric = await _rubric(conn, bareme)
            else:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "select version, prompt, axes from notation.rubric"
                        " order by created_at desc limit 1"
                    )
                    rubric = await cur.fetchone()
                if rubric is None:
                    typer.echo("aucun barème en base.")
                    raise typer.Exit(1)

            typer.echo(f"barème {rubric['version']} — lecture des notes…")
            try:
                bilan = await mesurer_validite(conn, rubric)
            except PasAssezDOeuvres as exc:
                typer.echo(f"ERREUR : {exc}")
                raise typer.Exit(1) from exc

            typer.echo(f"\n{bilan['oeuvres']} œuvre(s) notée(s).\n")

            typer.echo("1. LES ANCRES — le barème reproduit-il ses propres définitions ?\n")
            typer.echo(f"  {'axe':<11}{'ancres':>8}{'écart':>8}   le plus loin")
            for a in bilan["ancres"]:
                ecart = f"{a['ecartMoyen']:.2f}" if a["ecartMoyen"] is not None else "—"
                trouvees = f"{a['trouvees']}/{a['declarees']}"
                pire = (
                    f"{a['pire']['titre']} : {a['pire']['declare']:.0f} déclaré,"
                    f" {a['pire']['rendu']:.1f} rendu"
                    if a["pire"]
                    else "—"
                )
                typer.echo(f"  {a['axe']:<11}{trouvees:>8}{ecart:>8}   {pire}")
            typer.echo(
                "\n  Au-delà de 1,5 d'écart, la définition n'est pas suivie :"
                "\n  le juge note autre chose que ce que le barème décrit."
            )

            typer.echo("\n2. LES GENRES TMDB — critère extérieur, produit par d'autres\n")
            typer.echo(f"  {'axe':<11}{'œuvres':>8}{'avec':>7}{'sans':>7}{'écart':>8}   genres")
            for g in bilan["genres"]:
                avec = f"{g['moyenneAvec']:.2f}" if g["moyenneAvec"] is not None else "—"
                sans = f"{g['moyenneSans']:.2f}" if g["moyenneSans"] is not None else "—"
                ecart = f"{g['ecart']:+.2f}" if g["ecart"] is not None else "—"
                typer.echo(
                    f"  {g['axe']:<11}{g['avec']:>8}{avec:>7}{sans:>7}{ecart:>8}"
                    f"   {', '.join(g['genres'])[:38]}"
                )
            typer.echo(
                "\n  Un écart proche de zéro dirait que l'axe ne mesure rien que"
                "\n  quelqu'un d'autre reconnaîtrait. Un écart énorme dirait qu'il"
                "\n  recopie le genre, ce que le barème interdit explicitement."
            )

            typer.echo(
                f"\n3. LE CONTRE-JUGE — Haiku, autre famille, même dossier"
                f"  ({bilan['contreJugeOeuvres']} œuvre(s))\n"
            )
            if not bilan["contreJugeOeuvres"]:
                typer.echo(
                    "  Aucune contre-note en base. C'est le point aveugle le plus"
                    "\n  coûteux : sans second juge, rien ne distingue une mesure"
                    "\n  d'une lubie propre à une lignée de modèles."
                )
            else:
                for j in bilan["contreJuge"]:
                    ecart = f"{j['ecartMoyen']:.2f}" if j["ecartMoyen"] is not None else "—"
                    typer.echo(f"  {j['axe']:<11}{j['oeuvres']:>6} œuvres   écart moyen {ecart}")
                typer.echo(
                    "\n  À comparer au bruit propre du juge (0,37) : un écart du même"
                    "\n  ordre dit que les deux familles voient la même chose."
                )

    _run(run())


@training_app.command("diagnostic")
def training_diagnostic(
    bareme: Annotated[
        str | None, typer.Option("--bareme", help="Version du barème. Défaut : la plus récente.")
    ] = None,
    focus: Annotated[
        int | None,
        typer.Option("--focus", help="Id TMDB dont afficher le voisinage. Ex. 63174 (Lucifer)."),
    ] = None,
) -> None:
    """Ce que l'encodeur ne lit pas du dossier, et si ça se voit sur l'erreur.

    Le juge et l'encodeur ne reçoivent pas le même texte : GPT lit le dossier
    entier, l'encodeur les 12 000 premiers caractères. Pour toute fiche qui
    dépasse, la note à prédire dépend d'un texte que le vecteur n'a jamais vu.
    Six hypothèses sont tombées sur le plafond — volume, encodeur, calibration,
    voisinage, famille de modèle, absence de Wikipédia — celle-ci n'a jamais
    été mesurée.

    La corrélation longueur × erreur tranche : plate, la troncature est hors de
    cause ; croissante, relever la borne devient le levier.

    `--focus` ajoute le voisinage cosine d'une œuvre. C'est la question qui
    passe avant le choix d'un modèle : aucune régression ne retrouve ce que la
    représentation ne contient pas, et si Lucifer a pour voisins des policiers
    surnaturels plutôt que des comédies, sa joie est perdue dès l'encodage.

    N'écrit rien et n'appelle aucune API payante.
    """
    from fiv_admin.routes.training import PasAssezDOeuvres, _rubric, diagnostic_matiere

    settings = get_settings()

    async def run() -> None:
        async with connect(settings.database_url, settings.sourcing_schema, "admin") as conn:
            if bareme:
                rubric = await _rubric(conn, bareme)
            else:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "select version, prompt, axes from notation.rubric"
                        " order by created_at desc limit 1"
                    )
                    rubric = await cur.fetchone()
                if rubric is None:
                    typer.echo("aucun barème en base.")
                    raise typer.Exit(1)

            typer.echo(f"barème {rubric['version']} — assemblage des dossiers…")
            try:
                bilan = await diagnostic_matiere(conn, settings, rubric, focus=focus)
            except PasAssezDOeuvres as exc:
                typer.echo(f"ERREUR : {exc}")
                raise typer.Exit(1) from exc

            total = bilan["oeuvres"]
            typer.echo(f"\n{total} dossier(s). L'encodeur coupe à {bilan['coupe']:,} caractères.\n")
            typer.echo(f"  {'longueur du dossier':<22}{'œuvres':>8}{'part':>8}")
            for t in bilan["tranches"]:
                part = t["oeuvres"] / total if total else 0.0
                typer.echo(f"  {t['libelle']:<22}{t['oeuvres']:>8}{part:>8.0%}")
            tronques = bilan["tronques"]
            typer.echo(
                f"\n  tronqués        : {tronques}/{total} ({tronques / total if total else 0:.0%})"
            )
            typer.echo(f"  texte jugé perdu: {bilan['partPerdue']:.0%} du total assemblé")

            w = bilan["wikipedia"]
            typer.echo(
                f"\n  Wikipédia présente : {w['presente']}/{total}"
                f"  —  entière {w['entiere']}, coupée {w['coupee']}, jamais atteinte {w['absente']}"
            )

            if bilan["quartiles"]:
                typer.echo("\n  MAE cv par quartile de longueur")
                for q in bilan["quartiles"]:
                    borne = f"{q['charsMin']:,} – {q['charsMax']:,}"
                    typer.echo(f"    Q{q['rang']}  {borne:<20}{q['mae']:>7.3f}  ({q['oeuvres']})")
            if bilan["correlation"] is not None:
                typer.echo(f"\n  corrélation longueur × erreur : {bilan['correlation']:+.2f}")
            typer.echo(
                "\n  Une erreur qui monte avec la longueur accuse la troncature."
                "\n  Une erreur plate l'innocente, et renvoie chercher ailleurs."
            )

            v = bilan["voisinage"]
            if focus is not None and v is None:
                typer.echo(f"\n  {focus} n'est pas dans le corpus noté — pas de voisinage.")
            elif v is not None:
                axe = v["axePireEcart"]
                typer.echo(f"\n  voisins de {v['titre']} ({v['idTmdb']}) — cosine sur le dossier")
                if axe:
                    typer.echo(
                        f"  axe le plus faux : {axe} —"
                        f" juge {v['juge'][axe]:.1f}, modèle {v['modele'][axe]:.1f}\n"
                    )
                typer.echo(f"    {'cos':>6}{'  ' + (axe or 'juge'):<12}œuvre")
                for n in v["voisins"]:
                    note = f"{n['juge']:.1f}" if n["juge"] is not None else "—"
                    typer.echo(f"    {n['cosinus']:>6.3f}  {note:<10}{n['titre']}")
                typer.echo(
                    "\n  Des voisins qui portent la même note que le juge disent que"
                    "\n  l'information est là, et que c'est le modèle qui la rate."
                    "\n  Des voisins tous à côté disent que l'encodage l'a déjà perdue."
                )

    _run(run())


@catalog_app.command("refresh")
def catalog_refresh() -> None:
    """Recalcule les vignettes depuis le brut.

    À lancer après une passe de collecte : la grille de cartes lit cette
    projection, pas le brut, et reste donc en retard jusque-là. Le détail d'une
    série, lui, relit toujours le brut.
    """
    from fiv_admin.catalog import refresh_cards

    settings = get_settings()

    async def run() -> int:
        async with connect(settings.database_url, settings.sourcing_schema) as conn:
            return await refresh_cards(conn)

    typer.echo(f"{_run(run()):,} vignette(s) dans la projection".replace(",", " "))


@search_app.command("reindex")
def search_reindex(
    univers: Annotated[
        str,
        typer.Option("--univers", help="series, movies, ou all (défaut)."),
    ] = "all",
    lot: Annotated[
        int, typer.Option("--lot", min=50, max=5000, help="Documents par envoi bulk.")
    ] = 500,
) -> None:
    """Reconstruit les index de recherche et bascule les alias, sans coupure.

    À lancer après une passe de collecte ou un `catalog refresh` : l'index se
    reconstruit en entier — il n'est jamais mis à jour au fil de l'eau, c'est
    le même régime que la projection de vignettes, et c'est ce qui garde la
    réindexation triviale à raisonner : un état, pas un delta.

    Le gros du temps part dans la relecture des payloads : les titres traduits
    ne vivent que dans le brut, et c'est précisément eux qui font que « Le
    Trône de fer » se met à répondre.
    """
    import time

    import httpx

    from fiv_admin.media import MEDIA
    from fiv_admin.search import etat, reindexer

    settings = get_settings()
    if not settings.es_url:
        typer.echo("ERREUR : ES_URL est vide — la recherche est désactivée.")
        raise typer.Exit(1)

    cibles = [m for m in MEDIA.values() if m.catalog_table is not None]
    if univers != "all":
        cibles = [m for m in cibles if m.univers == univers]
        if not cibles:
            typer.echo(f"ERREUR : univers inconnu ou sans catalogue : {univers}")
            raise typer.Exit(1)

    async def run() -> None:
        # Un client à part, sans le timeout court des routes : le
        # `force_merge` final d'1,5 M de documents se compte en minutes.
        async with httpx.AsyncClient(
            base_url=settings.es_url, timeout=httpx.Timeout(600.0, connect=5.0)
        ) as http:
            try:
                await http.get("/")
            except httpx.HTTPError as exc:
                typer.echo(f"ERREUR : Elasticsearch injoignable sur {settings.es_url} : {exc}")
                typer.echo("→ sur le poste : make es-start (après make bootstrap-es)")
                raise typer.Exit(1) from exc

            async with connect(settings.database_url, settings.sourcing_schema, "admin") as conn:
                for media in cibles:
                    typer.echo(f"{media.univers} : extraction et indexation…")
                    debut = time.monotonic()
                    stats = await reindexer(
                        conn,
                        http,
                        media,
                        lot=lot,
                        avancement=lambda n: print(f"\r  {n:,}".replace(",", " "), end=""),
                    )
                    print()
                    compte = f"{stats['documents']:,}".replace(",", " ")
                    duree = time.monotonic() - debut
                    typer.echo(
                        f"  {compte} documents → {stats['index']}"
                        f" (alias {stats['alias']}, {duree:.0f} s)"
                    )
                    if stats["remplaces"]:
                        typer.echo(f"  remplacé : {', '.join(stats['remplaces'])}")

            bilan = await etat(http)
            typer.echo(f"santé : {bilan['sante']}")
            for nom, infos in sorted(bilan["indices"].items()):
                typer.echo(
                    f"  {nom:<32} {infos['documents']:>9,} docs  {infos['taille']}".replace(
                        ",", " "
                    )
                )

    _run(run())


@search_app.command("status")
def search_status() -> None:
    """La santé du service et les index de recherche en place."""
    import httpx

    from fiv_admin.search import etat

    settings = get_settings()
    if not settings.es_url:
        typer.echo("recherche désactivée (ES_URL vide) — les routes servent l'ILIKE.")
        raise typer.Exit()

    async def run() -> None:
        async with httpx.AsyncClient(base_url=settings.es_url, timeout=5.0) as http:
            try:
                bilan = await etat(http)
            except httpx.HTTPError as exc:
                typer.echo(f"Elasticsearch injoignable sur {settings.es_url} : {exc}")
                typer.echo("Les routes servent l'ILIKE en attendant — rien n'est cassé.")
                raise typer.Exit(1) from exc
            typer.echo(f"santé : {bilan['sante']}  ({settings.es_url})")
            if not bilan["indices"]:
                typer.echo("aucun index — lancer `fiv-admin search reindex`")
            for nom, infos in sorted(bilan["indices"].items()):
                typer.echo(
                    f"  {nom:<32} {infos['documents']:>9,} docs  {infos['taille']}".replace(
                        ",", " "
                    )
                )

    _run(run())


@app.callback()
def _root(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )
    # Posé sur le gestionnaire, pas sur un logger particulier : une fuite vient
    # presque toujours d'une bibliothèque tierce, et on ne veut pas dépendre de
    # la liste de celles qui journalisent des URL.
    for handler in logging.getLogger().handlers:
        handler.addFilter(SecretFilter())


@app.command()
def serve(
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
    reload: Annotated[bool, typer.Option("--reload", help="Rechargement à chaud (dev).")] = False,
) -> None:
    """Lance l'API (et le front, s'il est construit)."""
    import uvicorn

    settings = get_settings()
    if not settings.admin_secret_key:
        typer.echo("⚠ ADMIN_SECRET_KEY absente : les sessions ne survivront pas au redémarrage.")
        typer.echo(f"  suggestion : ADMIN_SECRET_KEY={secrets.token_hex(32)}")

    typer.echo(f"base  : {redact_dsn(settings.database_url)}")
    typer.echo(f"front : {settings.web_dist if settings.has_front else 'non construit'}")

    uvicorn.run(
        "fiv_admin.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


@app.command()
def doctor() -> None:
    """Vérifie l'environnement : interpréteur, base, migrations, comptes, front."""
    import sys
    from pathlib import Path

    settings = get_settings()
    ok = True

    if VENDOR_DIR.exists():
        base = Path(sys.base_prefix).resolve()
        vendored = (
            VENDOR_DIR in Path(sys.executable).resolve().parents or VENDOR_DIR in base.parents
        )
        ok &= _line("interpréteur", vendored, f"{sys.version.split()[0]} — {base}")
        if not vendored:
            typer.echo("        → Python hors vendor/. Relancer `make bootstrap`.")
    else:
        _line("interpréteur", True, f"{sys.version.split()[0]} — image, pas de vendor/")

    ok &= _line(
        "secret de session",
        bool(settings.admin_secret_key),
        "configuré" if settings.admin_secret_key else "absent — sessions éphémères",
    )

    try:
        state = _run(_status())
    except Exception as exc:  # noqa: BLE001 — on veut le message brut
        ok &= _line("base", False, f"{type(exc).__name__}: {exc}")
        typer.echo(
            "        → la base est celle de sourcing : `make -C ../sourcing db-create migrate`."
        )
    else:
        ok &= _line("base", True, redact_dsn(settings.database_url))
        ok &= _line(
            "schéma sourcing",
            state["sourcing"],
            "présent" if state["sourcing"] else "absent — migrer sourcing d'abord",
        )
        ok &= _line(
            "schéma admin",
            state["admin"],
            "présent" if state["admin"] else "absent — `fiv-admin db migrate`",
        )
        if state["admin"]:
            ok &= _line(
                "comptes",
                state["users"] > 0,
                f"{state['users']}" if state["users"] else "aucun — `fiv-admin user add`",
            )
        ok &= _line(
            "catalogue", state["catalog"] > 0, f"{state['catalog']:,} séries".replace(",", " ")
        )

    _line(
        "front construit",
        settings.has_front,
        str(settings.web_dist)
        if settings.has_front
        else f"pas d'index.html dans {settings.web_dist} — `make web-build`",
    )

    raise typer.Exit(0 if ok else 1)


@db_app.command("migrate")
def db_migrate() -> None:
    """Applique les migrations du schéma `admin`."""
    settings = get_settings()
    typer.echo(f"cible      : {redact_dsn(settings.database_url)}")
    typer.echo(f"migrations : {settings.migrations_dir}")

    async def run() -> list[str]:
        async with connect(settings.database_url) as conn:
            return await migrate(conn, settings.migrations_dir)

    try:
        applied = _run(run())
    except MigrationsNotFound as exc:
        typer.echo(f"ERREUR : {exc}")
        raise typer.Exit(1) from exc
    except psycopg.errors.RaiseException as exc:
        typer.echo(f"ERREUR : {exc.diag.message_primary or exc}")
        raise typer.Exit(1) from exc

    detail = f" : {', '.join(applied)}" if applied else " (base déjà à jour)"
    typer.echo(f"{len(applied)} migration(s) appliquée(s){detail}")


@user_app.command("add")
def user_add(
    username: Annotated[str, typer.Argument(help="Identifiant de connexion.")],
    display_name: Annotated[str | None, typer.Option("--name", help="Nom affiché.")] = None,
) -> None:
    """Crée un compte. Le mot de passe est demandé, jamais passé en argument —
    une ligne de commande finit dans l'historique du shell."""
    # Vérifié avant l'invite, pas après : se faire saisir un mot de passe deux
    # fois pour apprendre ensuite que la table n'existe pas est le genre de
    # détail qui use.
    _require_admin_schema()

    password = typer.prompt("Mot de passe", hide_input=True, confirmation_prompt=True)
    if len(password) < 12:
        typer.echo("Mot de passe trop court : 12 caractères au minimum.")
        raise typer.Exit(2)

    settings = get_settings()

    async def run() -> bool:
        async with (
            connect(settings.database_url, settings.admin_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                insert into admin_user (username, password_hash, display_name)
                values (%s, %s, %s)
                on conflict (username) do nothing
                returning username
                """,
                (username, hash_password(password), display_name),
            )
            return await cur.fetchone() is not None

    if not _run(run()):
        typer.echo(f"Le compte {username} existe déjà — `fiv-admin user passwd {username}`.")
        raise typer.Exit(1)
    typer.echo(f"Compte {username} créé.")


@user_app.command("passwd")
def user_passwd(username: str) -> None:
    """Change le mot de passe d'un compte."""
    # Avant l'invite, pour la même raison que dans `user_add` : saisir un mot de
    # passe deux fois pour apprendre ensuite que la table n'existe pas est
    # exactement ce qu'on ne veut pas faire vivre à quelqu'un qui déploie.
    _require_admin_schema()

    password = typer.prompt("Nouveau mot de passe", hide_input=True, confirmation_prompt=True)
    if len(password) < 12:
        typer.echo("Mot de passe trop court : 12 caractères au minimum.")
        raise typer.Exit(2)

    settings = get_settings()

    async def run() -> bool:
        async with (
            connect(settings.database_url, settings.admin_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                update admin_user set password_hash = %s
                where username = %s
                returning username
                """,
                (hash_password(password), username),
            )
            return await cur.fetchone() is not None

    if not _run(run()):
        typer.echo(f"Compte inconnu : {username}")
        raise typer.Exit(1)
    typer.echo(f"Mot de passe de {username} changé.")


@user_app.command("disable")
def user_disable(
    username: str,
    enable: Annotated[
        bool, typer.Option("--enable", help="Réactiver au lieu de désactiver.")
    ] = False,
) -> None:
    """Désactive (ou réactive) un compte. Effet immédiat : les sessions en
    cours sont refusées à la requête suivante."""
    settings = get_settings()

    async def run() -> bool:
        async with (
            connect(settings.database_url, settings.admin_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "update admin_user set disabled = %s where username = %s returning username",
                (not enable, username),
            )
            return await cur.fetchone() is not None

    if not _run(run()):
        typer.echo(f"Compte inconnu : {username}")
        raise typer.Exit(1)
    typer.echo(f"Compte {username} {'réactivé' if enable else 'désactivé'}.")


@user_app.command("list")
def user_list() -> None:
    """Liste les comptes."""
    settings = get_settings()

    async def run() -> list[tuple[Any, ...]]:
        async with (
            connect(settings.database_url, settings.admin_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "select username, display_name, disabled, created_at, last_login_at"
                " from admin_user order by username"
            )
            return list(await cur.fetchall())

    rows = _run(run())
    if not rows:
        typer.echo("Aucun compte. `fiv-admin user add <identifiant>`")
        return
    for username, name, disabled, created, last in rows:
        state = "désactivé" if disabled else "actif"
        seen = last.strftime("%Y-%m-%d %H:%M") if last else "jamais connecté"
        typer.echo(f"{username:<20} {state:<10} {name or '':<24} créé {created:%Y-%m-%d}  {seen}")


async def _status() -> dict[str, Any]:
    settings = get_settings()
    async with connect(settings.database_url) as conn, conn.cursor() as cur:
        await cur.execute(
            "select schema_name from information_schema.schemata"
            " where schema_name = any(%s::text[])",
            ([settings.sourcing_schema, settings.admin_schema],),
        )
        present = {row[0] for row in await cur.fetchall()}

        users = 0
        if settings.admin_schema in present:
            await cur.execute(
                f'select count(*) from "{settings.admin_schema}".admin_user'  # noqa: S608
            )
            users = (await cur.fetchone() or (0,))[0]

        catalog = 0
        if settings.sourcing_schema in present:
            await cur.execute(
                f'select count(*) from "{settings.sourcing_schema}".tmdb_catalog'  # noqa: S608
            )
            catalog = (await cur.fetchone() or (0,))[0]

    return {
        "sourcing": settings.sourcing_schema in present,
        "admin": settings.admin_schema in present,
        "users": users,
        "catalog": catalog,
    }


def _require_admin_schema() -> None:
    """Échoue avec une consigne si `admin.admin_user` n'existe pas.

    C'est l'état d'une base migrée pour `sourcing` mais pas encore pour
    l'administration — le cas normal au premier déploiement. Sans ce contrôle,
    la première commande de compte se termine par une trace `UndefinedTable`,
    qui dit *quelle table* manque mais pas *quoi faire*.
    """
    settings = get_settings()

    async def run() -> str | None:
        async with connect(settings.database_url) as conn, conn.cursor() as cur:
            await cur.execute("select to_regclass(%s)", (f"{settings.admin_schema}.admin_user",))
            row = await cur.fetchone()
        return row[0] if row else None

    if _run(run()) is None:
        # Le cas qui trompe : ce n'est pas la migration qui manque, c'est
        # l'endroit où on la cherche. Les migrations posent `admin` en dur ; un
        # `ADMIN_SCHEMA` différent fait donc chercher les comptes dans un schéma
        # que rien ne créera jamais, et le conseil « appliquer les migrations »
        # envoie tourner en rond.
        if settings.admin_schema != "admin":
            typer.echo(f"Le schéma configuré est « {settings.admin_schema} ».")
            typer.echo("Or les migrations créent « admin », et ce nom n'est pas un réglage.")
            typer.echo("→ retirer ADMIN_SCHEMA de l'environnement (ou le remettre à « admin ») :")
            typer.echo("     sed -i 's/^ADMIN_SCHEMA=.*/ADMIN_SCHEMA=admin/' .env")
            typer.echo("     docker compose up -d admin")
            raise typer.Exit(1)

        typer.echo(f"Le schéma « {settings.admin_schema} » n'existe pas encore.")
        typer.echo("→ appliquer les migrations d'abord :")
        typer.echo("     fiv-admin db migrate")
        typer.echo("   en conteneur :")
        typer.echo("     docker compose run --rm admin db migrate")
        typer.echo("")
        typer.echo("   Si cette commande échoue sur « schéma sourcing absent », c'est que")
        typer.echo("   la collecte n'a pas encore migré cette base :")
        typer.echo("     docker compose run --rm sourcing db migrate")
        raise typer.Exit(1)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(coro)
    except psycopg.OperationalError as exc:
        typer.echo(f"ERREUR de connexion : {exc}")
        typer.echo("→ vérifier DATABASE_URL dans admin/.env")
        raise typer.Exit(1) from exc
    except psycopg.errors.UndefinedTable as exc:
        # Le filet pour les autres commandes de compte, qui n'ont pas d'invite
        # à protéger et vont donc droit à la requête.
        typer.echo(f"ERREUR : {exc}")
        typer.echo("→ le schéma de l'administration n'est pas créé :")
        typer.echo("     fiv-admin db migrate")
        raise typer.Exit(1) from exc


def _line(label: str, ok: bool, detail: str = "") -> bool:
    typer.echo(f"  {'✓' if ok else '✗'}  {label:<20} {detail}")
    return ok
