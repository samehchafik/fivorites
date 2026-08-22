"""La navigation dans ce qui a été collecté : vignettes, fiche, saisons.

Deux régimes de lecture, et la distinction est délibérée.

* **La grille** lit `admin.tv_card`, la projection plate (voir
  `002_admin_cards.sql`). Elle est rapide et légèrement en retard.
* **La fiche et les saisons** relisent `sourcing.raw_source`. Ce qu'on ouvre est
  donc toujours l'état réel du stockage, jamais un résumé recalculé.

C'est aussi la frontière du langage : la grille est monolingue par nature (une
vignette, un titre), tandis que la fiche est l'endroit où le sélecteur de langue
prend tout son sens — les synopsis d'épisode ne sont traduits que parce qu'on a
redemandé la saison entière dans cette langue.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from fiv_admin.media import DEFAULT_MEDIA, MEDIA, country_of

SOURCE = "tmdb"
# Le `kind` des saisons. Il n'a pas d'équivalent par univers parce que seules
# les séries en ont : `fetch_season` est, par nature, une lecture de série. Le
# `kind` des fiches, lui, vient de `media.py` — il change d'un univers à
# l'autre.
KIND_SEASON = "tv_season"

# Le barème courant : le plus récent, la même règle que l'atelier et la ligne
# de commande appliquent pour noter.
#
# Sans ce filtre, l'affichage agrège les notes de tous les barèmes confondus :
# `distinct on (id_tmdb, axe)` groupe par *nom* d'axe, or deux référentiels
# n'ont pas les mêmes noms. Une œuvre notée sous l'ancien barème et sous le
# nouveau montrerait donc les douze axes empilés — un vecteur chimère qui
# n'existe dans aucun référentiel. Et tant que rien n'est noté sous le barème
# courant, elle montrerait uniquement les axes de l'ancien.
#
# Les notes des barèmes précédents restent en base : la version EST la
# provenance, on n'écrase jamais. Elles se relisent depuis l'atelier, qui sait
# de quel barème il parle — l'affichage général, lui, n'a qu'un référentiel.
BAREME_COURANT = "(select version from notation.rubric order by created_at desc limit 1)"

# La note, pondérée par le nombre de votants.
#
# Trier sur `vote_average` brut donne un classement inutile : une série notée
# 10 par un seul votant passe devant une série notée 8,4 par vingt-deux mille.
# Ce n'est pas un cas rare — c'est le sommet de la liste, entièrement occupé par
# des séries que personne n'a vues.
#
# La correction est la moyenne bayésienne, celle qu'IMDb applique à son Top 250 :
# on ajoute à chaque série `m` votes fictifs à la note moyenne du catalogue.
# Une série à trois votes reste donc tirée vers la moyenne, et il faut du volume
# pour s'en écarter — ce qui est exactement ce qu'on veut dire par « bien notée ».
#
#     (note × votants + C × m) / (votants + m)
#
# `m = 50` : le seuil à partir duquel une note commence à vouloir dire quelque
# chose. `C = 6,5` : la moyenne observée sur TMDB, où les notes se serrent haut.
# Les deux sont des constantes assumées, pas des réglages — les rendre
# configurables donnerait un classement dont personne ne saurait plus la règle.
NOTE_VOTES_FICTIFS = sql.Literal(50)
NOTE_MOYENNE = sql.Literal(6.5)

_NOTE_PONDEREE = """(case
        when coalesce({t}.vote_count, 0) = 0 then null
        else ({t}.vote_average * {t}.vote_count + {c} * {m}) / ({t}.vote_count + {m})
    end)"""


def note_ponderee(table: str) -> sql.Composable:
    """La note pondérée, écrite sur l'alias de table demandé.

    Une série sans aucun vote vaut `null`, jamais la moyenne : elle n'est pas
    « moyennement notée », elle n'est pas notée. Le `nulls last` du tri la
    renvoie donc en fin de liste dans les deux sens, ce qui est la seule place
    honnête pour une absence de note.

    Publique parce que la réindexation (`search.py`) fige la même formule dans
    chaque document : le classement d'ES et le tri de la grille doivent rester
    une seule et même règle.
    """
    return sql.SQL(_NOTE_PONDEREE).format(t=sql.SQL(table), c=NOTE_MOYENNE, m=NOTE_VOTES_FICTIFS)


# Tris de la grille. Liste fermée : la clé vient de la requête HTTP, jamais le
# nom de colonne.
def card_sorts(pivot_card: bool = False) -> dict[str, sql.Composable]:
    """Les tris de la grille, pour un univers.

    Un seul diffère : la popularité. Les univers TMDB la lisent dans
    l'inventaire (`c.popularity`), les livres dans leur projection
    (`v.popularity`, le nombre de Wikipédias qui portent l'œuvre) — ils n'ont
    pas d'inventaire où aller la chercher.
    """
    return {
        **CARD_SORTS,
        "popularity": sql.SQL("v.popularity") if pivot_card else sql.SQL("c.popularity"),
    }


CARD_SORTS: dict[str, sql.Composable] = {
    # Le défaut demandé : de la plus récente à la plus ancienne.
    "air_date": sql.SQL("v.first_air_date"),
    # L'année seule, et c'est le seul tri qui rende un second critère utile.
    # Sur le jour exact, deux séries ont rarement la même date : le critère de
    # départage n'a alors rien à départager, et paraît ne pas fonctionner. À
    # l'année, les égalités sont massives, et « les plus récentes, et à année
    # égale les plus populaires » devient un classement lisible.
    "air_year": sql.SQL("extract(year from v.first_air_date)"),
    "name": sql.SQL("coalesce(v.name, v.original_name)"),
    "popularity": sql.SQL("c.popularity"),
    "rating": note_ponderee("v"),
    "fetched": sql.SQL("v.fetched_at"),
}

# Combien de visuels et de comédiens la fiche rapporte. Le brut en contient
# souvent des centaines ; les envoyer tous ferait peser une modale plus lourd
# que toute la grille.
GALLERY_LIMIT = 18
CAST_LIMIT = 30


# Les colonnes du SELECT final, où `page` a perdu les préfixes de tables.
PAGE_SORTS: dict[str, sql.Composable] = {
    "air_date": sql.SQL("p.first_air_date"),
    "air_year": sql.SQL("extract(year from p.first_air_date)"),
    "name": sql.SQL("coalesce(p.name, p.original_name)"),
    "popularity": sql.SQL("p.popularity"),
    "rating": note_ponderee("p"),
    "fetched": sql.SQL("p.fetched_at"),
}


def _filtre_actualite(univers: Any) -> sql.SQL:
    """« A au moins un événement d'actualité », dans la bonne géométrie.

    Les projections TMDB portent l'identifiant TMDB (`v.id = id_tmdb`), la
    projection des livres porte le pivot directement (`v.id = oeuvre.id`).
    Écrire une seule forme lierait le film 550 à l'actualité de la série 550 —
    le piège habituel des catalogues qui se chevauchent.
    """
    if univers.pivot_card:
        return sql.SQL("exists (select 1 from actualite a where a.oeuvre_id = v.id)")
    return sql.SQL(
        "exists (select 1 from actualite a"
        " join oeuvre o on o.id = a.oeuvre_id"
        " where o.univers = %(univers)s and o.id_tmdb = v.id)"
    )


@dataclass(frozen=True, slots=True)
class CardQuery:
    lang: str
    # L'univers affiché — `tv` ou `movie`. Il décide de la projection lue et du
    # filtre sur l'inventaire ; le reste de la requête est identique, les deux
    # vues ayant les mêmes colonnes.
    media: str = DEFAULT_MEDIA
    search: str | None = None
    min_popularity: float | None = None
    sort: str = "air_date"
    descending: bool = True
    # Le critère de départage. « Les plus récentes, et à date égale les plus
    # populaires » : sans lui, tout un lot de séries sorties le même jour tombe
    # dans un ordre arbitraire, qui change d'une page à l'autre.
    sort2: str | None = None
    descending2: bool = True
    # N'afficher que ce qui a une affiche. Une vignette sans visuel n'est pas un
    # défaut de la grille : TMDB n'en a pas pour tout le monde, et le fond de
    # catalogue en est largement dépourvu.
    with_poster: bool = False
    # N'afficher que ce qui a un synopsis. C'est la matière de la notation :
    # une série sans texte ne servira à rien au lot 5, quelle que soit son
    # affiche.
    with_overview: bool = False
    # Les genres retenus, en OU : « comédie ou drame ». Vide = tous. Les
    # libellés sont ceux du payload, donc **en français** — les fiches sont
    # collectées en `fr-FR` (voir 013_movie_card.sql et la table de genres de
    # la notation, qui a appris la leçon dans l'autre sens).
    genres: tuple[str, ...] = ()
    # N'afficher que les œuvres qui ont au moins un événement d'actualité —
    # c'est la lorgnette de surveillance de la dérivation : « qu'est-ce qui a
    # bougé dans le catalogue ? », pas un filtre de contenu.
    with_actualite: bool = False
    page: int = 1
    page_size: int = 24

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def criteria(self) -> tuple[tuple[str, bool], ...]:
        """Les critères effectifs, du plus fort au plus faible.

        Un second critère identique au premier est écarté : il ne départagerait
        rien, et laisser passer `order by x desc, x asc` produirait une clause
        contradictoire dont Postgres ne dirait rien.
        """
        if self.sort2 and self.sort2 != self.sort:
            return ((self.sort, self.descending), (self.sort2, self.descending2))
        return ((self.sort, self.descending),)


# Les traductions de la langue demandée, ordonnées : la région demandée
# d'abord, les autres ensuite.
#
# Deux points appris des données réelles, et non de la documentation de TMDB.
#
# **Un champ vide veut dire « pas de version localisée ».** Sur *Game of
# Thrones*, `en-US`, `de-DE` et `fr-FR` ont un `name` vide alors que leur
# `overview` est rempli : le titre n'est simplement pas traduit dans ces
# langues.
#
# **Chaque champ se résout indépendamment.** Toujours sur cette série, le titre
# français vient de `fr-CA` (« Le trône de fer ») pendant que le synopsis vient
# de `fr-FR`. Prendre une seule entrée pour les deux ferait perdre l'un ou
# l'autre — d'où une liste rendue par le SQL, et le choix fait en Python, champ
# par champ.
_TRADUCTIONS_LANGUE = """
                       coalesce((
                           select jsonb_agg(
                               t -> 'data' order by (t ->> 'iso_3166_1' = %(region)s) desc
                           )
                           from jsonb_array_elements(
                               coalesce(
                                   r.payload -> 'translations' -> 'translations', '[]'::jsonb
                               )
                           ) t
                           where t ->> 'iso_639_1' = %(lang2)s
                       ), '[]'::jsonb)"""


def _premier_non_vide(traductions: list[dict[str, Any]] | None, champ: str) -> str | None:
    """La première valeur non vide de ce champ, dans l'ordre rendu par le SQL."""
    for entree in traductions or []:
        valeur = (entree.get(champ) or "").strip()
        if valeur:
            return valeur
    return None


# Les traductions des seules séries de la page affichée.
#
# C'est la seule entorse à la règle « aucune liste ne lit `payload` », et elle
# est bornée : au plus `pageSize` payloads ouverts, jamais le catalogue entier.
# L'alternative était de porter les traductions dans la projection — de l'ordre
# de deux cents mégaoctets, et une liste de langues figée dans une migration
# alors que le contrat de données rappelle qu'elle est un réglage.
_TRADUCTIONS = sql.SQL(
    """
                , traductions as (
                    select distinct on (r.source_id) r.source_id as sid,"""
    + _TRADUCTIONS_LANGUE
    + """ as data
                    from raw_source r
                    where r.source = %(source)s and r.kind = %(kind)s
                      and r.http_status between 200 and 299 and r.payload is not null
                      and r.source_id = any (array(select id::text from page))
                    order by r.source_id, r.fetched_at desc
                )
"""
)

# La même chose pour les livres, depuis leur vraie source de titres traduits :
# les articles Wikipédia. `riche_source.source_id` d'une ligne wikipedia EST le
# titre de l'article dans sa langue — « Cent ans de solitude » sur frwiki,
# « مائة عام من العزلة » sur arwiki — et son `content` le texte. Même interface
# que `_TRADUCTIONS` (sid, data) pour que la jointure ne change pas.
#
# L'aperçu est tronqué en SQL : un article courant pèse cent kilooctets, et la
# grille n'en montre que quelques lignes — transporter vingt-quatre articles
# entiers pour ça ferait des pages de plusieurs mégaoctets.
_TRADUCTIONS_LIVRES = sql.SQL(
    """
                , traductions as (
                    select r.oeuvre_id::text as sid,
                           jsonb_build_array(jsonb_build_object(
                               'name', r.source_id,
                               'overview', left(r.content, 1200))) as data
                    from riche_source r
                    where r.source = 'wikipedia' and r.lang = %(lang2)s
                      and r.oeuvre_id = any (array(select id from page))
                )
"""
)


def _order_by(
    criteria: tuple[tuple[str, bool], ...],
    columns: dict[str, sql.Composable],
    tiebreak: sql.SQL,
) -> sql.SQL:
    """La clause de tri, plus un départage final sur l'id.

    Le départage n'est pas cosmétique : sans lui, deux lignes que tous les
    critères déclarent égales peuvent changer de place entre deux pages, et la
    pagination fait alors apparaître deux fois la même série ou en saute une.
    """
    parts = [
        sql.SQL("{} {} nulls last").format(
            columns[key], sql.SQL("desc") if desc else sql.SQL("asc")
        )
        for key, desc in criteria
    ]
    parts.append(tiebreak)
    return sql.SQL(", ").join(parts)


async def fetch_cards(
    conn: psycopg.AsyncConnection, q: CardQuery, ids: Sequence[int] | None = None
) -> tuple[list[dict[str, Any]], int]:
    """Une page de vignettes, et le total du filtre.

    Deux régimes, même requête :

    * `ids=None` — le filtrage, le tri et la pagination sont faits ici, en SQL.
    * `ids=[…]` — Elasticsearch a déjà filtré, classé et paginé (voir
      `search.py`) ; le SQL ne fait plus qu'hydrater ces vignettes-là, dans
      l'ordre reçu (`array_position`). Le total rendu est alors le nombre de
      lignes hydratées : c'est le total d'ES qui fait foi, et c'est l'appelant
      qui le porte.
    """
    univers = MEDIA[q.media]
    if ids is not None and not ids:
        return [], 0
    # Le français est déjà dans la projection : inutile de rouvrir vingt-quatre
    # payloads pour retrouver ce qu'on a sous la main. C'est aussi la langue par
    # défaut, donc le cas le plus fréquent — la page d'accueil reste aussi
    # rapide qu'avant.
    #
    # Sauf pour les livres : leur `name` projeté est le libellé Wikidata, servi
    # avec une préférence anglaise — le seul choix stable pour une projection
    # sans langue. Le titre d'affichage vient donc TOUJOURS de la traduction
    # (le titre d'article Wikipédia de la langue demandée), français compris.
    langue = q.lang.split("-")[0]
    traduire = langue != "fr" or univers.pivot_card

    params: dict[str, Any] = {
        "source": SOURCE,
        "kind": univers.kind,
        "part_kind": univers.part_kind or "",
        "univers": univers.univers,
        "lang2": langue,
        "region": q.lang.rpartition("-")[2],
        "limit": q.page_size,
        "offset": q.offset,
        "search": q.search or None,
        "like": f"%{q.search}%" if q.search else None,
        "search_id": int(q.search) if q.search and q.search.isdigit() else None,
        "min_popularity": q.min_popularity,
        "genres": list(q.genres) or None,
    }

    if ids is not None:
        # La page est déjà décidée : ces ids-là, dans cet ordre-là. Les autres
        # filtres ont été appliqués par ES, les rejouer ici pourrait seulement
        # diverger — au pire une vignette disparue de la projection tombe de
        # la page, ce que la jointure fait d'elle-même.
        params["ids"] = list(ids)
        params["limit"] = len(ids)
        params["offset"] = 0
        # `::bigint[]` et `::bigint` des deux côtés : les ids d'ES arrivent en
        # integer[], et `v.id` est un int pour les séries mais un BIGINT pour
        # les livres (le pivot). Postgres 13 — celui du serveur — refuse
        # array_position(integer[], bigint) ; les versions récentes unifient
        # silencieusement, ce qui a caché le bug en local. Le cast explicite
        # est vrai partout.
        where = sql.SQL("v.id = any(%(ids)s::bigint[])")
        if q.with_actualite:
            # L'index de recherche ne connaît pas l'actualité : le filtre se
            # rejoue en SQL sur la page choisie par ES. Le total, lui, vient
            # d'ES et peut donc surcompter — des pages de fin plus courtes,
            # pas des lignes fausses. L'alternative serait d'indexer
            # l'actualité dans ES pour un filtre d'administration : non.
            where = sql.SQL(" and ").join([where, _filtre_actualite(univers)])
        order = sql.SQL("array_position(%(ids)s::bigint[], v.id::bigint)")
        order_page = sql.SQL("array_position(%(ids)s::bigint[], p.id::bigint)")
    else:
        where = sql.SQL(" and ").join(
            [
                sql.SQL(
                    "(%(search)s::text is null"
                    " or v.name ilike %(like)s"
                    " or v.original_name ilike %(like)s"
                    " or v.id = %(search_id)s::int)"
                ),
                sql.SQL("(%(min_popularity)s::real is null or {pop} >= %(min_popularity)s)").format(
                    pop=sql.SQL("v.popularity") if univers.pivot_card else sql.SQL("c.popularity")
                ),
                # `nullif` parce que TMDB renvoie tantôt `null`, tantôt une
                # chaîne vide : les deux veulent dire « pas d'affiche », et
                # n'en traiter qu'un laisserait passer des vignettes trouées.
                sql.SQL("nullif(v.poster_path, '') is not null")
                if q.with_poster
                else sql.SQL("true"),
                # Même précaution que pour l'affiche, et elle sert plus souvent
                # encore : un `overview` non traduit revient en chaîne vide,
                # pas en `null`. Tester `is not null` seul ne filtrerait
                # presque rien.
                sql.SQL("nullif(btrim(v.overview), '') is not null")
                if q.with_overview
                else sql.SQL("true"),
                # Les genres vivent en jsonb dans la projection — `[{id, name}]`.
                # Sans index dessus, c'est un parcours ; c'est justement ce
                # qu'Elasticsearch évite, et ce repli n'est là que pour les
                # moments où il ne répond pas.
                sql.SQL(
                    "(%(genres)s::text[] is null or exists ("
                    " select 1 from jsonb_array_elements(coalesce(v.genres, '[]'::jsonb)) g"
                    " where g ->> 'name' = any (%(genres)s)))"
                ),
                # Livres : la langue d'affichage filtre — écrit ou traduit
                # dans la langue de la grille, sinon la carte est illisible
                # pour son lecteur. Les autres projections n'ont pas la
                # colonne, et leur langue n'est pas un filtre.
                sql.SQL("v.langues ? %(lang2)s") if univers.pivot_card else sql.SQL("true"),
                _filtre_actualite(univers) if q.with_actualite else sql.SQL("true"),
            ]
        )

        order = _order_by(q.criteria, card_sorts(univers.pivot_card), sql.SQL("v.id desc"))
        order_page = _order_by(q.criteria, PAGE_SORTS, sql.SQL("p.id desc"))

    async with conn.cursor(row_factory=dict_row) as cur:
        total = 0
        if ids is None:
            await cur.execute(
                sql.SQL(
                    """
                    select count(*) as total
                    from admin.{vue} v
                    left join tmdb_catalog c on c.univers = %(univers)s and c.id = v.id
                    where {where}
                    """
                ).format(where=where, vue=sql.Identifier(univers.card_view)),
                params,
            )
            row = await cur.fetchone()
            total = int(row["total"]) if row else 0

        await cur.execute(
            sql.SQL(
                """
                with page as (
                    select v.id, v.name, v.original_name, {apercu} as overview, v.poster_path,
                           v.backdrop_path, v.status, v.original_language,
                           v.first_air_date, v.last_air_date, v.number_of_seasons,
                           v.number_of_episodes, v.vote_average, v.vote_count,
                           v.genres, v.origin_country, v.fetched_at,
                           {popularite}, c.adult
                    from admin.{vue} v
                    left join tmdb_catalog c on c.univers = %(univers)s and c.id = v.id
                    where {where}
                    order by {order}
                    limit %(limit)s offset %(offset)s
                ),
                -- La couverture par langue de la page, dans la même requête :
                -- une vignette porte ses pastilles de langue sans aller-retour
                -- supplémentaire.
                by_lang as (
                    select split_part(r.source_id, '/', 1) as sid,
                           r.lang,
                           count(distinct r.source_id)
                               filter (where r.http_status between 200 and 299) as ok,
                           count(distinct r.source_id)
                               filter (where r.http_status not between 200 and 299) as failed
                    from raw_source r
                    where r.source = %(source)s and r.kind = %(part_kind)s
                      and r.lang is not null
                      and split_part(r.source_id, '/', 1) = any (array(select id::text from page))
                    group by 1, 2
                ),
                langs as (
                    select sid,
                           jsonb_object_agg(lang, jsonb_build_object('ok', ok, 'failed', failed))
                               as coverage
                    from by_lang group by sid
                ),
                parts as (
                    select split_part(s.source_id, '/', 1) as sid, count(*) as expected
                    from fetch_state s
                    where s.source = %(source)s and s.kind = %(part_kind)s
                      and split_part(s.source_id, '/', 1) = any (array(select id::text from page))
                    group by 1
                ),
                -- L'empreinte courante : la note la plus récente par axe, sous
                -- le barème courant (cf. BAREME_COURANT), venue du juge —
                -- jamais la contre-note manuelle, jamais la prédiction interne,
                -- c'est le verdict qui fait foi tant que la régression n'est
                -- pas devenue la référence. Absent tant qu'une série n'a jamais
                -- été notée sous ce barème : `null`, pas des zéros.
                scores as (
                    select distinct on ({pivot}, s.axe) {pivot} as id_tmdb, s.axe, s.valeur
                    from notation.score s
                    join sourcing.oeuvre o on o.id = s.oeuvre_id
                    where o.univers = %(univers)s
                      and {pivot} = any (array(select id from page))
                      and s.valeur is not null
                      and s.rubric_version = {bareme}
                      and s.modele <> 'interne-ridge' and s.modele not like 'claude%%'
                    order by {pivot}, s.axe, s.scored_at desc
                ),
                vectors as (
                    select id_tmdb, jsonb_object_agg(axe, valeur) as axis_scores
                    from scores group by id_tmdb
                ),
                -- La prédiction de la régression, dans les mêmes conditions.
                -- Elle sert à afficher l'écart avec le juge : c'est la mesure
                -- de ce que le modèle interne a appris, œuvre par œuvre.
                internes as (
                    select distinct on ({pivot}, s.axe) {pivot} as id_tmdb, s.axe, s.valeur
                    from notation.score s
                    join sourcing.oeuvre o on o.id = s.oeuvre_id
                    where o.univers = %(univers)s
                      and {pivot} = any (array(select id from page))
                      and s.valeur is not null and s.modele = 'interne-ridge'
                      and s.rubric_version = {bareme}
                    order by {pivot}, s.axe, s.scored_at desc
                ),
                vecteurs_internes as (
                    select id_tmdb, jsonb_object_agg(axe, valeur) as internal_scores
                    from internes group by id_tmdb
                )
                {traductions}
                select p.*,
                       coalesce(l.coverage, '{{}}'::jsonb) as coverage,
                       coalesce(t.expected, 0) as parts_expected,
                       sv.axis_scores,
                       iv.internal_scores,
                       {traduction}
                from page p
                left join langs l on l.sid = p.id::text
                left join parts t on t.sid = p.id::text
                left join vectors sv on sv.id_tmdb = p.id
                left join vecteurs_internes iv on iv.id_tmdb = p.id
                {jointure}
                order by {order_page}
                """
            ).format(
                where=where,
                vue=sql.Identifier(univers.card_view),
                order=order,
                order_page=order_page,
                bareme=sql.SQL(BAREME_COURANT),
                # Les livres n'ont pas d'id TMDB : leurs vignettes sont keyées
                # par le pivot, et les notes se joignent donc sur `o.id`.
                pivot=sql.SQL("o.id") if univers.pivot_card else sql.SQL("o.id_tmdb"),
                popularite=(
                    sql.SQL("v.popularity") if univers.pivot_card else sql.SQL("c.popularity")
                ),
                # L'aperçu d'un livre est un article Wikipédia entier ; la
                # grille n'en montre que quelques lignes.
                apercu=(
                    sql.SQL("left(v.overview, 1200)")
                    if univers.pivot_card
                    else sql.SQL("v.overview")
                ),
                traductions=(
                    (_TRADUCTIONS_LIVRES if univers.pivot_card else _TRADUCTIONS)
                    if traduire
                    else sql.SQL("")
                ),
                traduction=(
                    sql.SQL("coalesce(x.data, '[]'::jsonb) as traduction")
                    if traduire
                    else sql.SQL("'[]'::jsonb as traduction")
                ),
                jointure=(
                    sql.SQL("left join traductions x on x.sid = p.id::text")
                    if traduire
                    else sql.SQL("")
                ),
            ),
            params,
        )
        rows = await cur.fetchall()

    return [_shape_card(row, q.lang) for row in rows], (total if ids is None else len(rows))


def _repli_titre(row: dict[str, Any], lang: str) -> str | None:
    """Le titre à montrer faute de traduction : l'original, sauf en français."""
    if lang.split("-")[0] == "fr":
        return row["name"] or row["original_name"]
    return row["original_name"] or row["name"]


def _shape_card(row: dict[str, Any], lang: str) -> dict[str, Any]:
    # Le texte traduit s'il existe, le français sinon. La vignette ne dit pas
    # lequel des deux elle montre : sur une grille de vingt-quatre cartes, la
    # mention serait du bruit — c'est la fiche qui l'annonce, à l'endroit où on
    # lit vraiment le texte.
    traduites = row.get("traduction")
    nom = _premier_non_vide(traduites, "name")
    synopsis = _premier_non_vide(traduites, "overview")

    coverage: dict[str, Any] = row["coverage"] or {}
    expected = int(row["parts_expected"] or 0)
    selected = coverage.get(lang) or {"ok": 0, "failed": 0}
    ok = int(selected.get("ok") or 0)

    return {
        "id": row["id"],
        # Quand le titre n'est pas traduit, TMDB affiche le titre **original**,
        # pas la version française : un `name` vide dans les traductions veut
        # dire « cette langue n'a pas de titre à elle ». Retomber sur le
        # français afficherait « Le Trône de fer » à un lecteur arabophone dont
        # la série s'appelle « Game of Thrones » partout ailleurs.
        #
        # Le français fait exception, et c'est le seul : la fiche ayant été
        # demandée en `fr-FR`, la racine du payload porte déjà son titre
        # d'affichage — traductions comprises.
        "name": nom or _repli_titre(row, lang),
        "originalName": row["original_name"],
        "overview": synopsis or row["overview"],
        "posterPath": row["poster_path"],
        "backdropPath": row["backdrop_path"],
        "status": row["status"],
        "originalLanguage": row["original_language"],
        "firstAirDate": row["first_air_date"],
        "lastAirDate": row["last_air_date"],
        "year": row["first_air_date"].year if row["first_air_date"] else None,
        "seasons": row["number_of_seasons"],
        "episodes": row["number_of_episodes"],
        "voteAverage": row["vote_average"],
        "voteCount": row["vote_count"],
        "genres": [genre.get("name") for genre in (row["genres"] or []) if genre.get("name")],
        "originCountry": row["origin_country"] or [],
        "popularity": float(row["popularity"]) if row["popularity"] is not None else None,
        "fetchedAt": row["fetched_at"],
        # Le vecteur de goût courant, axe → note (1-10) — absent tant que la
        # série n'a jamais été jugée. `None`, jamais un objet vide : la carte
        # doit pouvoir distinguer « pas encore notée » de « notée à zéro
        # partout », ce qui n'existe pas dans le barème.
        "axisScores": row.get("axis_scores"),
        # La prédiction interne, à côté du verdict : l'écart entre les deux
        # est la seule lecture directe de ce que la régression a appris.
        "internalScores": row.get("internal_scores"),
        "expectedParts": expected,
        "coverage": {
            code: {"ok": int(value.get("ok") or 0), "failed": int(value.get("failed") or 0)}
            for code, value in coverage.items()
        },
        "selected": {
            "lang": lang,
            "ok": ok,
            "failed": int(selected.get("failed") or 0),
            "ratio": (ok / expected) if expected else None,
        },
    }


async def _fetch_work_livre(
    conn: psycopg.AsyncConnection, work_id: int, lang: str
) -> dict[str, Any] | None:
    """La fiche d'un livre — assemblée depuis `riche_source`, pas depuis un brut.

    Un livre n'a pas de fiche TMDB : sa matière vient de l'enrichissement
    (Wikidata pour les faits, Open Library pour la description et les
    éditions, Wikipédia pour le texte long). La forme rendue est **celle de
    `fetch_work`**, clé pour clé — c'est ce qui permet au front d'ouvrir la
    même modale ; ce qu'un livre n'a pas (affiche, saisons, distribution,
    diffusion) est vide ou null, comme pour une série lacunaire.

    Les traductions affichées sont les langues d'édition d'Open Library — la
    donnée que l'univers livre existe pour porter — complétées des langues
    d'articles Wikipédia collectées.
    """
    lang2 = lang.split("-")[0]
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select id, titre, annee, wikidata_qid, id_openlibrary
            from sourcing.oeuvre where univers = 'livres' and id = %s
            """,
            (work_id,),
        )
        oeuvre = await cur.fetchone()
        if oeuvre is None:
            return None

        await cur.execute(
            """
            select source, lang, source_id, content, facts, media, url, fetched_at
            from riche_source where oeuvre_id = %s
            """,
            (work_id,),
        )
        riches = await cur.fetchall()

        # L'empreinte et la prédiction interne — mêmes règles que `fetch_work`,
        # la jointure en moins : le livre EST désigné par son pivot.
        await cur.execute(
            f"""
            select distinct on (s.axe) s.axe, s.valeur
            from notation.score s
            where s.oeuvre_id = %s and s.valeur is not null
              and s.rubric_version = {BAREME_COURANT}
              and s.modele <> 'interne-ridge' and s.modele not like 'claude%%'
            order by s.axe, s.scored_at desc
            """,
            (work_id,),
        )
        axis_scores = {row["axe"]: float(row["valeur"]) for row in await cur.fetchall()}
        await cur.execute(
            f"""
            select distinct on (s.axe) s.axe, s.valeur
            from notation.score s
            where s.oeuvre_id = %s and s.valeur is not null
              and s.modele = 'interne-ridge' and s.rubric_version = {BAREME_COURANT}
            order by s.axe, s.scored_at desc
            """,
            (work_id,),
        )
        internal_scores = {row["axe"]: float(row["valeur"]) for row in await cur.fetchall()}

    wikipedia = {r["lang"]: r for r in riches if r["source"] == "wikipedia"}
    wikidata = next((r for r in riches if r["source"] == "wikidata"), None)
    openlib = next((r for r in riches if r["source"] == "openlibrary"), None)
    faits_wd = (wikidata or {}).get("facts") or {}
    faits_ol = (openlib or {}).get("facts") or {}
    editions = (faits_ol.get("editions") or {}).get("par_langue") or []

    # Le texte long dans la langue demandée, puis le repli — fr, en, la plus
    # longue collectée — puis la description Open Library. On dit lequel :
    # même contrat `translated` que les séries.
    #
    # Le titre suit la même règle : le `source_id` d'une ligne wikipedia EST
    # le titre de l'article dans sa langue — c'est lui qu'on affiche, jamais
    # le libellé Wikidata (servi avec une préférence anglaise) tant qu'un
    # article existe dans la langue demandée.
    article = wikipedia.get(lang2)
    repli = next(
        (wikipedia[code] for code in ("fr", "en") if code in wikipedia),
        max(wikipedia.values(), key=lambda r: len(r["content"] or ""), default=None),
    )
    overview = (
        (article or {}).get("content")
        or (repli or {}).get("content")
        or ((openlib or {}).get("content"))
    )

    auteurs = [a.get("nom") for a in faits_wd.get("auteurs") or [] if a.get("nom")]
    annee = faits_wd.get("annee") or oeuvre["annee"]
    langues_editions = sorted({e["langue"] for e in editions} | set(wikipedia))
    # Les couvertures Open Library — des URL complètes, que `tmdbImage` côté
    # front laisse passer telles quelles. La première en affiche, le reste en
    # galerie.
    couvertures = [
        image["url"]
        for image in (openlib or {}).get("media") or []
        if image.get("type") == "poster" and image.get("url")
    ]

    return {
        "id": work_id,
        "name": (article or {}).get("source_id") or oeuvre["titre"] or faits_ol.get("titre"),
        "originalName": oeuvre["titre"],
        "tagline": None,
        "overview": overview,
        "translated": {
            "lang": lang,
            "name": article is not None,
            "overview": article is not None,
        },
        "posterPath": couvertures[0] if couvertures else None,
        "backdropPath": None,
        "homepage": (openlib or {}).get("url"),
        "status": None,
        "type": "livre",
        "originalLanguage": next(iter(faits_wd.get("langues") or []), None),
        "firstAirDate": f"{annee}-01-01" if annee else None,
        "lastAirDate": None,
        "numberOfSeasons": None,
        "numberOfEpisodes": None,
        "voteAverage": None,
        "voteCount": None,
        "genres": [],
        "networks": [],
        "createdBy": auteurs,
        "originCountry": faits_wd.get("pays") or [],
        "externalIds": {
            "wikidata_id": oeuvre["wikidata_qid"],
            "openlibrary_id": oeuvre["id_openlibrary"],
        },
        "translations": langues_editions,
        "gallery": {"backdrops": [], "posters": couvertures},
        "cast": [],
        "watch": _shape_watch({}, [], lang),
        "seasons": [],
        "raw": {
            "fetchedAt": (wikidata or openlib or {}).get("fetched_at"),
            "httpStatus": 200 if riches else None,
        },
        "axisScores": axis_scores or None,
        "internalScores": internal_scores or None,
        "videos": [],
        # Le pendant du bloc `tmdb_catalog` des autres univers : la fiche
        # affiche « Popularité » depuis `catalog.popularity`, et un livre la
        # tient de sa notoriété Wikipédia (facts.sitelinks) — la même valeur
        # que la vignette et le tri. Absent tant que le crawl ne l'a pas
        # collectée : `—` à l'écran, pas un zéro inventé.
        "catalog": (
            {
                "popularity": float(faits_wd["sitelinks"]),
                "adult": None,
                "exportedOn": None,
            }
            if faits_wd.get("sitelinks") is not None
            else None
        ),
    }


async def fetch_work(
    conn: psycopg.AsyncConnection, work_id: int, lang: str, media: str = DEFAULT_MEDIA
) -> dict[str, Any] | None:
    """La fiche complète, lue dans le brut.

    Les tableaux volumineux — visuels, distribution — sont tronqués **en SQL**
    par `jsonb_path_query_array` : on ne transporte pas six cents affiches pour
    en afficher dix-huit.
    """
    univers = MEDIA[media]
    if univers.pivot_card:
        # Un livre n'a pas de brut TMDB à lire : sa fiche s'assemble depuis
        # l'enrichissement, sous la même forme.
        return await _fetch_work_livre(conn, work_id, lang)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select r.fetched_at, r.http_status,
                   -- Un film nomme son titre `title` et sa date `release_date`.
                   -- `coalesce` plutôt qu'une seconde requête : les deux champs
                   -- ne coexistent jamais, et la fiche garde une seule forme
                   -- pour le front.
                   coalesce(r.payload ->> 'name', r.payload ->> 'title')   as name,
                   coalesce(r.payload ->> 'original_name',
                            r.payload ->> 'original_title')                as original_name,
                   r.payload ->> 'overview'              as overview,
                   r.payload ->> 'tagline'               as tagline,
                   r.payload ->> 'poster_path'           as poster_path,
                   r.payload ->> 'backdrop_path'         as backdrop_path,
                   r.payload ->> 'homepage'              as homepage,
                   r.payload ->> 'status'                as status,
                   r.payload ->> 'type'                  as type,
                   r.payload ->> 'original_language'     as original_language,
                   nullif(r.payload ->> 'first_air_date', '')      as first_air_date,
                   nullif(r.payload ->> 'last_air_date', '')       as last_air_date,
                   nullif(r.payload ->> 'number_of_seasons', '')::int  as number_of_seasons,
                   nullif(r.payload ->> 'number_of_episodes', '')::int as number_of_episodes,
                   nullif(r.payload ->> 'vote_average', '')::real  as vote_average,
                   nullif(r.payload ->> 'vote_count', '')::int     as vote_count,
                   coalesce(r.payload -> 'genres', '[]'::jsonb)         as genres,
                   coalesce(r.payload -> 'networks', '[]'::jsonb)       as networks,
                   coalesce(r.payload -> 'created_by', '[]'::jsonb)     as created_by,
                   coalesce(r.payload -> 'origin_country', '[]'::jsonb) as origin_country,
                   coalesce(r.payload -> 'seasons', '[]'::jsonb)        as seasons,
                   coalesce(r.payload -> 'external_ids', '{}'::jsonb)   as external_ids,
                   jsonb_path_query_array(r.payload, %(backdrops)s::jsonpath) as backdrops,
                   jsonb_path_query_array(r.payload, %(posters)s::jsonpath)   as posters,
                   -- `aggregate_credits` consolide toute la série ; `credits` ne
                   -- donne que la saison 1. On prend le premier des deux.
                   coalesce(
                       nullif(
                           jsonb_path_query_array(r.payload, %(agg_cast)s::jsonpath),
                           '[]'::jsonb
                       ),
                       jsonb_path_query_array(r.payload, %(cast)s::jsonpath)
                   ) as members,
                   coalesce((
                       select jsonb_agg(distinct t ->> 'iso_639_1')
                       from jsonb_array_elements(
                           coalesce(r.payload -> 'translations' -> 'translations', '[]'::jsonb)
                       ) t
                   ), '[]'::jsonb) as translations,
                   -- Le titre et le synopsis dans la langue demandée.
                   --
                   -- La fiche n'est téléchargée qu'une fois, en `fr-FR` : sans
                   -- cette extraction, changer de langue ne changeait rien au
                   -- texte affiché. Les traductions sont pourtant là — c'est
                   -- `append_to_response=translations` qui les apporte — mais
                   -- personne ne les lisait.
                   --
                   -- L'ordre départage les variantes régionales d'une même
                   -- langue : `ar-SA` d'abord, puis n'importe quel `ar`. TMDB
                   -- en renvoie plusieurs (ar-AE, ar-SA…) et prendre la
                   -- première venue donnerait un résultat instable d'une
                   -- collecte à l'autre.
                  coalesce((
                           select jsonb_agg(
                               t -> 'data' order by (t ->> 'iso_3166_1' = %(region)s) desc
                           )
                           from jsonb_array_elements(
                               coalesce(
                                   r.payload -> 'translations' -> 'translations', '[]'::jsonb
                               )
                           ) t
                           where t ->> 'iso_639_1' = %(lang2)s
                       ), '[]'::jsonb) as traduction,
                   -- La disponibilité en streaming, pour le pays de la langue
                   -- choisie seulement. Le brut en porte une centaine ; les
                   -- envoyer tous ferait transiter un catalogue mondial pour
                   -- afficher trois logos.
                   coalesce(
                       r.payload -> 'watch/providers' -> 'results' -> %(country)s,
                       '{}'::jsonb
                   ) as providers,
                   -- Les pays où la série est disponible, pour pouvoir dire
                   -- « rien chez vous, mais disponible ailleurs » plutôt qu'un
                   -- vide qu'on prendrait pour une donnée manquante.
                   coalesce((
                       select jsonb_agg(pays order by pays)
                       from jsonb_object_keys(
                           coalesce(r.payload -> 'watch/providers' -> 'results', '{}'::jsonb)
                       ) as pays
                   ), '[]'::jsonb) as provider_countries
            from raw_source r
            where r.source = %(source)s and r.kind = %(kind)s and r.source_id = %(id)s
              and r.http_status between 200 and 299
            order by r.fetched_at desc
            limit 1
            """,
            {
                "source": SOURCE,
                "kind": univers.kind,
                "id": str(work_id),
                "country": country_of(lang) or "",
                "lang2": lang.split("-")[0],
                "region": country_of(lang) or "",
                "backdrops": f"$.images.backdrops[0 to {GALLERY_LIMIT - 1}]",
                "posters": f"$.images.posters[0 to {GALLERY_LIMIT - 1}]",
                "agg_cast": f"$.aggregate_credits.cast[0 to {CAST_LIMIT - 1}]",
                "cast": f"$.credits.cast[0 to {CAST_LIMIT - 1}]",
            },
        )
        head = await cur.fetchone()
        if head is None:
            return None

        # L'état de collecte de chaque saison, langue par langue : c'est ce qui
        # dit à l'accordéon quelles langues il peut proposer.
        #
        # Sautée pour un univers sans parties : un film n'a pas de saison, et
        # la requête rendrait de toute façon zéro ligne — autant ne pas la
        # poser, et dire pourquoi.
        collected: list[dict[str, Any]] = []
        if univers.part_kind is not None:
            await cur.execute(
                """
                select split_part(source_id, '/', 2) as season,
                       lang,
                       max(http_status) as http_status,
                       max(fetched_at) as fetched_at
                from raw_source
                where source = %(source)s and kind = %(part_kind)s
                  and split_part(source_id, '/', 1) = %(id)s
                  and lang is not null
                group by 1, 2
                """,
                {"source": SOURCE, "part_kind": univers.part_kind, "id": str(work_id)},
            )
            collected = await cur.fetchall()

        await cur.execute(
            "select popularity, adult, exported_on from tmdb_catalog"
            " where univers = %s and id = %s",
            (univers.univers, work_id),
        )
        catalog = await cur.fetchone()

        # L'empreinte courante — même règle que sur les vignettes : le dernier
        # verdict du juge par axe sous le barème courant, jamais la contre-note
        # manuelle, ni la prédiction interne.
        await cur.execute(
            f"""
            select distinct on (s.axe) s.axe, s.valeur
            from notation.score s
            join sourcing.oeuvre o on o.id = s.oeuvre_id
            where o.univers = %s and o.id_tmdb = %s and s.valeur is not null
              and s.rubric_version = {BAREME_COURANT}
              and s.modele <> 'interne-ridge' and s.modele not like 'claude%%'
            order by s.axe, s.scored_at desc
            """,
            (univers.univers, work_id),
        )
        axis_scores = {row["axe"]: float(row["valeur"]) for row in await cur.fetchall()}

        # La prédiction interne, pour afficher l'écart avec le juge.
        await cur.execute(
            f"""
            select distinct on (s.axe) s.axe, s.valeur
            from notation.score s
            join sourcing.oeuvre o on o.id = s.oeuvre_id
            where o.univers = %s and o.id_tmdb = %s and s.valeur is not null
              and s.modele = 'interne-ridge'
              and s.rubric_version = {BAREME_COURANT}
            order by s.axe, s.scored_at desc
            """,
            (univers.univers, work_id),
        )
        internal_scores = {row["axe"]: float(row["valeur"]) for row in await cur.fetchall()}

        # Les vidéos, la meilleure d'abord — `priorite` porte déjà la
        # préférence de type et d'officialité (cf. migration 010). La langue
        # départage ensuite : le français d'abord pour une interface française,
        # puis l'anglais, puis le reste. C'est un ordre d'affichage, pas un
        # filtre : une série dont la seule bande-annonce est italienne doit
        # quand même en avoir une.
        #
        # `vivante is not false` et non `is true` : une vidéo jamais vérifiée
        # (null) reste montrée. La prudence ne doit pas vider l'onglet avant
        # que la première passe de `videos-check` ait tourné — ce qui serait
        # une régression garantie le jour de la mise en service.
        await cur.execute(
            """
            select v.site, v.cle, v.type, v.nom, v.lang, v.officiel, v.publie_le,
                   v.definition, v.saison
            from sourcing.video v
            join sourcing.oeuvre o on o.id = v.oeuvre_id
            where o.univers = %s and o.id_tmdb = %s and v.vivante is not false
            order by v.priorite,
                     case v.lang when 'fr' then 0 when 'en' then 1 else 2 end,
                     v.publie_le desc nulls last
            """,
            (univers.univers, work_id),
        )
        videos = [
            {
                "site": row["site"],
                "key": row["cle"],
                "type": row["type"],
                "name": row["nom"],
                "lang": row["lang"] or None,
                "official": row["officiel"],
                "publishedAt": row["publie_le"],
                "definition": row["definition"],
                "season": row["saison"],
            }
            for row in await cur.fetchall()
        ]

    by_season: dict[int, dict[str, Any]] = {}
    for row in collected:
        number = int(row["season"].removeprefix("s")) if row["season"].startswith("s") else -1
        by_season.setdefault(number, {})[row["lang"]] = {
            "status": row["http_status"],
            "fetchedAt": row["fetched_at"],
        }

    seasons = [
        {
            "seasonNumber": season.get("season_number"),
            "name": season.get("name"),
            "overview": season.get("overview"),
            "airDate": season.get("air_date") or None,
            "episodeCount": season.get("episode_count"),
            "posterPath": season.get("poster_path"),
            "collected": by_season.get(season.get("season_number"), {}),
            "hasSelectedLang": lang in by_season.get(season.get("season_number"), {}),
        }
        for season in head["seasons"]
    ]

    # Le texte traduit s'il existe, le français sinon — et l'on dit lequel.
    # Afficher un synopsis français en prétendant montrer l'arabe induirait en
    # erreur sur ce qui est réellement collecté, ce que ce tableau de bord a
    # précisément pour rôle de mesurer.
    # Le français ne passe pas par les traductions : la fiche ayant été demandée
    # à TMDB avec `language=fr-FR`, la racine du payload porte déjà le titre
    # d'affichage français, résolu par TMDB lui-même. Y rechercher nous-mêmes
    # ramènerait par exemple le `fr-CA` « Le trône de fer » là où la racine dit
    # « Le Trône de fer » — une régression silencieuse sur la langue par défaut.
    traduites = head["traduction"] if lang.split("-")[0] != "fr" else []
    nom = _premier_non_vide(traduites, "name")
    synopsis = _premier_non_vide(traduites, "overview")
    accroche = _premier_non_vide(traduites, "tagline")

    return {
        "id": work_id,
        # Faute de titre traduit, TMDB montre le titre original — pas la
        # version française. Le français fait exception : la fiche ayant été
        # demandée en `fr-FR`, la racine du payload porte déjà son titre.
        "name": nom or _repli_titre(head, lang),
        "originalName": head["original_name"],
        "tagline": accroche or head["tagline"] or None,
        "overview": synopsis or head["overview"],
        # Ce que la langue choisie a réellement apporté. Le front s'en sert pour
        # signaler un repli plutôt que de le laisser passer inaperçu.
        "translated": {
            "lang": lang,
            "name": nom is not None,
            "overview": synopsis is not None,
        },
        "posterPath": head["poster_path"],
        "backdropPath": head["backdrop_path"],
        "homepage": head["homepage"] or None,
        "status": head["status"],
        "type": head["type"],
        "originalLanguage": head["original_language"],
        "firstAirDate": head["first_air_date"],
        "lastAirDate": head["last_air_date"],
        "numberOfSeasons": head["number_of_seasons"],
        "numberOfEpisodes": head["number_of_episodes"],
        "voteAverage": head["vote_average"],
        "voteCount": head["vote_count"],
        "genres": [genre.get("name") for genre in head["genres"] if genre.get("name")],
        "networks": [
            {"name": network.get("name"), "logoPath": network.get("logo_path")}
            for network in head["networks"]
        ],
        "createdBy": [person.get("name") for person in head["created_by"] if person.get("name")],
        "originCountry": head["origin_country"],
        "externalIds": head["external_ids"],
        "translations": sorted(head["translations"] or []),
        "gallery": {
            "backdrops": [image.get("file_path") for image in head["backdrops"]],
            "posters": [image.get("file_path") for image in head["posters"]],
        },
        "cast": [_shape_member(member) for member in head["members"]],
        "watch": _shape_watch(head["providers"], head["provider_countries"], lang),
        "seasons": seasons,
        "raw": {"fetchedAt": head["fetched_at"], "httpStatus": head["http_status"]},
        "axisScores": axis_scores or None,
        "internalScores": internal_scores or None,
        # Vide tant que `fiv-sourcing videos` n'a pas projeté la série : le
        # brut contient les vidéos depuis toujours, la table qui les rend
        # lisibles est remplie par une passe séparée.
        "videos": videos,
        "catalog": (
            {
                "popularity": float(catalog["popularity"]),
                "adult": catalog["adult"],
                "exportedOn": catalog["exported_on"],
            }
            if catalog
            else None
        ),
    }


# Les rubriques de TMDB, dans l'ordre où elles intéressent : par abonnement
# d'abord, puis gratuit, puis à l'acte. `ads` est le gratuit financé par la
# publicité, que JustWatch distingue du gratuit tout court.
WATCH_KINDS: tuple[tuple[str, str], ...] = (
    ("flatrate", "Par abonnement"),
    ("free", "Gratuit"),
    ("ads", "Gratuit avec publicité"),
    ("rent", "En location"),
    ("buy", "À l'achat"),
)


def _shape_watch(providers: dict[str, Any], countries: list[str], lang: str) -> dict[str, Any]:
    """Où regarder la série, dans le pays de la langue choisie.

    La donnée vient de JustWatch via TMDB, et TMDB impose de citer la source —
    c'est fait dans le front, à côté des logos.
    """
    country = country_of(lang)
    return {
        "country": country,
        # Le lien JustWatch du pays : la page qui fait autorité, et le seul
        # endroit où l'on saura si l'offre a changé depuis la collecte.
        "link": providers.get("link"),
        "offers": [
            {
                "kind": kind,
                "label": label,
                "providers": [
                    {
                        "id": provider.get("provider_id"),
                        "name": provider.get("provider_name"),
                        "logoPath": provider.get("logo_path"),
                    }
                    for provider in sorted(
                        providers.get(kind) or [],
                        key=lambda p: p.get("display_priority") or 0,
                    )
                ],
            }
            for kind, label in WATCH_KINDS
            if providers.get(kind)
        ],
        # Sert à distinguer « aucune plateforme dans ce pays » de « aucune
        # donnée de disponibilité du tout ».
        "countries": countries or [],
    }


def _shape_member(member: dict[str, Any]) -> dict[str, Any]:
    """`aggregate_credits` porte les rôles dans un tableau `roles` ; `credits`
    met le personnage à plat dans `character`. On aplatit les deux pareil."""
    roles = member.get("roles") or []
    character = member.get("character") or (roles[0].get("character") if roles else None)
    episodes = member.get("total_episode_count") or (
        roles[0].get("episode_count") if roles else None
    )
    return {
        "id": member.get("id"),
        "name": member.get("name"),
        "character": character,
        "profilePath": member.get("profile_path"),
        "episodeCount": episodes,
    }


async def fetch_season(
    conn: psycopg.AsyncConnection, work_id: int, season_number: int, lang: str
) -> dict[str, Any] | None:
    """Les épisodes d'une saison, dans la langue demandée.

    Chargée à l'ouverture du volet, pas avec la fiche : une série de huit
    saisons en porte deux cents, et personne ne les lit toutes.

    C'est la seule vue où la langue change vraiment le contenu affiché — les
    synopsis d'épisode n'existent que parce que la collecte a redemandé la
    saison entière dans cette langue.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select r.lang, r.fetched_at, r.http_status,
                   r.payload ->> 'name'      as name,
                   r.payload ->> 'overview'  as overview,
                   nullif(r.payload ->> 'air_date', '') as air_date,
                   r.payload ->> 'poster_path' as poster_path,
                   coalesce(r.payload -> 'episodes', '[]'::jsonb) as episodes
            from raw_source r
            where r.source = %(source)s and r.kind = %(part_kind)s
              and r.source_id = %(id)s and r.lang = %(lang)s
              and r.http_status between 200 and 299
            order by r.fetched_at desc
            limit 1
            """,
            {
                "source": SOURCE,
                "part_kind": KIND_SEASON,
                "id": f"{work_id}/s{season_number}",
                "lang": lang,
            },
        )
        row = await cur.fetchone()

    if row is None:
        return None

    return {
        "lang": row["lang"],
        "fetchedAt": row["fetched_at"],
        "name": row["name"],
        "overview": row["overview"],
        "airDate": row["air_date"],
        "posterPath": row["poster_path"],
        "episodes": [
            {
                "episodeNumber": episode.get("episode_number"),
                "name": episode.get("name"),
                "overview": episode.get("overview"),
                "airDate": episode.get("air_date") or None,
                "runtime": episode.get("runtime"),
                "stillPath": episode.get("still_path"),
                "voteAverage": episode.get("vote_average"),
            }
            for episode in row["episodes"]
        ],
    }


async def genres_disponibles(
    conn: psycopg.AsyncConnection, media: str = DEFAULT_MEDIA
) -> list[dict[str, Any]]:
    """Les genres de l'univers et leur nombre d'œuvres, lus en SQL.

    Le repli de l'agrégation Elasticsearch (voir `search.py`). Un parcours de
    la projection entière : acceptable parce que la liste se charge une fois
    par univers, pas à chaque page — et parce qu'ES fait le travail dès qu'il
    répond.
    """
    univers = MEDIA[media]
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql.SQL(
                """
                select g ->> 'name' as name, count(*) as count
                from admin.{vue} v,
                     jsonb_array_elements(coalesce(v.genres, '[]'::jsonb)) g
                where nullif(btrim(g ->> 'name'), '') is not null
                group by 1
                order by 2 desc, 1
                """
            ).format(vue=sql.Identifier(univers.card_view))
        )
        return [{"name": row["name"], "count": int(row["count"])} for row in await cur.fetchall()]


async def refresh_cards(conn: psycopg.AsyncConnection, univers: str | None = None) -> int:
    """Recalcule les projections et renvoie le nombre de vignettes.

    **Toutes** par défaut, et non celle de l'univers courant : le bouton de
    l'admin n'a pas d'univers, et un rafraîchissement qui n'en couvrirait
    qu'un laisserait l'autre en retard sans que rien ne le dise. `univers`
    restreint depuis la ligne de commande — recalculer le million de vignettes
    de `movie_card` parce que deux livres ont été crawlés serait du gâchis.

    `concurrently` : le rafraîchissement ne prend pas de verrou exclusif, donc
    la grille reste consultable pendant qu'il tourne. Il exige l'index unique
    posé par la migration, et refuse de s'exécuter sur une vue jamais peuplée —
    d'où le repli sur un rafraîchissement bloquant au tout premier appel.
    """
    total = 0
    for media in MEDIA.values():
        if not media.disponible or (univers is not None and media.univers != univers):
            continue
        vue = sql.Identifier("admin", media.card_view)
        try:
            await conn.execute(sql.SQL("refresh materialized view concurrently {}").format(vue))
        except psycopg.errors.ObjectNotInPrerequisiteState:
            await conn.execute(sql.SQL("refresh materialized view {}").format(vue))

        async with conn.cursor() as cur:
            await cur.execute(sql.SQL("select count(*) from {}").format(vue))
            row = await cur.fetchone()
        total += int(row[0]) if row else 0
    return total


async def cards_state(conn: psycopg.AsyncConnection, media: str = DEFAULT_MEDIA) -> dict[str, Any]:
    """De quoi dire au front si la projection est vide, en retard, ou à jour.

    Le point délicat est le sens de « en retard ». Il se mesurait contre
    `fetch_state`, et c'était faux : cette table dit ce que la collecte a
    *tenté et réussi*, pas ce qu'elle a *stocké*. Les deux peuvent diverger —
    observé en production, 226 séries marquées « succès HTTP 200 » sans aucune
    ligne dans `raw_source` — et le bandeau restait alors allumé pour toujours,
    puisqu'aucun rafraîchissement ne pouvait projeter des séries dont le brut
    n'existe pas.

    Le compte se fait donc contre **ce dont la projection est faite** : les
    identifiants distincts que la vue matérialisée retiendrait si on la
    recalculait maintenant. Par construction, l'égalité signifie « à jour », et
    aucune incohérence en amont ne peut plus allumer le bandeau à tort.
    """
    univers = MEDIA[media]
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql.SQL("select count(*) as total, max(fetched_at) as last_at from {}").format(
                sql.Identifier("admin", univers.card_view)
            )
        )
        projection = await cur.fetchone() or {}

        # Exactement le filtre de `002_admin_cards.sql`. Parcours d'index seul
        # grâce à `raw_source_latest_idx (source, kind, source_id, …)`, mais ce
        # `count(distinct)` reste le poste le plus cher de cette réponse : il
        # justifierait un cache si la page devenait lente.
        await cur.execute(
            """
            select count(distinct source_id) as total
            from raw_source
            where source = %(source)s and kind = %(kind)s
              and http_status between 200 and 299 and payload is not null
            """,
            # La fiche d'un livre est le lookup Wikidata du crawler : c'est
            # `media.raw_source` qui dit où compter, pas la constante TMDB.
            {"source": univers.raw_source, "kind": univers.kind},
        )
        projetables = await cur.fetchone() or {}

        # Gardé pour l'affichage, et parce que l'écart entre les deux est en soi
        # un signal : une collecte qui se dit réussie sans rien avoir stocké.
        await cur.execute(
            """
            select count(*) as total
            from fetch_state
            where source = %(source)s and kind = %(kind)s and last_success_at is not null
            """,
            {"source": univers.raw_source, "kind": univers.kind},
        )
        collected = await cur.fetchone() or {}

    total = int(projection.get("total") or 0)
    disponibles = int(projetables.get("total") or 0)
    return {
        "projected": total,
        "collected": int(collected.get("total") or 0),
        "projectable": disponibles,
        # Ce qu'un rafraîchissement ajouterait — donc ce que le bouton sert à
        # faire, et rien d'autre.
        "pending": max(0, disponibles - total),
        "stale": disponibles > total,
        "lastAt": projection.get("last_at"),
    }


# Combien de texte la fiche rapporte par source enrichie.
#
# Un article de Wikipédia pèse couramment cent kilooctets ; cinq langues en
# feraient un demi-mégaoctet dans une fenêtre que personne ne lira en entier.
# On en montre le début — de quoi juger de la matière — et le compte exact de
# caractères dit ce qu'il y a derrière. Le texte complet se lit chez la source,
# dont l'URL est fournie.
EXTRAIT_CHARS = 1500


async def fetch_actualite(
    conn: psycopg.AsyncConnection, work_id: int, media: str = DEFAULT_MEDIA
) -> dict[str, Any]:
    """L'actualité d'une œuvre : les événements datés que la dérivation a liés.

    Liste vide quand il n'y a rien, jamais un 404 : une œuvre sans actualité
    est l'état normal du catalogue — les diffs ne parlent que des fiches
    recollectées, et le RSS n'arrose que la tête. Une erreur ferait croire à
    une panne.

    `media` qualifie l'identifiant, comme partout : sans lui, le film 550
    lirait l'actualité de la série 550.
    """
    univers = MEDIA[media].univers
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select a.type_evenement, a.survenu_le, a.titre, a.url, a.editeur,
                   a.confiance_liaison, a.derive_at
            from sourcing.actualite a
            join sourcing.oeuvre o on o.id = a.oeuvre_id
            where o.univers = %(univers)s and o.id_tmdb = %(id)s
            order by a.survenu_le desc, a.derive_at desc
            limit 50
            """,
            {"univers": univers, "id": work_id},
        )
        lignes = await cur.fetchall()
    return {
        "id": work_id,
        "evenements": [
            {
                "type": ligne["type_evenement"],
                "survenuLe": ligne["survenu_le"].isoformat(),
                "titre": ligne["titre"],
                "url": ligne["url"],
                "editeur": ligne["editeur"],
                # null = liaison certaine (diff interne) — le front distingue
                # « fait maison » de « presse liée par matching ».
                "confiance": ligne["confiance_liaison"],
            }
            for ligne in lignes
        ],
    }


async def fetch_rich(
    conn: psycopg.AsyncConnection, work_id: int, media: str = DEFAULT_MEDIA
) -> dict[str, Any]:
    """L'enrichissement d'une œuvre, groupé par source.

    `riche_source` porte une ligne par (œuvre, source, langue) : Wikipédia en
    cinq langues fait cinq lignes, Wikidata et TVmaze une seule chacune (leur
    contenu n'est pas linguistique). Le groupement par source est donc celui de
    la lecture : « qu'apporte Wikipédia ? », pas « qu'y a-t-il en français ? ».

    Les `facts` sont **canoniques** — mêmes clés quelle que soit la source
    (`titre`, `annee`, `statut`, `pays`, `langues`, `lieux`, `diffuseur`,
    `calendrier`, `episodes`, `ids`). C'est la promesse de `normalize.py` côté
    sourcing, et c'est ce qui permet de les afficher sans savoir d'où ils
    viennent.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        # Le pivot d'identité, **s'il porte quelque chose**.
        #
        # La nuance date du lot 12. Avant, le pivot naissait à l'enrichissement
        # et son absence disait donc « jamais enrichie ». Il naît maintenant à
        # la collecte, comme identité de l'œuvre : toute série collectée en a
        # un, et sa seule présence ne dit plus rien. Ce sont les identifiants
        # externes qui portent l'information — ils ne peuvent venir que de
        # Wikidata, d'IMDb ou de TVmaze, donc de l'enrichissement.
        #
        # C'est aussi ce qu'attend le panneau : il n'affiche que des liens
        # externes, et un bloc d'identité vide serait pire qu'absent.
        await cur.execute(
            sql.SQL(
                """
                select id, univers, wikidata_qid, imdb_id, tvmaze_id, id_openlibrary,
                       titre, annee
                from oeuvre where univers = %(univers)s and {cle} = %(id)s
                order by id limit 1
                """
            ).format(
                # Un livre est désigné par son pivot — il n'a pas d'id TMDB.
                cle=sql.SQL("id") if MEDIA[media].pivot_card else sql.SQL("id_tmdb")
            ),
            {"id": work_id, "univers": MEDIA[media].univers},
        )
        pivot = await cur.fetchone()
        oeuvre = (
            pivot
            if pivot
            and any(
                pivot[cle] for cle in ("wikidata_qid", "imdb_id", "tvmaze_id", "id_openlibrary")
            )
            else None
        )

        # Par le pivot quand il existe — c'est le lien qui fait foi, et il
        # couvre les lignes dont l'`id_tmdb` est nul. Le pivot ici, pas
        # `oeuvre` : celui-ci est filtré pour l'affichage (identifiants
        # externes), la jointure ne l'est pas.
        #
        # ⚠️ Le repli par `id_tmdb` seul ne vaut que pour les séries. C'est un
        # reste d'avant le lot 7, quand `riche_source` n'avait pas de pivot, et
        # cette colonne ne porte pas d'univers : l'employer sur un film
        # rendrait l'enrichissement de la série qui porte le même numéro. Le
        # cas s'est produit — le film 557 affichait les sources de *Camp
        # Lazlo*. Un film sans pivot n'a donc pas de repli, et c'est correct :
        # aucun enrichissement film n'a jamais été écrit sans lui.
        await cur.execute(
            sql.SQL(
                """
                select source, lang, source_id, url, resolved_by, fetched_at,
                       content_chars, media_count, facts, media,
                       left(content, %(extrait)s) as extrait
                from riche_source
                where {lien}
                order by source, lang, source_id
                """
            ).format(
                lien=(
                    sql.SQL("oeuvre_id = %(oeuvre)s")
                    if pivot
                    else sql.SQL("id_tmdb = %(id)s")
                    if media == DEFAULT_MEDIA
                    else sql.SQL("false")
                )
            ),
            {"id": work_id, "oeuvre": pivot["id"] if pivot else None, "extrait": EXTRAIT_CHARS},
        )
        lignes = await cur.fetchall()

    groupes: dict[str, list[dict[str, Any]]] = {}
    for ligne in lignes:
        caracteres = int(ligne["content_chars"] or 0)
        extrait = ligne["extrait"] or ""
        groupes.setdefault(ligne["source"], []).append(
            {
                # La langue de requête, vide pour les sources qui n'en ont pas
                # (Wikidata, TVmaze) : `''` plutôt que null, c'est la valeur par
                # défaut de la colonne et le front n'a pas à distinguer.
                "lang": ligne["lang"] or "",
                "sourceId": ligne["source_id"],
                "url": ligne["url"],
                # Par quel chemin le raccordement a réussi (`sitelink`,
                # `imdb`…). Ce n'est pas un détail de plomberie : un
                # rattachement par titre est moins sûr qu'un rattachement par
                # identifiant, et c'est ici qu'on peut en douter.
                "resolvedBy": ligne["resolved_by"],
                "fetchedAt": ligne["fetched_at"],
                "contentChars": caracteres,
                "extract": extrait,
                # Le front n'a pas à recalculer la troncature : elle dépend
                # d'une constante d'ici.
                "truncated": caracteres > len(extrait),
                "facts": ligne["facts"] or {},
                "media": ligne["media"] or [],
                "mediaCount": int(ligne["media_count"] or 0),
            }
        )

    return {
        "workId": work_id,
        "oeuvre": {
            "id": oeuvre["id"],
            "univers": oeuvre["univers"],
            "titre": oeuvre["titre"],
            "annee": oeuvre["annee"],
            "wikidataQid": oeuvre["wikidata_qid"],
            "imdbId": oeuvre["imdb_id"],
            "tvmazeId": oeuvre["tvmaze_id"],
            "openlibraryId": oeuvre["id_openlibrary"],
        }
        if oeuvre
        else None,
        "sources": [
            {
                "source": source,
                "entries": entrees,
                "chars": sum(entree["contentChars"] for entree in entrees),
                "media": sum(entree["mediaCount"] for entree in entrees),
            }
            for source, entrees in sorted(groupes.items())
        ],
    }
