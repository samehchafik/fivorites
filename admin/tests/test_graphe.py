"""Tests du graphe : les parties pures, et le contrat du vocabulaire.

Aucun Neo4j ici. Ce qui se teste sans serveur, et qui est justement ce qui
casserait en silence : la forme du nœud (une propriété absente doit partir à
`null`, pas disparaître), l'ordre des coordonnées de l'empreinte, le pliage du
Cypher sur une ligne — la Query API refuse les retours à la ligne littéraux, et
un commentaire `//` mal retiré avalerait la moitié d'une instruction sans
qu'aucune erreur ne le dise.

Le préfixe `Fiv` est vérifié lui aussi. Il n'a l'air de rien, mais c'est la
seule frontière entre nos données et tout ce qui pourrait un jour partager
l'instance : un label oublié se remarquerait le jour où il est trop tard.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from conftest import requires_db
from fiv_admin.graphe import (
    _EXTRACTION_MEMBRES,
    _PIVOTS_CHANGES,
    DISTRIBUTION_MAX,
    LABEL_ACTEUR,
    LABEL_CREATEUR,
    LABEL_DU_ROLE,
    LABEL_MEMBRE,
    LABEL_OEUVRE,
    LABEL_PERSONNE,
    LABEL_REALISATEUR,
    LABEL_UNIVERS,
    PREFIXE,
    REALISATEURS_MAX,
    REL_CITE,
    REL_CREE,
    REL_GENRE,
    REL_JOUE,
    REL_REALISE,
    RELATIONS_PROJETEES,
    Graphe,
    GrapheErreur,
    construire_oeuvre,
    lot_cypher,
    lot_membres_cypher,
    normaliser,
    parametres_extraction,
    requete_extraction,
    schema_cypher,
    synchroniser,
    une_ligne,
)
from fiv_admin.media import MEDIA


def _ligne(**champs: Any) -> dict[str, Any]:
    """Une ligne d'extraction : tout à `None` sauf ce que le test regarde."""
    base: dict[str, Any] = dict.fromkeys(
        (
            "oeuvre_id",
            "id_tmdb",
            "titre",
            "titre_original",
            "annee",
            "date_sortie",
            "langue",
            "statut",
            "affiche",
            "votes",
            "note",
            "genres",
            "distribution",
            "realisation",
            "creation",
            "empreinte",
            "empreinte_source",
            "bareme",
        )
    )
    base["oeuvre_id"] = 42
    base.update(champs)
    return base


class TestVocabulaire:
    def test_tout_est_prefixe(self) -> None:
        labels = [
            LABEL_OEUVRE,
            LABEL_PERSONNE,
            LABEL_ACTEUR,
            LABEL_REALISATEUR,
            LABEL_CREATEUR,
            *LABEL_UNIVERS.values(),
        ]
        assert all(label.startswith(PREFIXE) for label in labels)
        assert all(rel.startswith(PREFIXE.upper() + "_") for rel in RELATIONS_PROJETEES)

    def test_le_membre_est_prefixe_et_distinct_de_la_personne(self) -> None:
        # `:FivPersonne` est l'acteur ou le réalisateur ; `:FivMembre` est
        # quelqu'un qui a un compte. Les confondre ferait apparaître un
        # abonné dans un générique.
        assert LABEL_MEMBRE.startswith(PREFIXE)
        assert LABEL_MEMBRE != LABEL_PERSONNE
        assert REL_CITE.startswith(PREFIXE.upper() + "_")

    def test_chaque_univers_a_son_label(self) -> None:
        # Un univers servi par l'admin sans label ici ferait des nœuds sans
        # second label, donc invisibles à toute requête par univers.
        for media in MEDIA.values():
            if media.catalog_table is not None:
                assert media.univers in LABEL_UNIVERS


class TestMembres:
    """La projection des membres, et la seule chose qui compte vraiment : que
    rien d'identifiant n'y entre."""

    IDENTIFIANTS = ("pseudo", "email", "mail", "nom", "v1", "identifiant")

    def test_le_noeud_ne_porte_que_son_identifiant(self) -> None:
        # Le test qui a une raison d'exister : le jour où quelqu'un ajoutera
        # « juste le pseudo, pour déboguer », il échouera. Un graphe qui ne
        # porte pas une donnée ne peut pas la laisser fuiter.
        cypher = " ".join(lot_membres_cypher()).lower()
        for mot in self.IDENTIFIANTS:
            assert mot not in cypher, f"le Cypher des membres mentionne « {mot} »"
        assert "membreid" in cypher

    def test_la_requete_ne_lit_aucune_colonne_identifiante(self) -> None:
        sql = _EXTRACTION_MEMBRES.lower()
        for mot in ("pseudo", "email", "profil", "v1_id"):
            assert mot not in sql, f"l'extraction lit « {mot} »"

    def test_les_citations_ne_creent_jamais_une_oeuvre(self) -> None:
        """`MATCH` sur l'œuvre, jamais `MERGE`.

        Un `MERGE` fabriquerait un nœud portant un `oeuvreId` et rien d'autre,
        impossible à distinguer d'une œuvre réelle mal projetée. La citation
        attend son œuvre, elle ne l'invente pas.
        """
        _, citations = lot_membres_cypher()
        assert f"MATCH (o:{LABEL_OEUVRE}" in citations
        assert f"MERGE (o:{LABEL_OEUVRE}" not in citations

    def test_le_membre_est_cree_puis_detache(self) -> None:
        """Deux instructions, et la première efface les citations du membre.

        Sans cet effacement, un top raccourci garderait ses anciennes
        positions : `MERGE` réécrit ce qu'on lui donne, il n'enlève rien.
        """
        membres, _ = lot_membres_cypher()
        assert f"MERGE (p:{LABEL_MEMBRE}" in membres
        assert "DELETE perimee" in membres
        assert REL_CITE in membres

    def test_le_rang_voyage_sur_la_relation(self) -> None:
        # Le rang est le seul degré de force que la V1 donne : hors de la
        # relation, il n'existe nulle part.
        _, citations = lot_membres_cypher()
        assert "r.rang = c.rang" in citations
        assert "r.periode = c.periode" in citations


@requires_db
@pytest.mark.integration
class TestExtractionMembres:
    """Ce que la requête retient, et surtout ce qu'elle écarte."""

    async def test_un_membre_par_ligne_ses_citations_groupees(
        self, conn: psycopg.AsyncConnection
    ) -> None:
        from test_api_membres import semer_membres

        await semer_membres(conn)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_EXTRACTION_MEMBRES)
            lignes = await cur.fetchall()

        # Carla n'a aucun top : pas de nœud pour elle. Un nœud sans arête
        # n'apporte rien à une traversée, et il y en aurait 8 593.
        assert [ligne["membre_id"] for ligne in lignes] == [1, 2]
        alice = lignes[0]["citations"]
        assert [c["rang"] for c in alice] == [1, 2]
        assert all(set(c) == {"oeuvreId", "rang", "periode", "univers"} for c in alice)

    async def test_un_top_invalide_ne_compte_pas(self, conn: psycopg.AsyncConnection) -> None:
        from test_api_membres import semer_membres

        await semer_membres(conn)
        await conn.execute("update membre.five set valide = false where membre_id = 2")
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_EXTRACTION_MEMBRES)
            lignes = await cur.fetchall()

        assert [ligne["membre_id"] for ligne in lignes] == [1]


class TestNormaliser:
    def test_norme_unitaire(self) -> None:
        unitaire, norme = normaliser([3.0, 4.0])
        assert norme == pytest.approx(5.0)
        assert unitaire == pytest.approx([0.6, 0.8])

    def test_meme_couleur_intensites_differentes(self) -> None:
        """Le point du §5.4 de la mission empreinte : le cosinus ne distingue
        pas « un peu de peur » de « beaucoup de peur ». Les deux vecteurs
        unitaires sont identiques, et c'est la norme qui porte l'écart."""
        faible, n_faible = normaliser([2.0, 1.0, 1.0])
        forte, n_forte = normaliser([8.0, 4.0, 4.0])
        assert faible == pytest.approx(forte)
        assert n_forte > n_faible

    def test_vecteur_nul(self) -> None:
        assert normaliser([0.0, 0.0]) == (None, None)


class TestConstruireOeuvre:
    def test_absences_explicites(self) -> None:
        """Une propriété absente part à `null` : c'est ce qui la retire du nœud
        au `SET n += $props`. L'omettre laisserait une affiche disparue de TMDB
        vivre pour toujours dans le graphe."""
        noeud = construire_oeuvre(_ligne(), "series")
        props = noeud["props"]
        for cle in ("titre", "affiche", "empreinte", "empreinteBareme"):
            assert cle in props
            assert props[cle] is None

    def test_bareme_absent_sans_empreinte(self) -> None:
        noeud = construire_oeuvre(_ligne(bareme="empreinte-v3"), "series")
        assert noeud["props"]["empreinteBareme"] is None

    def test_empreinte_et_norme(self) -> None:
        noeud = construire_oeuvre(
            _ligne(empreinte=[6.0, 2.0, 3.0], empreinte_source="juge", bareme="empreinte-v3"),
            "movies",
        )
        props = noeud["props"]
        assert props["empreinte"] == [6.0, 2.0, 3.0]
        assert props["empreinteNorme"] == pytest.approx(7.0, abs=1e-3)
        assert props["empreinteUnitaire"] == pytest.approx([6 / 7, 2 / 7, 3 / 7], abs=1e-4)
        assert props["empreinteSource"] == "juge"
        assert props["empreinteBareme"] == "empreinte-v3"

    def test_date_serialisee(self) -> None:
        noeud = construire_oeuvre(_ligne(date_sortie=date(2011, 4, 17)), "series")
        assert noeud["props"]["dateSortie"] == "2011-04-17"

    def test_distribution_aplatie(self) -> None:
        """`aggregate_credits` porte les rôles dans un tableau, `credits` met le
        personnage à plat. Les deux formes donnent le même nœud."""
        agregee = construire_oeuvre(
            _ligne(
                distribution=[
                    {
                        "id": 12,
                        "name": "Peter Dinklage",
                        "roles": [{"character": "Tyrion", "episode_count": 67}],
                        "total_episode_count": 67,
                    }
                ]
            ),
            "series",
        )["distribution"]
        plate = construire_oeuvre(
            _ligne(distribution=[{"id": 12, "name": "Peter Dinklage", "character": "Tyrion"}]),
            "movies",
        )["distribution"]
        assert agregee[0]["cle"] == plate[0]["cle"] == "tmdb:12"
        assert agregee[0]["personnage"] == plate[0]["personnage"] == "Tyrion"
        assert agregee[0]["episodes"] == 67

    def test_membre_sans_identifiant_ecarte(self) -> None:
        # Sans identifiant, pas de clé : le nœud serait fusionné avec tous les
        # autres anonymes.
        noeud = construire_oeuvre(_ligne(distribution=[{"name": "Inconnu"}]), "movies")
        assert noeud["distribution"] == []

    def test_ordre_par_defaut_est_le_rang(self) -> None:
        """TMDB ne pose pas toujours `order` côté série ; le rang dans le
        tableau est déjà l'ordre du générique."""
        noeud = construire_oeuvre(
            _ligne(distribution=[{"id": 1}, {"id": 2}, {"id": 3, "order": 9}]), "series"
        )
        assert [m["ordre"] for m in noeud["distribution"]] == [0, 1, 9]

    def test_realisateurs_les_plus_presents_dabord(self) -> None:
        crew = [
            {"id": i, "jobs": [{"job": "Director", "episode_count": i}], "total_episode_count": i}
            for i in range(1, REALISATEURS_MAX + 5)
        ]
        noeud = construire_oeuvre(_ligne(realisation=crew), "series")
        assert len(noeud["realisation"]) == REALISATEURS_MAX
        episodes = [m["episodes"] for m in noeud["realisation"]]
        assert episodes == sorted(episodes, reverse=True)

    def test_departement_directing_sans_realisation(self) -> None:
        """Le filtre jsonpath des séries laisse passer tout le département
        « Directing » — assistants compris. C'est ici qu'ils sont écartés."""
        noeud = construire_oeuvre(
            _ligne(
                realisation=[
                    {"id": 1, "jobs": [{"job": "Assistant Director", "episode_count": 40}]},
                    {"id": 2, "jobs": [{"job": "Director", "episode_count": 3}]},
                ]
            ),
            "series",
        )
        assert [m["cle"] for m in noeud["realisation"]] == ["tmdb:2"]

    def test_createurs(self) -> None:
        noeud = construire_oeuvre(
            _ligne(creation=[{"id": 7, "name": "David Simon"}, {"name": "sans id"}]), "series"
        )
        assert noeud["creation"] == [{"cle": "tmdb:7", "nom": "David Simon", "photo": None}]


class TestExtraction:
    def test_chemins_par_univers(self) -> None:
        """Une série consolide ses crédits sur toute sa durée, un film n'a que
        `credits` — et leurs métiers ne se lisent pas au même endroit."""
        series = parametres_extraction(MEDIA["tv"])
        films = parametres_extraction(MEDIA["movie"])
        assert "aggregate_credits" in series["p_cast"]
        assert "aggregate_credits" in series["p_crew"]
        assert "aggregate_credits" not in films["p_cast"]
        assert '@.job == "Director"' in films["p_crew"]
        assert str(DISTRIBUTION_MAX - 1) in series["p_cast"]

    def test_ids_facultatifs(self) -> None:
        assert parametres_extraction(MEDIA["tv"])["ids"] is None
        assert parametres_extraction(MEDIA["tv"], [1, 2])["ids"] == [1, 2]


class TestCypher:
    def test_une_ligne_retire_les_commentaires(self) -> None:
        """Un `//` survivant avalerait tout ce qui le suit une fois l'
        instruction pliée : c'est le seul risque du pliage, et il est muet."""
        plie = une_ligne("MATCH (n)\n// un commentaire\nRETURN n")
        assert plie == "MATCH (n) RETURN n"
        assert "\n" not in plie

    def test_schema_porte_la_dimension_du_bareme(self) -> None:
        instructions = schema_cypher(6)
        vectoriels = [i for i in instructions if "VECTOR INDEX" in i]
        assert len(vectoriels) == 2
        assert all("`vector.dimensions`: 6" in i for i in vectoriels)
        # La quantification arrondit les coordonnées : sur six dimensions elle
        # n'économise rien et abîme le classement. Elle est ACTIVE par défaut.
        assert all("`vector.quantization.type`: 'none'" in i for i in vectoriels)
        assert sum("'euclidean'" in i for i in vectoriels) == 1
        assert sum("'cosine'" in i for i in vectoriels) == 1

    def test_schema_tient_sur_une_ligne(self) -> None:
        assert all("\n" not in i for i in schema_cypher(6))

    def test_lot_couvre_les_quatre_relations(self) -> None:
        instructions = lot_cypher("series")
        ensemble = " ".join(instructions)
        for rel in (REL_GENRE, REL_JOUE, REL_REALISE, REL_CREE):
            assert rel in ensemble
        assert LABEL_UNIVERS["series"] in instructions[0]

    def test_lot_efface_avant_de_reecrire(self) -> None:
        """Sans l'effacement, un genre retiré d'une fiche recollectée resterait
        attaché pour toujours — `MERGE` ajoute, il ne retire pas."""
        assert "DELETE perimee" in lot_cypher("movies")[0]

    def test_une_instruction_par_liste(self) -> None:
        """`UNWIND` d'une liste vide supprime la ligne : tout mettre dans une
        seule instruction ferait perdre la distribution des œuvres sans
        genre."""
        instructions = lot_cypher("movies")
        assert all(sum(1 for _ in i.split("UNWIND")) - 1 <= 2 for i in instructions)


# Un payload TMDB réduit à ce que la projection regarde : ce que la fiche porte
# de genres, de distribution et de fabrique.
PAYLOAD_SERIE = {
    "name": "Le Trône de fer",
    "original_name": "Game of Thrones",
    "poster_path": "/got.jpg",
    "first_air_date": "2011-04-17",
    "vote_average": 8.4,
    "vote_count": 22000,
    "status": "Ended",
    "original_language": "en",
    "genres": [{"id": 18, "name": "Drame"}, {"id": 10765, "name": "Science-Fiction & Fantastique"}],
    "created_by": [{"id": 9813, "name": "David Benioff", "profile_path": "/db.jpg"}],
    # `credits` ne donne que la saison 1 ; `aggregate_credits` consolide. Les
    # deux sont là pour vérifier que c'est bien le second qui gagne.
    "credits": {"cast": [{"id": 999, "name": "Figurant saison 1", "character": "Garde"}]},
    "aggregate_credits": {
        "cast": [
            {
                "id": 22970,
                "name": "Peter Dinklage",
                "profile_path": "/pd.jpg",
                "total_episode_count": 67,
                "roles": [{"character": "Tyrion Lannister", "episode_count": 67}],
            }
        ],
        "crew": [
            {
                "id": 1223,
                "name": "Alan Taylor",
                "department": "Directing",
                "total_episode_count": 7,
                "jobs": [{"job": "Director", "episode_count": 7}],
            },
            # Même département, autre métier : le filtre jsonpath le laisse
            # passer, la mise en forme l'écarte.
            {
                "id": 5555,
                "name": "Assistant",
                "department": "Directing",
                "jobs": [{"job": "Assistant Director", "episode_count": 40}],
            },
            # Un autre département : le jsonpath, lui, doit déjà l'avoir écarté.
            {
                "id": 7777,
                "name": "Chef op",
                "department": "Camera",
                "jobs": [{"job": "Director of Photography"}],
            },
        ],
    },
}


@pytest.mark.integration
@requires_db
class TestExtractionEnBase:
    """La requête d'extraction contre une vraie base.

    C'est le seul endroit où les filtres jsonpath (`? (@.department ==
    "Directing")`), le `with ordinality` qui donne l'ordre des axes et le
    `having` qui refuse les vecteurs incomplets se vérifient. Un test unitaire
    ne peut rien en dire.
    """

    async def _semer_serie(self, conn: psycopg.AsyncConnection) -> int:
        await conn.execute(
            "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
            " values (1399, 'Game of Thrones', 400.0, date '2026-08-05')"
        )
        await conn.execute(
            "insert into raw_source (source, kind, source_id, lang, http_status,"
            " payload, payload_sha256)"
            " values ('tmdb', 'tv', '1399', 'fr-FR', 200, %s::jsonb, %s)",
            (json.dumps(PAYLOAD_SERIE), b"\x01"),
        )
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into oeuvre (univers, id_tmdb) values ('series', 1399) returning id"
            )
            row = await cur.fetchone()
        from fiv_admin.catalog import refresh_cards

        await refresh_cards(conn)
        return row[0]

    async def _extraire(self, conn: psycopg.AsyncConnection) -> list[dict[str, Any]]:
        media = MEDIA["tv"]
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(requete_extraction(media), parametres_extraction(media))
            return await cur.fetchall()

    async def test_fiche_genres_et_gens(self, conn: psycopg.AsyncConnection) -> None:
        pivot = await self._semer_serie(conn)
        lignes = await self._extraire(conn)
        assert [ligne["oeuvre_id"] for ligne in lignes] == [pivot]

        noeud = construire_oeuvre(lignes[0], "series")
        props = noeud["props"]
        assert props["titre"] == "Le Trône de fer"
        assert props["titreOriginal"] == "Game of Thrones"
        assert props["annee"] == 2011
        assert props["affiche"] == "/got.jpg"
        # (8,4 × 22 000 + 6,5 × 50) / 22 050 — la note pondérée de la grille.
        assert props["note"] == pytest.approx(8.4, abs=0.01)
        # Jamais notée : le graphe l'accueille sans empreinte plutôt qu'avec
        # des zéros que la distance croirait.
        assert props["empreinte"] is None

        assert sorted(g["cle"] for g in noeud["genres"]) == ["tmdb:10765", "tmdb:18"]
        # `aggregate_credits` gagne sur `credits` : le figurant de la saison 1
        # n'est pas la distribution de la série.
        assert [m["cle"] for m in noeud["distribution"]] == ["tmdb:22970"]
        assert noeud["distribution"][0]["personnage"] == "Tyrion Lannister"
        assert noeud["distribution"][0]["episodes"] == 67
        # Le jsonpath a retenu le département, la mise en forme le métier.
        assert [m["cle"] for m in noeud["realisation"]] == ["tmdb:1223"]
        assert [m["cle"] for m in noeud["creation"]] == ["tmdb:9813"]

    async def test_empreinte_dans_lordre_du_bareme(self, conn: psycopg.AsyncConnection) -> None:
        """L'ordre des coordonnées est celui du tableau `axes` du barème, pas
        l'ordre alphabétique ni celui d'insertion des notes. C'est le contrat
        qui rend deux vecteurs comparables."""
        pivot = await self._semer_serie(conn)
        await conn.execute(
            "insert into notation.rubric (version, prompt, axes)"
            " values ('test-graphe', 'x', '[\"gamma\", \"alpha\", \"beta\"]'::jsonb)"
        )
        # Insérées dans le désordre, et une valeur ancienne à écraser.
        for axe, valeur, quand in (
            ("alpha", 1.0, "2026-01-01"),
            ("beta", 2.0, "2026-01-01"),
            ("gamma", 3.0, "2026-01-01"),
            ("alpha", 9.0, "2026-02-01"),
        ):
            await conn.execute(
                "insert into notation.score (oeuvre_id, axe, valeur, rubric_version, modele,"
                " input_sha256, prompt_sha256, scored_at)"
                " values (%s, %s, %s, 'test-graphe', 'juge-test', 'a', 'b', %s::timestamptz)",
                (pivot, axe, valeur, quand),
            )

        noeud = construire_oeuvre((await self._extraire(conn))[0], "series")
        assert noeud["props"]["empreinte"] == [3.0, 9.0, 2.0]
        assert noeud["props"]["empreinteSource"] == "juge"
        assert noeud["props"]["empreinteBareme"] == "test-graphe"

    async def test_vecteur_incomplet_refuse(self, conn: psycopg.AsyncConnection) -> None:
        """Cinq axes sur six n'est pas une empreinte à trou : c'est pas
        d'empreinte. Un trou bouché par un zéro déplacerait l'œuvre dans
        l'espace sans que rien ne le signale."""
        pivot = await self._semer_serie(conn)
        await conn.execute(
            "insert into notation.rubric (version, prompt, axes)"
            " values ('test-graphe', 'x', '[\"alpha\", \"beta\"]'::jsonb)"
        )
        await conn.execute(
            "insert into notation.score (oeuvre_id, axe, valeur, rubric_version, modele,"
            " input_sha256, prompt_sha256) values (%s, 'alpha', 5.0, 'test-graphe', 'juge-test',"
            " 'a', 'b')",
            (pivot,),
        )
        noeud = construire_oeuvre((await self._extraire(conn))[0], "series")
        assert noeud["props"]["empreinte"] is None

    async def test_le_juge_prime_sur_la_regression(self, conn: psycopg.AsyncConnection) -> None:
        """La régression ne sert que ce qui n'a pas été jugé, et les deux ne se
        mélangent jamais dans un même vecteur — la ridge contracte vers la
        moyenne, ses coordonnées ne sont pas comparables à celles du juge."""
        pivot = await self._semer_serie(conn)
        await conn.execute(
            "insert into notation.rubric (version, prompt, axes)"
            " values ('test-graphe', 'x', '[\"alpha\"]'::jsonb)"
        )
        for modele, valeur, quand in (
            ("juge-test", 8.0, "2026-01-01"),
            # Plus récente, et pourtant écartée : c'est le modèle qui départage.
            ("interne-ridge", 5.0, "2026-03-01"),
        ):
            await conn.execute(
                "insert into notation.score (oeuvre_id, axe, valeur, rubric_version, modele,"
                " input_sha256, prompt_sha256, scored_at)"
                " values (%s, 'alpha', %s, 'test-graphe', %s, 'a', 'b', %s::timestamptz)",
                (pivot, valeur, modele, quand),
            )
        noeud = construire_oeuvre((await self._extraire(conn))[0], "series")
        assert noeud["props"]["empreinte"] == [8.0]
        assert noeud["props"]["empreinteSource"] == "juge"

    async def test_regression_en_repli(self, conn: psycopg.AsyncConnection) -> None:
        pivot = await self._semer_serie(conn)
        await conn.execute(
            "insert into notation.rubric (version, prompt, axes)"
            " values ('test-graphe', 'x', '[\"alpha\"]'::jsonb)"
        )
        await conn.execute(
            "insert into notation.score (oeuvre_id, axe, valeur, rubric_version, modele,"
            " input_sha256, prompt_sha256) values (%s, 'alpha', 5.0, 'test-graphe',"
            " 'interne-ridge', 'a', 'b')",
            (pivot,),
        )
        noeud = construire_oeuvre((await self._extraire(conn))[0], "series")
        assert noeud["props"]["empreinte"] == [5.0]
        assert noeud["props"]["empreinteSource"] == "interne"


def _graphe_simule(reponses: dict[str, Any] | None = None) -> Graphe:
    """Un `Graphe` dont le transport est simulé : les instructions partent dans
    une liste au lieu d'un serveur. `graphe.envoyees` les rend au test."""
    envoyees: list[dict[str, Any]] = []
    reponses = reponses or {}

    def handler(request: httpx.Request) -> httpx.Response:
        corps = json.loads(request.content)
        envoyees.append(corps)
        for motif, valeurs in reponses.items():
            if motif in corps["statement"]:
                return httpx.Response(202, json=valeurs)
        return httpx.Response(202, json={"data": {"fields": [], "values": []}})

    graphe = Graphe("http://neo4j.test", "neo4j", "x")
    graphe._http = httpx.AsyncClient(
        base_url="http://neo4j.test",
        transport=httpx.MockTransport(handler),
    )
    graphe.envoyees = envoyees  # type: ignore[attr-defined]
    return graphe


class TestTransport:
    async def test_erreur_neo4j_porte_son_code(self) -> None:
        """Neo4j répond 202 même pour une erreur : sans la lecture d'`errors`,
        une instruction refusée passerait pour un succès silencieux."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                202,
                json={
                    "errors": [{"code": "Neo.ClientError.Statement.SyntaxError", "message": "…"}]
                },
            )

        graphe = Graphe("http://neo4j.test", "neo4j", "x")
        graphe._http = httpx.AsyncClient(
            base_url="http://neo4j.test", transport=httpx.MockTransport(handler)
        )
        async with graphe:
            with pytest.raises(GrapheErreur, match="SyntaxError"):
                await graphe.executer("MATCH (n) RETURN n")

    async def test_authentification_refusee_est_dite(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={})

        graphe = Graphe("http://neo4j.test", "neo4j", "faux")
        graphe._http = httpx.AsyncClient(
            base_url="http://neo4j.test", transport=httpx.MockTransport(handler)
        )
        async with graphe:
            with pytest.raises(GrapheErreur, match="NEO4J_PASSWORD"):
                await graphe.executer("MATCH (n) RETURN n")

    async def test_parametres_jamais_interpoles(self) -> None:
        """Le plan d'exécution est mis en cache par forme de requête : une
        projection qui interpolerait passerait son temps dans le planificateur.
        C'est aussi ce qui met les titres à l'abri d'une injection Cypher."""
        graphe = _graphe_simule()
        async with graphe:
            await graphe.executer("MERGE (n {cle: $cle})", cle="tmdb:1")
        corps = graphe.envoyees[0]  # type: ignore[attr-defined]
        assert corps["parameters"] == {"cle": "tmdb:1"}
        assert "tmdb:1" not in corps["statement"]


@pytest.mark.integration
@requires_db
class TestSynchronisation:
    async def test_sans_marqueur_elle_refuse(self, conn: psycopg.AsyncConnection) -> None:
        """Un graphe sans point de reprise ne peut pas dire ce qui lui manque :
        deviner creuserait un trou silencieux."""
        graphe = _graphe_simule()
        async with graphe:
            bilan = await synchroniser(conn, graphe, MEDIA["tv"])
        assert "erreur" in bilan
        assert "projeter" in bilan["erreur"]

    async def _pivots_changes(self, conn: psycopg.AsyncConnection, depuis: str) -> list[int]:
        async with conn.cursor() as cur:
            await cur.execute(
                _PIVOTS_CHANGES,
                {"source": "tmdb", "kind": "tv", "univers": "series", "depuis": depuis},
            )
            return sorted(row[0] for row in await cur.fetchall())

    async def test_une_note_fraiche_suffit(self, conn: psycopg.AsyncConnection) -> None:
        """LA porte d'entrée qu'un index de recherche n'a pas : `training note`
        n'écrit ni dans le brut ni dans `fetch_state`. Sans elle, une empreinte
        fraîche n'entrerait jamais dans le graphe."""
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into oeuvre (univers, id_tmdb, created_at)"
                " values ('series', 1399, '2020-01-01'::timestamptz) returning id"
            )
            pivot = (await cur.fetchone())[0]
        await conn.execute(
            "insert into notation.score (oeuvre_id, axe, valeur, rubric_version, modele,"
            " input_sha256, prompt_sha256, scored_at)"
            " values (%s, 'alpha', 5.0, 'v1', 'juge-test', 'a', 'b', now())",
            (pivot,),
        )
        assert await self._pivots_changes(conn, "2026-01-01") == [pivot]
        # Et rien avant la note : le marqueur postérieur ne rend rien.
        assert await self._pivots_changes(conn, "2999-01-01") == []

    async def test_collecte_et_oeuvre_neuve(self, conn: psycopg.AsyncConnection) -> None:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into oeuvre (univers, id_tmdb, created_at) values"
                " ('series', 100, '2020-01-01'::timestamptz),"  # ancienne, dormante
                " ('series', 200, '2020-01-01'::timestamptz),"  # ancienne, recollectée
                " ('series', 300, now())"  # neuve
                " returning id, id_tmdb"
            )
            pivots = {tmdb: pid for pid, tmdb in await cur.fetchall()}
        await conn.execute(
            "insert into fetch_state (source, kind, source_id, last_fetched_at)"
            " values ('tmdb', 'tv', '200', now()), ('tmdb', 'tv', '100', '2020-01-01'::timestamptz)"
        )
        assert await self._pivots_changes(conn, "2026-01-01") == sorted([pivots[200], pivots[300]])


class TestMetiers:
    """Acteurs et réalisateurs sont des labels sur le MÊME nœud, pas des nœuds
    distincts. C'est ce qui permet à Clint Eastwood d'être les deux sans être
    dédoublé — et l'unicité demandée reste portée par `:FivPersonne`."""

    def test_chaque_relation_confere_un_metier(self) -> None:
        assert set(LABEL_DU_ROLE) == {REL_JOUE, REL_REALISE, REL_CREE}
        # Le genre n'est pas un métier : la table ne doit pas déborder sur les
        # relations qui ne partent pas d'une personne.
        assert REL_GENRE not in LABEL_DU_ROLE

    def test_les_metiers_sont_poses_par_la_projection(self) -> None:
        instructions = lot_cypher("series")
        ensemble = " ".join(instructions)
        for relation, label in LABEL_DU_ROLE.items():
            assert f"SET p:{label}" in ensemble
            assert relation in ensemble

    def test_le_merge_reste_ancre_sur_la_personne(self) -> None:
        """Les `MERGE` visent `:FivPersonne` — c'est lui qui porte la
        contrainte d'unicité. Ancrer sur `:FivActeur` créerait un second nœud
        pour la même personne le jour où elle réalise."""
        for instruction in lot_cypher("movies"):
            for label in (LABEL_ACTEUR, LABEL_REALISATEUR, LABEL_CREATEUR):
                assert f"MERGE (p:{label}" not in instruction
        assert f"MERGE (p:{LABEL_PERSONNE}" in " ".join(lot_cypher("movies"))

    def test_lunicite_ne_porte_que_sur_la_personne(self) -> None:
        """Une contrainte par métier serait au mieux redondante, au pire un
        second espace de clés : `cle` identifie la personne, pas le rôle."""
        contraintes = [i for i in schema_cypher(6) if "CREATE CONSTRAINT" in i]
        assert any(LABEL_PERSONNE in i for i in contraintes)
        for label in (LABEL_ACTEUR, LABEL_REALISATEUR, LABEL_CREATEUR):
            assert not any(label in i for i in contraintes)
