"""La fiche détaillée d'une œuvre — ce que la modale du composant affiche.

La carte sert à reconnaître et à classer ; la fiche sert à **décider**. D'où
ce qu'elle porte en plus : le synopsis entier, la grande image de fond, les
saisons d'une série, ceux qui la font avec leur photo.

Deux chemins, comme partout dans le dépôt :

* **séries et films** — le dernier brut TMDB, relu directement. Pas la
  projection de vignettes : elle est faite pour trier mille cartes, pas pour
  décrire une œuvre, et ce qui l'intéresse (distribution, saisons) n'y est
  pas. Les tableaux volumineux sont tronqués **en SQL** — on ne transporte
  pas six cents crédits pour en afficher douze ;
* **livres** — `riche_source`, comme leur projection : Wikidata pour les
  faits et les auteurs, Wikipédia pour le texte long, Open Library pour la
  couverture. Un livre n'a ni saison ni distribution, et la forme rendue le
  dit par des listes vides plutôt que par des clés absentes : le front garde
  une seule modale.

Une limite assumée, notée ici pour qu'elle ne se redécouvre pas : le texte
rendu est celui du brut, collecté en `fr-FR`. Les traductions dorment dans le
payload (l'admin sait les lire, `catalog.fetch_work`) et le site public ne
les exploite pas encore — il n'a pas de sélecteur de langue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fiv_webapp.univers import Univers

SOURCE = "tmdb"

# Ce qu'on montre de la distribution. Douze, parce que c'est ce qu'une modale
# affiche sans faire défiler trois écrans — et parce qu'au-delà du générique
# de tête, un nom n'aide plus personne à décider.
DISTRIBUTION_MAX = 12

# Les réalisateurs et créateurs : une poignée suffit, et une série de longue
# durée en crédite quatre-vingts dont soixante ont dirigé un épisode.
REALISATION_MAX = 6

# Le `kind` de brut à relire, par univers interne. Les livres n'en ont pas —
# ils passent par l'autre chemin.
KIND_TMDB = {"series": "tv", "movies": "movie"}

# Le brut d'une saison : collecté à part, une ligne par saison ET par langue
# (`source_id` = « 1399/s1 »). C'est ce qui permet de ne charger les épisodes
# qu'au dépliement — une série de huit saisons en porte deux cents.
KIND_SAISON = "tv_season"

# La langue préférée du site. Le repli sur une autre langue collectée est
# explicite dans la requête : mieux vaut des épisodes en anglais qu'un
# accordéon qui s'ouvre sur du vide.
LANGUE_DEFAUT = "fr-FR"


@dataclass(frozen=True, slots=True)
class Personne:
    """Quelqu'un qui fait l'œuvre : un acteur avec son rôle, un réalisateur,
    un auteur."""

    nom: str
    role: str | None = None
    photo: str | None = None
    episodes: int | None = None

    def publique(self) -> dict[str, Any]:
        return {
            "nom": self.nom,
            "role": self.role,
            "photo": self.photo,
            "episodes": self.episodes,
        }


@dataclass(frozen=True, slots=True)
class Saison:
    """Une saison, telle que la fiche TMDB la porte."""

    numero: int
    nom: str | None
    annee: int | None
    episodes: int | None
    affiche: str | None
    synopsis: str | None

    def publique(self) -> dict[str, Any]:
        return {
            "numero": self.numero,
            "nom": self.nom,
            "annee": self.annee,
            "episodes": self.episodes,
            "affiche": self.affiche,
            "synopsis": self.synopsis,
        }


@dataclass(frozen=True, slots=True)
class Episode:
    """Un épisode, tel que le brut de sa saison le porte."""

    numero: int
    titre: str | None
    synopsis: str | None
    diffusion: str | None
    duree: int | None
    image: str | None
    note: float | None

    def publique(self) -> dict[str, Any]:
        return {
            "numero": self.numero,
            "titre": self.titre,
            "synopsis": self.synopsis,
            "diffusion": self.diffusion,
            "duree": self.duree,
            "image": self.image,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Fiche:
    """L'œuvre en grand. `oeuvre_id` est l'identité que les boutons de
    classement manipulent — la modale les garde, c'est tout l'intérêt d'y
    arriver depuis une carte."""

    id: int
    oeuvre_id: int | None
    univers: str
    titre: str | None
    titre_original: str | None
    accroche: str | None = None
    annee: int | None = None
    synopsis: str | None = None
    affiche: str | None = None
    fond: str | None = None
    genres: list[str] = field(default_factory=list)
    note: float | None = None
    votes: int | None = None
    statut: str | None = None
    pays: list[str] = field(default_factory=list)
    langue: str | None = None
    duree_saisons: int | None = None
    duree_episodes: int | None = None
    distribution: list[Personne] = field(default_factory=list)
    realisation: list[Personne] = field(default_factory=list)
    saisons: list[Saison] = field(default_factory=list)

    def publique(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "oeuvreId": self.oeuvre_id,
            "univers": self.univers,
            "titre": self.titre,
            "titreOriginal": self.titre_original,
            "accroche": self.accroche,
            "annee": self.annee,
            "synopsis": self.synopsis,
            "affiche": self.affiche,
            "fond": self.fond,
            "genres": self.genres,
            "note": self.note,
            "votes": self.votes,
            "statut": self.statut,
            "pays": self.pays,
            "langue": self.langue,
            "saisonsTotal": self.duree_saisons,
            "episodesTotal": self.duree_episodes,
            "distribution": [personne.publique() for personne in self.distribution],
            "realisation": [personne.publique() for personne in self.realisation],
            "saisons": [saison.publique() for saison in self.saisons],
        }


# Le brut d'une série ou d'un film, réduit à ce que la modale montre. Les
# crédits sont tronqués en SQL : `aggregate_credits` consolide toute la série,
# `credits` ne donne que la première saison — on prend le premier des deux,
# comme le fait l'admin.
_FICHE_TMDB = """
    select coalesce(r.payload ->> 'name', r.payload ->> 'title')            as titre,
           coalesce(r.payload ->> 'original_name',
                    r.payload ->> 'original_title')                         as titre_original,
           nullif(btrim(coalesce(r.payload ->> 'overview', '')), '')        as synopsis,
           nullif(btrim(coalesce(r.payload ->> 'tagline', '')), '')         as accroche,
           r.payload ->> 'poster_path'                                      as affiche,
           r.payload ->> 'backdrop_path'                                    as fond,
           r.payload ->> 'status'                                           as statut,
           r.payload ->> 'original_language'                                as langue,
           nullif(r.payload ->> 'first_air_date', '')                       as sortie_tv,
           nullif(r.payload ->> 'release_date', '')                         as sortie_film,
           nullif(r.payload ->> 'number_of_seasons', '')::int               as saisons_total,
           nullif(r.payload ->> 'number_of_episodes', '')::int              as episodes_total,
           nullif(r.payload ->> 'vote_average', '')::real                   as note,
           nullif(r.payload ->> 'vote_count', '')::int                      as votes,
           coalesce(r.payload -> 'genres', '[]'::jsonb)                     as genres,
           coalesce(r.payload -> 'origin_country', '[]'::jsonb)             as pays,
           coalesce(r.payload -> 'seasons', '[]'::jsonb)                    as saisons,
           coalesce(r.payload -> 'created_by', '[]'::jsonb)                 as creation,
           coalesce(
               nullif(jsonb_path_query_array(r.payload, %(p_cast_agg)s::jsonpath), '[]'::jsonb),
               jsonb_path_query_array(r.payload, %(p_cast)s::jsonpath)
           )                                                                as distribution,
           jsonb_path_query_array(r.payload, %(p_crew)s::jsonpath)          as realisation
    from raw_source r
    where r.source = %(source)s and r.kind = %(kind)s and r.source_id = %(id)s
      and r.http_status between 200 and 299 and r.payload is not null
    order by r.fetched_at desc
    limit 1
"""

# Le pivot d'une œuvre TMDB : l'identité que les boutons manipulent. Séparé de
# la fiche parce qu'il vient d'une autre table, et qu'une œuvre peut avoir un
# brut sans pivot (collecte partielle) — la modale s'affiche alors sans
# permettre de classer, plutôt que de ne pas s'ouvrir.
_PIVOT = """
    select id from oeuvre where univers = %(univers)s and id_tmdb = %(id)s limit 1
"""

# Les épisodes d'une saison. Le tri de langue est explicite : la langue du
# site d'abord, n'importe quelle autre collectée ensuite — un accordéon qui
# s'ouvre sur du vide serait pire qu'un titre en anglais.
_EPISODES = """
    select r.lang,
           coalesce(r.payload -> 'episodes', '[]'::jsonb) as episodes
    from raw_source r
    where r.source = %(source)s and r.kind = %(kind)s
      and r.source_id = %(id)s
      and r.http_status between 200 and 299 and r.payload is not null
    order by (r.lang = %(langue)s) desc, r.fetched_at desc
    limit 1
"""

# Un livre : le pivot, ses faits Wikidata, son article Wikipédia le plus
# fourni (préférence française), sa couverture Open Library.
_FICHE_LIVRE = """
    select o.id,
           o.titre,
           o.annee,
           wd.facts                                as faits,
           wp.content                              as article,
           lv.name                                 as titre_projete,
           lv.overview                             as synopsis_projete,
           lv.poster_path                          as affiche,
           lv.first_air_date                       as sortie
    from oeuvre o
    left join admin.livre_card lv on lv.id = o.id
    left join lateral (
        select r.facts
        from riche_source r
        where r.oeuvre_id = o.id and r.source = 'wikidata'
        limit 1
    ) wd on true
    left join lateral (
        select r.content
        from riche_source r
        where r.oeuvre_id = o.id and r.source = 'wikipedia'
          and nullif(btrim(r.content), '') is not null
        order by array_position(array['fr', 'en', 'es', 'ar'], r.lang) nulls last,
                 r.content_chars desc
        limit 1
    ) wp on true
    where o.univers = 'livres' and o.id = %(id)s
"""


class Fiches:
    """La lecture d'une fiche, par univers. Une classe plutôt que des
    fonctions libres : les deux chemins partagent leur mise en forme, et
    c'est elle qui garantit au front une seule modale."""

    async def pour(
        self, conn: psycopg.AsyncConnection, univers: Univers, identifiant: int
    ) -> Fiche | None:
        if univers.pivot_card:
            return await self._livre(conn, univers, identifiant)
        return await self._tmdb(conn, univers, identifiant)

    async def episodes(
        self, conn: psycopg.AsyncConnection, identifiant: int, numero: int
    ) -> list[Episode]:
        """Les épisodes d'une saison, chargés **au dépliement** et pas avec la
        fiche : une série de huit saisons en porte deux cents, et personne ne
        les lit toutes.

        Une saison jamais collectée rend une liste vide — pas une erreur : le
        cas est banal (la collecte procède par langue et par lot) et
        l'accordéon sait dire « pas encore collectés ».
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                _EPISODES,
                {
                    "source": SOURCE,
                    "kind": KIND_SAISON,
                    "id": f"{identifiant}/s{numero}",
                    "langue": LANGUE_DEFAUT,
                },
            )
            ligne = await cur.fetchone()
        if ligne is None:
            return []
        return self._episodes(ligne.get("episodes"))

    def _episodes(self, episodes: list[dict[str, Any]] | None) -> list[Episode]:
        """Les épisodes, dans l'ordre de diffusion. Un épisode sans numéro
        n'en est pas un — il n'aurait pas de place dans la liste."""
        retenus: list[Episode] = []
        for episode in episodes or []:
            numero = episode.get("episode_number")
            if numero is None:
                continue
            note = episode.get("vote_average")
            retenus.append(
                Episode(
                    numero=int(numero),
                    titre=(episode.get("name") or "").strip() or None,
                    synopsis=(episode.get("overview") or "").strip() or None,
                    diffusion=episode.get("air_date") or None,
                    duree=episode.get("runtime"),
                    image=episode.get("still_path"),
                    note=round(float(note), 1) if note else None,
                )
            )
        return sorted(retenus, key=lambda episode: episode.numero)

    # --- séries et films ----------------------------------------------------

    async def _tmdb(
        self, conn: psycopg.AsyncConnection, univers: Univers, identifiant: int
    ) -> Fiche | None:
        parametres = self._parametres_credits(univers)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                _FICHE_TMDB,
                {
                    "source": SOURCE,
                    "kind": KIND_TMDB[univers.interne],
                    "id": str(identifiant),
                    **parametres,
                },
            )
            ligne = await cur.fetchone()
            if ligne is None:
                return None
            await cur.execute(_PIVOT, {"univers": univers.interne, "id": identifiant})
            pivot = await cur.fetchone()

        sortie = ligne.get("sortie_tv") or ligne.get("sortie_film")
        note = ligne.get("note")
        return Fiche(
            id=identifiant,
            oeuvre_id=pivot["id"] if pivot else None,
            univers=univers.slug,
            titre=ligne.get("titre"),
            titre_original=ligne.get("titre_original"),
            accroche=ligne.get("accroche"),
            annee=int(sortie[:4]) if sortie else None,
            synopsis=ligne.get("synopsis"),
            affiche=ligne.get("affiche"),
            fond=ligne.get("fond"),
            genres=[
                genre["name"]
                for genre in ligne.get("genres") or []
                if (genre.get("name") or "").strip()
            ],
            note=round(float(note), 1) if note else None,
            votes=ligne.get("votes"),
            statut=ligne.get("statut"),
            pays=list(ligne.get("pays") or []),
            langue=ligne.get("langue"),
            duree_saisons=ligne.get("saisons_total"),
            duree_episodes=ligne.get("episodes_total"),
            distribution=self._distribution(ligne.get("distribution")),
            realisation=self._realisation(ligne.get("realisation"), ligne.get("creation")),
            saisons=self._saisons(ligne.get("saisons")),
        )

    def _parametres_credits(self, univers: Univers) -> dict[str, str]:
        """Les chemins jsonb des crédits — ils divergent par univers, comme au
        graphe et à l'indexation : une série consolide dans
        `aggregate_credits` et range ses métiers dans `jobs`, un film n'a que
        `credits`, un métier par ligne."""
        if univers.interne == "series":
            return {
                "p_cast_agg": f"$.aggregate_credits.cast[0 to {DISTRIBUTION_MAX - 1}]",
                "p_cast": f"$.credits.cast[0 to {DISTRIBUTION_MAX - 1}]",
                "p_crew": '$.aggregate_credits.crew[*] ? (@.department == "Directing")',
            }
        return {
            "p_cast_agg": f"$.credits.cast[0 to {DISTRIBUTION_MAX - 1}]",
            "p_cast": f"$.credits.cast[0 to {DISTRIBUTION_MAX - 1}]",
            "p_crew": '$.credits.crew[*] ? (@.job == "Director")',
        }

    def _distribution(self, membres: list[dict[str, Any]] | None) -> list[Personne]:
        """Les acteurs, rôle compris. `aggregate_credits` porte les rôles dans
        un tableau `roles`, `credits` met le personnage à plat : on aplatit
        les deux pareil."""
        retenus: list[Personne] = []
        for membre in membres or []:
            nom = (membre.get("name") or "").strip()
            if not nom:
                continue
            roles = membre.get("roles") or []
            personnage = membre.get("character") or (roles[0].get("character") if roles else None)
            episodes = membre.get("total_episode_count") or (
                roles[0].get("episode_count") if roles else None
            )
            retenus.append(
                Personne(
                    nom=nom,
                    role=(personnage or "").strip() or None,
                    photo=membre.get("profile_path"),
                    episodes=episodes,
                )
            )
        return retenus[:DISTRIBUTION_MAX]

    def _realisation(
        self, equipe: list[dict[str, Any]] | None, creation: list[dict[str, Any]] | None
    ) -> list[Personne]:
        """Réalisateurs et créateurs, dédupliqués et rangés par présence.

        Côté série, le filtre jsonpath a laissé passer tout le département
        « Directing » : c'est ici qu'on ne garde que les réalisateurs, le
        tableau `jobs` n'étant pas filtrable proprement en jsonpath.
        """
        createurs: dict[str, Personne] = {}
        par_nom: dict[str, Personne] = {}
        for membre in creation or []:
            nom = (membre.get("name") or "").strip()
            if nom:
                createurs[nom] = Personne(
                    nom=nom, role="Création", photo=membre.get("profile_path")
                )
        par_nom.update(createurs)
        for membre in equipe or []:
            nom = (membre.get("name") or "").strip()
            if not nom or nom in par_nom:
                continue
            metiers = membre.get("jobs") or []
            if metiers:
                if not any(metier.get("job") == "Director" for metier in metiers):
                    continue
                episodes = membre.get("total_episode_count") or metiers[0].get("episode_count")
            elif membre.get("job") not in (None, "Director"):
                continue
            else:
                episodes = None
            par_nom[nom] = Personne(
                nom=nom,
                role="Réalisation",
                photo=membre.get("profile_path"),
                episodes=episodes,
            )
        # Les créateurs d'abord, quel que soit leur compte d'épisodes : ils
        # signent la série entière, là où un réalisateur en signe sept
        # épisodes. Trier tout le monde sur le nombre d'épisodes ferait passer
        # le second devant les premiers — vu sur Game of Thrones, où Alan
        # Taylor doublait Benioff et Weiss.
        retenus = sorted(
            par_nom.values(),
            key=lambda personne: (personne.nom not in createurs, -(personne.episodes or 0)),
        )
        return retenus[:REALISATION_MAX]

    def _saisons(self, saisons: list[dict[str, Any]] | None) -> list[Saison]:
        """Les saisons, dans l'ordre. La saison 0 — les « spéciaux » de
        TMDB — n'est pas montrée : elle n'est pas une étape du récit, et
        l'afficher en tête ferait commencer la série par ses bonus."""
        retenues: list[Saison] = []
        for saison in saisons or []:
            numero = saison.get("season_number")
            if numero is None or int(numero) == 0:
                continue
            sortie = saison.get("air_date")
            retenues.append(
                Saison(
                    numero=int(numero),
                    nom=(saison.get("name") or "").strip() or None,
                    annee=int(sortie[:4]) if sortie else None,
                    episodes=saison.get("episode_count"),
                    affiche=saison.get("poster_path"),
                    synopsis=(saison.get("overview") or "").strip() or None,
                )
            )
        return sorted(retenues, key=lambda saison: saison.numero)

    # --- livres --------------------------------------------------------------

    def _chapeau(self, article: str | None) -> str | None:
        """Le chapeau d'un article Wikipédia : tout ce qui précède sa première
        section.

        Le texte collecté est l'article ENTIER — sections, bibliographie,
        « Liens externes », listes d'URL. Le chapeau, lui, est exactement ce
        qu'on veut ici : deux ou trois paragraphes qui disent de quoi il
        s'agit et donnent envie. La coupe se fait sur les titres de section
        (`== … ==`), qui sont la seule structure fiable du format.
        """
        if not article:
            return None
        garde: list[str] = []
        for ligne in article.splitlines():
            if ligne.lstrip().startswith("=="):
                break
            garde.append(ligne)
        return "\n".join(garde).strip() or None

    async def _livre(
        self, conn: psycopg.AsyncConnection, univers: Univers, identifiant: int
    ) -> Fiche | None:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_FICHE_LIVRE, {"id": identifiant})
            ligne = await cur.fetchone()
        if ligne is None:
            return None

        faits = ligne.get("faits") or {}
        sortie = ligne.get("sortie")
        # L'article Wikipédia d'abord — c'est le texte qui donne envie de
        # lire ; la description Open Library projetée en repli. L'article est
        # coupé à son chapeau : la suite est une encyclopédie, pas un
        # argumentaire (voir `_chapeau`).
        synopsis = self._chapeau(ligne.get("article")) or ligne.get("synopsis_projete")
        return Fiche(
            id=ligne["id"],
            # Un livre EST désigné par son pivot : la vignette et l'identité
            # de classement sont la même clé.
            oeuvre_id=ligne["id"],
            univers=univers.slug,
            titre=ligne.get("titre_projete") or ligne.get("titre"),
            titre_original=ligne.get("titre"),
            annee=(sortie.year if sortie else ligne.get("annee")),
            synopsis=(synopsis or "").strip() or None,
            affiche=ligne.get("affiche"),
            genres=list(faits.get("genres") or []),
            pays=list(faits.get("pays") or []),
            langue=(faits.get("langues") or [None])[0],
            realisation=[
                Personne(nom=auteur["nom"], role="Auteur")
                for auteur in faits.get("auteurs") or []
                if (auteur.get("nom") or "").strip()
            ],
        )
