"""Le jeton de session : authentique, expiré, trafiqué."""

from fiv_webapp.jeton import JetonSession


def test_aller_retour() -> None:
    jeton = JetonSession("secret", ttl_seconds=3600)
    brut = jeton.emettre("abc-123", now=1000)
    session = jeton.lire(brut, now=2000)
    assert session is not None
    assert session.session_id == "abc-123"
    assert session.emise_le == 1000
    assert session.expire_le == 4600


def test_expiration() -> None:
    jeton = JetonSession("secret", ttl_seconds=10)
    brut = jeton.emettre("abc", now=1000)
    assert jeton.lire(brut, now=1009) is not None
    assert jeton.lire(brut, now=1010) is None


def test_mauvais_secret() -> None:
    brut = JetonSession("secret-a", ttl_seconds=3600).emettre("abc")
    assert JetonSession("secret-b", ttl_seconds=3600).lire(brut) is None


def test_jeton_trafique() -> None:
    jeton = JetonSession("secret", ttl_seconds=3600)
    brut = jeton.emettre("abc")
    corps, signature = brut.split(".")
    # Le corps changé, la signature gardée : refusé avant même d'être lu.
    assert jeton.lire(f"x{corps}.{signature}") is None
    # Des formes qui ne sont pas des jetons du tout.
    assert jeton.lire("") is None
    assert jeton.lire("pas-un-jeton") is None
    assert jeton.lire("a.b.c") is None
