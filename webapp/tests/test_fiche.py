"""La mise en forme de la fiche : ce que le brut TMDB devient à l'écran.

Les parties pures seulement — les chemins jsonb, eux, ne se vérifient que
contre une vraie base (côté admin, `test_search.py::TestExtraction` couvre
les mêmes). Ce qui se teste ici : les règles d'affichage qu'on regretterait
de casser en silence — l'ordre des saisons, les spéciaux écartés, les deux
formes de crédits aplaties pareil, le département Directing filtré.
"""

from __future__ import annotations

from typing import Any

from fiv_webapp.fiche import DISTRIBUTION_MAX, REALISATION_MAX, Fiches
from fiv_webapp.univers import UNIVERS


class TestDistribution:
    def test_roles_agreges_et_a_plat(self) -> None:
        """`aggregate_credits` porte les rôles dans un tableau, `credits` met
        le personnage à plat : les deux doivent rendre la même chose."""
        fiches = Fiches()
        agrege = fiches._distribution(
            [
                {
                    "name": "Emilia Clarke",
                    "profile_path": "/e.jpg",
                    "roles": [{"character": "Daenerys", "episode_count": 62}],
                    "total_episode_count": 62,
                }
            ]
        )
        a_plat = fiches._distribution(
            [{"name": "Emilia Clarke", "profile_path": "/e.jpg", "character": "Daenerys"}]
        )
        assert agrege[0].nom == a_plat[0].nom == "Emilia Clarke"
        assert agrege[0].role == a_plat[0].role == "Daenerys"
        assert agrege[0].episodes == 62

    def test_sans_nom_ecarte_et_plafond(self) -> None:
        """Un crédit sans nom n'est pas une personne ; et la modale ne montre
        pas cinquante visages."""
        membres: list[dict[str, Any]] = [{"name": ""}, {"name": "   "}]
        membres += [{"name": f"Acteur {i}"} for i in range(DISTRIBUTION_MAX + 5)]
        retenus = Fiches()._distribution(membres)
        assert len(retenus) == DISTRIBUTION_MAX
        assert all(personne.nom.strip() for personne in retenus)


class TestRealisation:
    def test_createurs_puis_realisateurs_sans_doublon(self) -> None:
        """Le créateur d'une série la porte plus que le réalisateur d'un
        épisode : il entre en premier, et ne se dédouble pas s'il a aussi
        réalisé."""
        retenus = Fiches()._realisation(
            [
                {
                    "name": "David Benioff",
                    "jobs": [{"job": "Director", "episode_count": 2}],
                    "total_episode_count": 2,
                },
                {
                    "name": "Alan Taylor",
                    "jobs": [{"job": "Director", "episode_count": 7}],
                    "total_episode_count": 7,
                },
            ],
            [{"name": "David Benioff", "profile_path": "/d.jpg"}],
        )
        noms = [personne.nom for personne in retenus]
        assert noms.count("David Benioff") == 1
        # Le rôle est un CODE : la fiche se lit en quatre langues, et c'est le
        # front qui le nomme (`src/i18n/textes`, clés `role.*`).
        assert next(p for p in retenus if p.nom == "David Benioff").role == "creation"
        # Le créateur EN TÊTE, même avec moins d'épisodes que le réalisateur :
        # il signe la série, l'autre signe sept épisodes.
        assert noms == ["David Benioff", "Alan Taylor"]

    def test_seul_directing_passe(self) -> None:
        """Côté série, le filtre jsonpath laisse passer tout le département :
        c'est ici que le monteur et le premier assistant s'arrêtent."""
        retenus = Fiches()._realisation(
            [
                {"name": "Alan Taylor", "jobs": [{"job": "Director", "episode_count": 7}]},
                {"name": "Quelqu'un", "jobs": [{"job": "First Assistant Director"}]},
            ],
            [],
        )
        assert [personne.nom for personne in retenus] == ["Alan Taylor"]

    def test_film_sans_tableau_de_metiers(self) -> None:
        """Côté film, le jsonpath a déjà filtré `job == "Director"` : pas de
        tableau `jobs`, et le crédit doit passer tel quel."""
        retenus = Fiches()._realisation([{"name": "Bong Joon-ho", "job": "Director"}], [])
        assert [personne.nom for personne in retenus] == ["Bong Joon-ho"]

    def test_les_plus_presents_d_abord_et_plafond(self) -> None:
        equipe = [
            {"name": f"Réal {i}", "jobs": [{"job": "Director"}], "total_episode_count": i}
            for i in range(REALISATION_MAX + 4)
        ]
        retenus = Fiches()._realisation(equipe, [])
        assert len(retenus) == REALISATION_MAX
        # Le plus présent en tête.
        assert retenus[0].episodes == REALISATION_MAX + 3


class TestSaisons:
    def test_ordre_et_speciaux_ecartes(self) -> None:
        """La saison 0 de TMDB, ce sont les bonus : elle n'est pas une étape
        du récit et ne doit pas ouvrir la liste."""
        saisons = Fiches()._saisons(
            [
                {"season_number": 2, "name": "Saison 2", "air_date": "2012-04-01"},
                {"season_number": 0, "name": "Spéciaux", "air_date": "2011-01-01"},
                {"season_number": 1, "name": "Saison 1", "air_date": "2011-04-17"},
            ]
        )
        assert [saison.numero for saison in saisons] == [1, 2]
        assert saisons[0].annee == 2011

    def test_sans_date_ni_numero(self) -> None:
        """Une saison annoncée sans date existe (la prochaine) ; une entrée
        sans numéro n'est pas une saison."""
        saisons = Fiches()._saisons([{"season_number": 3}, {"name": "Bizarre"}])
        assert [saison.numero for saison in saisons] == [3]
        assert saisons[0].annee is None


class TestEpisodes:
    def test_ordre_et_sans_numero(self) -> None:
        """L'ordre de diffusion, quel que soit l'ordre du payload ; un épisode
        sans numéro n'a pas de place dans la liste."""
        episodes = Fiches()._episodes(
            [
                {"episode_number": 2, "name": "Le Roi du Nord"},
                {"name": "Sans numéro"},
                {"episode_number": 1, "name": "L'hiver vient", "vote_average": 8.44},
            ]
        )
        assert [episode.numero for episode in episodes] == [1, 2]
        assert episodes[0].titre == "L'hiver vient"
        assert episodes[0].note == 8.4

    def test_champs_vides_deviennent_none(self) -> None:
        """Une date vide de TMDB (`""`) n'est pas une date, et un synopsis
        d'espaces n'est pas un synopsis."""
        episodes = Fiches()._episodes(
            [{"episode_number": 1, "name": "  ", "overview": "   ", "air_date": ""}]
        )
        assert episodes[0].titre is None
        assert episodes[0].synopsis is None
        assert episodes[0].diffusion is None


class TestChapeau:
    def test_coupe_a_la_premiere_section(self) -> None:
        """Le collecté est l'article ENTIER : sans cette coupe, la modale d'un
        livre affiche sa bibliographie et ses liens externes — vu à l'écran."""
        chapeau = Fiches()._chapeau(
            "Le Seigneur des anneaux est un roman de Tolkien.\n"
            "Il paraît en trois volumes.\n"
            "\n"
            "== Résumé ==\n"
            "Frodon quitte la Comté…\n"
            "=== Liens externes ===\n"
            "https://exemple.fr\n"
        )
        assert chapeau == (
            "Le Seigneur des anneaux est un roman de Tolkien.\nIl paraît en trois volumes."
        )

    def test_sans_section_ni_texte(self) -> None:
        assert Fiches()._chapeau("Un article sans section.") == "Un article sans section."
        assert Fiches()._chapeau(None) is None
        # Un article qui n'est QUE des sections ne laisse rien : le repli
        # Open Library doit alors prendre la main, d'où le None.
        assert Fiches()._chapeau("== Résumé ==\ntexte") is None


class TestParametresCredits:
    def test_series_consolident_films_non(self) -> None:
        """La divergence TMDB, payée une fois ici comme au graphe et à
        l'indexation."""
        fiches = Fiches()
        series = fiches._parametres_credits(UNIVERS["series"])
        films = fiches._parametres_credits(UNIVERS["films"])
        assert "aggregate_credits" in series["p_cast_agg"]
        assert "department" in series["p_crew"]
        assert "aggregate_credits" not in films["p_cast_agg"]
        assert '@.job == "Director"' in films["p_crew"]


class TestSynopsis:
    """La cascade du synopsis : la langue demandée, puis l'anglais, puis la
    racine — et la langue retenue est dite."""

    def test_la_langue_demandee_passe_devant(self) -> None:
        texte, langue = Fiches()._synopsis(
            {
                "traductions": [{"overview": "En français"}],
                "traductions_en": [{"overview": "In English"}],
                "synopsis": "La racine",
            },
            "fr",
        )
        assert (texte, langue) == ("En français", "fr")

    def test_sans_traduction_ni_racine_l_anglais_sauve_la_fiche(self) -> None:
        """Le cas courant : 334 séries sur 500 n'ont pas de synopsis racine, et
        325 d'entre elles en ont un en anglais (mesuré sur la production)."""
        texte, langue = Fiches()._synopsis(
            {"traductions": [], "traductions_en": [{"overview": "In English"}], "synopsis": None},
            "ar",
        )
        assert (texte, langue) == ("In English", "en")

    def test_un_champ_vide_n_efface_pas_le_texte_qu_on_a(self) -> None:
        texte, langue = Fiches()._synopsis(
            {"traductions": [{"overview": "   "}], "traductions_en": [], "synopsis": "La racine"},
            "es",
        )
        assert (texte, langue) == ("La racine", "fr")

    def test_rien_nulle_part_ne_leve_pas(self) -> None:
        assert Fiches()._synopsis({}, "fr") == (None, None)
