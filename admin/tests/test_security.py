"""Mots de passe, jetons de session, freinage des tentatives."""

from __future__ import annotations

from fiv_admin.security import (
    LoginThrottle,
    hash_password,
    issue_session,
    read_session,
    verify_password,
)

SECRET = "secret-de-test"


def test_hash_is_salted_and_verifiable() -> None:
    first = hash_password("un mot de passe correct")
    second = hash_password("un mot de passe correct")

    assert first != second, "sans sel, deux comptes au même mot de passe se verraient"
    assert verify_password("un mot de passe correct", first)
    assert verify_password("un mot de passe correct", second)
    assert not verify_password("un mot de passe correct ", first)


def test_hash_carries_its_parameters() -> None:
    """Les paramètres sont dans la chaîne : les durcir ne casse pas l'existant."""
    encoded = hash_password("mot de passe")
    scheme, n, r, p, salt, digest = encoded.split("$")
    assert scheme == "scrypt"
    assert int(n) >= 1 << 14
    assert int(r) > 0 and int(p) > 0
    assert salt and digest


def test_malformed_hash_never_opens_the_door() -> None:
    for broken in ("", "n'importe quoi", "scrypt$abc$8$1$sel$empreinte", "bcrypt$1$2$3$4$5"):
        assert not verify_password("mot de passe", broken)


def test_session_round_trip() -> None:
    token = issue_session("sameh", SECRET, ttl_seconds=60)
    session = read_session(token, SECRET)

    assert session is not None
    assert session.username == "sameh"
    assert session.expires_at - session.issued_at == 60


def test_session_rejects_another_secret() -> None:
    token = issue_session("sameh", SECRET, ttl_seconds=60)
    assert read_session(token, "un autre secret") is None


def test_session_rejects_tampering() -> None:
    """Changer le compte dans le corps invalide la signature — c'est tout
    l'intérêt du HMAC par rapport à un cookie en clair."""
    token = issue_session("lecteur", SECRET, ttl_seconds=60)
    body, signature = token.split(".")
    forged = issue_session("admin", SECRET, ttl_seconds=60).split(".")[0]

    assert read_session(f"{forged}.{signature}", SECRET) is None
    assert read_session(f"{body}.{signature}x", SECRET) is None
    assert read_session("sans-point", SECRET) is None


def test_session_expires() -> None:
    token = issue_session("sameh", SECRET, ttl_seconds=60, now=1_000)
    assert read_session(token, SECRET, now=1_059) is not None
    assert read_session(token, SECRET, now=1_060) is None


def test_throttle_locks_then_frees() -> None:
    throttle = LoginThrottle(max_attempts=3, lockout_seconds=300)

    for _ in range(3):
        assert throttle.locked_for("sameh", "10.0.0.1", now=0.0) == 0
        throttle.record_failure("sameh", "10.0.0.1", now=0.0)

    assert throttle.locked_for("sameh", "10.0.0.1", now=0.0) == 300
    # Une autre adresse n'est pas punie pour celle-ci, et inversement.
    assert throttle.locked_for("sameh", "10.0.0.2", now=0.0) == 0
    # La fenêtre glisse.
    assert throttle.locked_for("sameh", "10.0.0.1", now=301.0) == 0


def test_throttle_resets_on_success() -> None:
    throttle = LoginThrottle(max_attempts=2, lockout_seconds=300)
    throttle.record_failure("sameh", "10.0.0.1", now=0.0)
    throttle.record_failure("sameh", "10.0.0.1", now=1.0)
    assert throttle.locked_for("sameh", "10.0.0.1", now=2.0) > 0

    throttle.reset("sameh", "10.0.0.1")
    assert throttle.locked_for("sameh", "10.0.0.1", now=2.0) == 0
