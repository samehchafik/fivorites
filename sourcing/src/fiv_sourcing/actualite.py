"""L'actualité dérivée du pipeline lui-même : les diffs de fiches TMDB.

La propriété qui rend tout ceci gratuit : `raw_source` ne grandit que quand le
contenu change — `store_raw` déduplique par empreinte, une recollecte
identique n'écrit rien. Toute nouvelle ligne de fiche EST donc un changement
réel, et « qu'est-ce qui est arrivé à cette œuvre ? » se répond en comparant
sa dernière fiche à la précédente. Aucun réseau, aucun appel payant.

La reprise est un entier : `actualite_curseur` retient le dernier
`raw_source.id` traité par kind. Le remettre à zéro rejoue tout, et le rejeu
est idempotent — les clés `(raw_source_id, type_evenement)` font qu'un
événement déjà dérivé ne se réécrit pas.

Ce qu'un diff SAIT dire et ce qu'il ne sait pas : il voit qu'une saison est
apparue, qu'une date de diffusion a changé, qu'un statut a basculé. Il ne voit
pas pourquoi, et il ne voit rien de ce que TMDB ne structure pas — c'est le
rôle du flux RSS, l'autre moitié de doc/architecture-actualite.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fiv_sourcing import store

log = logging.getLogger(__name__)

# Les kinds qui portent une fiche d'œuvre — pas les saisons, pas les lookups.
KINDS_FICHES = ("tv", "movie")

# Combien de nouvelles lignes de brut se traitent par transaction de curseur.
# Le premier passage remonte tout l'historique ; par lots, une interruption ne
# coûte que le lot en cours.
LOT = 500


@dataclass(slots=True)
class DeriveReport:
    examines: int = 0  # lignes de brut vues (curseur avancé dessus)
    sans_precedent: int = 0  # premières collectes : rien à comparer
    evenements: int = 0  # lignes écrites dans actualite
    par_type: dict[str, int] = field(default_factory=dict)


def _date_sure(brut: Any) -> date | None:
    """Une date TMDB (`YYYY-MM-DD`) ou rien — jamais une exception.

    Les payloads portent des chaînes vides et des dates partielles ; un diff
    qui planterait sur une fiche mal remplie s'arrêterait au milieu du
    catalogue.
    """
    if not brut or not isinstance(brut, str):
        return None
    try:
        return datetime.strptime(brut[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _saisons(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Les saisons par numéro, sans la saison 0 (les hors-série ne sont pas
    une annonce — TMDB y range bêtisiers et épisodes spéciaux)."""
    return {
        s["season_number"]: s
        for s in payload.get("seasons") or []
        if isinstance(s, dict)
        and isinstance(s.get("season_number"), int)
        and s["season_number"] > 0
    }


def diff_evenements(
    kind: str, avant: dict[str, Any], apres: dict[str, Any], jour: date
) -> list[tuple[str, date, str]]:
    """Les événements entre deux versions d'une fiche : (type, date, titre).

    Fonction pure, exprès : c'est elle que les tests attaquent, sans base. Le
    `jour` est la date de collecte de la nouvelle version — le repli quand
    l'événement n'apporte pas sa propre date.

    Un seul événement par type et par diff : deux saisons annoncées d'un coup
    font UNE annonce qui les nomme toutes — c'est ce que la clé
    `(raw_source_id, type_evenement)` impose, et c'est aussi ce qu'un lecteur
    attend (« Saisons 3 et 4 annoncées », pas deux lignes).
    """
    evenements: list[tuple[str, date, str]] = []

    if kind == "tv":
        nouvelles = sorted(set(_saisons(apres)) - set(_saisons(avant)))
        if nouvelles:
            saisons_apres = _saisons(apres)
            quand = min(
                (d for n in nouvelles if (d := _date_sure(saisons_apres[n].get("air_date")))),
                default=jour,
            )
            noms = (
                f"Saison {nouvelles[0]} annoncée"
                if len(nouvelles) == 1
                else "Saisons " + " et ".join(str(n) for n in nouvelles) + " annoncées"
            )
            evenements.append(("saison_annoncee", quand, noms))

        avant_ep = (avant.get("next_episode_to_air") or {}).get("air_date")
        apres_ep = (apres.get("next_episode_to_air") or {}).get("air_date")
        quand_ep = _date_sure(apres_ep)
        if quand_ep is not None and apres_ep != avant_ep:
            evenements.append(
                ("date_diffusion", quand_ep, f"Prochain épisode le {quand_ep:%d/%m/%Y}")
            )

        statut_avant, statut_apres = avant.get("status"), apres.get("status")
        if statut_apres != statut_avant:
            quand_fin = _date_sure(apres.get("last_air_date")) or jour
            if statut_apres == "Ended":
                evenements.append(("diffusion_terminee", quand_fin, "Diffusion terminée"))
            elif statut_apres == "Canceled":
                evenements.append(("annulation", quand_fin, "Série annulée"))

    elif kind == "movie":
        avant_sortie = _date_sure(avant.get("release_date"))
        apres_sortie = _date_sure(apres.get("release_date"))
        statut_avant, statut_apres = avant.get("status"), apres.get("status")
        if apres_sortie is not None and apres_sortie != avant_sortie:
            libelle = (
                f"Sortie le {apres_sortie:%d/%m/%Y}"
                if apres_sortie >= jour
                else f"Sorti le {apres_sortie:%d/%m/%Y}"
            )
            evenements.append(("sortie", apres_sortie, libelle))
        elif statut_apres == "Released" and statut_avant != "Released":
            evenements.append(("sortie", apres_sortie or jour, "Film sorti"))

    return evenements


async def deriver_diffs(
    conn: psycopg.AsyncConnection,
    *,
    limit: int | None = None,
) -> DeriveReport:
    """Avance le curseur et écrit les événements des fiches recollectées.

    Le parcours suit `raw_source.id` croissant — l'ordre d'arrivée — et le
    prédécesseur se cherche par `(kind, source_id, lang)` : la fiche est
    collectée en une langue, et comparer un `fr-FR` à un `en-US` fabriquerait
    des différences qui n'existent pas.
    """
    report = DeriveReport()

    for kind in KINDS_FICHES:
        univers_cle = "series" if kind == "tv" else "movies"
        async with conn.cursor() as cur:
            await cur.execute(
                """
                insert into actualite_curseur (kind) values (%s)
                on conflict do nothing
                """,
                (kind,),
            )
            await cur.execute(
                "select dernier_raw_id from actualite_curseur where kind = %s", (kind,)
            )
            curseur = (await cur.fetchone())[0]

        while limit is None or report.examines < limit:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    select id, source_id, lang, payload, fetched_at
                    from raw_source
                    where source = 'tmdb' and kind = %s and id > %s
                      and http_status between 200 and 299 and payload is not null
                    order by id
                    limit %s
                    """,
                    (kind, curseur, LOT),
                )
                lignes = await cur.fetchall()
            if not lignes:
                break

            a_ecrire: list[tuple[Any, ...]] = []
            ids_tmdb: set[int] = set()
            par_ligne: list[tuple[int, int, list[tuple[str, date, str]]]] = []

            for raw_id, source_id, lang, payload, fetched_at in lignes:
                report.examines += 1
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        select payload from raw_source
                        where source = 'tmdb' and kind = %s and source_id = %s
                          and coalesce(lang, '') = coalesce(%s, '')
                          and id < %s
                          and http_status between 200 and 299 and payload is not null
                        order by fetched_at desc, id desc
                        limit 1
                        """,
                        (kind, source_id, lang, raw_id),
                    )
                    precedent = await cur.fetchone()
                if precedent is None:
                    # Première collecte : une fiche qui apparaît n'est pas une
                    # nouvelle, c'est un rattrapage de catalogue.
                    report.sans_precedent += 1
                    continue

                evenements = diff_evenements(kind, precedent[0], payload, fetched_at.date())
                if evenements:
                    ids_tmdb.add(int(source_id))
                    par_ligne.append((raw_id, int(source_id), evenements))

            if par_ligne:
                # Le pivot en un geste pour tout le lot. `ensure` et non un
                # simple select : depuis le lot 12, une œuvre existe dès que sa
                # fiche a été téléchargée — et ces fiches viennent de l'être.
                pivots = await store.ensure_oeuvres(conn, sorted(ids_tmdb), univers=univers_cle)
                for raw_id, id_tmdb, evenements in par_ligne:
                    for type_evt, quand, titre in evenements:
                        a_ecrire.append(
                            (
                                pivots.get(id_tmdb),
                                type_evt,
                                quand,
                                titre,
                                "tmdb",
                                raw_id,
                            )
                        )

            if a_ecrire:
                # Écrites une à une avec `returning` : le rapport doit compter
                # les lignes réellement INSÉRÉES, pas les proposées — au rejeu,
                # `on conflict do nothing` écarte tout, et un rapport qui
                # annoncerait des événements « écrits » à chaque passage rendrait
                # l'idempotence invérifiable de l'extérieur. Les événements sont
                # rares ; l'unité ne coûte rien.
                async with conn.cursor() as cur:
                    for ligne in a_ecrire:
                        await cur.execute(
                            """
                            insert into actualite
                                (oeuvre_id, type_evenement, survenu_le, titre,
                                 editeur, raw_source_id)
                            values (%s, %s, %s, %s, %s, %s)
                            on conflict (raw_source_id, type_evenement)
                                where raw_source_id is not null
                            do nothing
                            returning id
                            """,
                            ligne,
                        )
                        if await cur.fetchone() is not None:
                            report.evenements += 1
                            report.par_type[ligne[1]] = report.par_type.get(ligne[1], 0) + 1

            curseur = lignes[-1][0]
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    update actualite_curseur
                    set dernier_raw_id = %s, avance_at = now()
                    where kind = %s
                    """,
                    (curseur, kind),
                )

    return report


# ------------------------------------------------------------------ flux RSS


@dataclass(slots=True)
class SweepReport:
    flux: int = 0  # flux actifs visités
    inchanges: int = 0  # 304 — le passage normal, et le moins cher
    items_vus: int = 0
    items_nouveaux: int = 0  # lignes réellement écrites (dédup par empreinte)
    erreurs: int = 0


async def balayer_flux(conn: psycopg.AsyncConnection, fetcher: Any) -> SweepReport:
    """Un passage sur tous les flux actifs — le cœur de `rss-sweep`.

    Trois règles, chacune tirée du contrat d'un agrégateur correct :

    * **le GET est conditionnel** : les validateurs du dernier passage partent
      avec la requête, et un 304 clôt le flux pour quelques octets. En rythme
      de croisière, c'est la réponse dominante — un flux de presse change
      quelques fois par jour, on passe toutes les heures ;
    * **un flux en erreur ne bloque pas les autres** : l'erreur se note sur SA
      ligne (`last_error`), la passe continue. Un éditeur qui tombe un samedi
      ne doit pas éteindre la collecte du week-end entier ;
    * **un item ré-émis à l'identique n'écrit rien** : l'empreinte du payload
      normalisé fait partie de la clé, comme dans `raw_source`. Les flux
      ré-émettent leurs vingt derniers items à chaque réponse — sans la dédup,
      chaque 200 multiplierait le brut par vingt.
    """
    from fiv_sourcing.sources import rss

    report = SweepReport()
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, url, etag, last_modified from rss_feed where actif order by id"
        )
        flux = await cur.fetchall()

    for feed_id, url, etag, last_modified in flux:
        report.flux += 1
        try:
            statut, corps, nouvel_etag, nouveau_lm = await fetcher.get_conditional_text(
                url, etag=etag, last_modified=last_modified
            )
        except Exception as exc:  # noqa: BLE001 — un flux ne tue pas la passe
            statut, corps, nouvel_etag, nouveau_lm = 0, "", None, None
            log.warning("flux %s : %s", url, exc)

        if statut == 304:
            report.inchanges += 1
            async with conn.cursor() as cur:
                await cur.execute(
                    "update rss_feed set last_status = 304, last_success_at = now(),"
                    " last_error = null where id = %s",
                    (feed_id,),
                )
            continue

        if statut < 200 or statut >= 300 or not corps:
            report.erreurs += 1
            async with conn.cursor() as cur:
                await cur.execute(
                    "update rss_feed set last_status = %s, last_error = %s where id = %s",
                    (statut, f"HTTP {statut}" if statut else "injoignable", feed_id),
                )
            continue

        items = rss.parser_flux(corps)
        report.items_vus += len(items)
        async with conn.cursor() as cur:
            for payload in items:
                await cur.execute(
                    """
                    insert into raw_rss_item (feed_id, guid, digest, payload)
                    values (%s, %s, %s, %s)
                    on conflict (feed_id, guid, digest) do nothing
                    returning id
                    """,
                    (
                        feed_id,
                        payload["guid"],
                        store.payload_digest(payload),
                        Jsonb(payload),
                    ),
                )
                if await cur.fetchone() is not None:
                    report.items_nouveaux += 1
            # Les validateurs se rangent tels quels — ils sont opaques, c'est
            # le serveur de l'éditeur qui les relira au prochain passage.
            await cur.execute(
                """
                update rss_feed
                set etag = %s, last_modified = %s, last_status = %s,
                    last_success_at = now(), last_error = null
                where id = %s
                """,
                (nouvel_etag, nouveau_lm, statut, feed_id),
            )

    return report
