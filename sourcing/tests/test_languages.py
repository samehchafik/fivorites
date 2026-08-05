"""La liste des langues de saison — le poste de coût dominant de la collecte."""

from __future__ import annotations

from fiv_sourcing.config import Settings


def test_les_cinq_langues_par_defaut():
    langues = Settings().season_languages
    assert langues == ("fr-FR", "en-US", "es-ES", "ar-SA", "tr-TR")


def test_la_liste_se_restreint_par_configuration():
    """Pour pouvoir viser étroit sur un échantillon avant d'ouvrir en grand :
    chaque langue multiplie le nombre d'appels par saison."""
    settings = Settings(tmdb_season_languages="fr-FR,en-US")
    assert settings.season_languages == ("fr-FR", "en-US")


def test_les_espaces_et_entrees_vides_sont_ignores():
    """La liste est saisie à la main dans un .env : elle doit tolérer une mise
    en forme approximative plutôt que produire une langue `''` silencieuse."""
    settings = Settings(tmdb_season_languages=" fr-FR , , en-US ,")
    assert settings.season_languages == ("fr-FR", "en-US")
