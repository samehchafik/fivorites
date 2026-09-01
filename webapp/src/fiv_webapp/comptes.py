"""Les comptes du site public : inscription, vérification, connexion, fives.

Le contrat, tenu par la base autant que par le code :

* un compte ne PEUT rien tant que l'email n'est pas vérifié — le code à six
  chiffres expire en quinze minutes et se consume en cinq tentatives ;
* la connexion RATTACHE la session anonyme courante au compte : tout ce que
  le visiteur avait classé avant de s'inscrire devient sien, rien ne se
  perd — c'est la promesse écrite dans la migration 001 ;
* poser un five pose AUSSI le signal « vu et aimé » : les fives nourrissent
  le moteur par le chemin que tout le reste emprunte déjà.

Le mot de passe est haché en scrypt (bibliothèque standard, coût mémoire
élevé par construction), au format auto-décrit `scrypt$n$r$p$sel$empreinte`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any

import psycopg

# Les paramètres scrypt : n=2^14 est le plancher recommandé, et le facteur
# limitant volontaire — quelques dizaines de millisecondes par tentative.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 16384, 8, 1

CODE_VALIDITE_MINUTES = 15
CODE_TENTATIVES_MAX = 5
FIVES_RANGS = (1, 2, 3, 4, 5)


def hacher(mot_de_passe: str) -> str:
    sel = secrets.token_bytes(16)
    empreinte = hashlib.scrypt(
        mot_de_passe.encode("utf-8"), salt=sel, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    sel_b64 = base64.b64encode(sel).decode()
    empreinte_b64 = base64.b64encode(empreinte).decode()
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${sel_b64}${empreinte_b64}"


def verifier_mot_de_passe(mot_de_passe: str, hache: str) -> bool:
    try:
        algo, n, r, p, sel_b64, empreinte_b64 = hache.split("$")
        if algo != "scrypt":
            return False
        attendue = base64.b64decode(empreinte_b64)
        calculee = hashlib.scrypt(
            mot_de_passe.encode("utf-8"),
            salt=base64.b64decode(sel_b64),
            n=int(n),
            r=int(r),
            p=int(p),
        )
        return hmac.compare_digest(attendue, calculee)
    except (ValueError, TypeError):
        return False


def generer_code() -> str:
    """Six chiffres, tirés au hasard cryptographique — jamais séquentiels."""
    return f"{secrets.randbelow(1_000_000):06d}"


@dataclass(frozen=True, slots=True)
class Compte:
    id: str
    pseudo: str
    email: str
    genre: str | None
    verifie: bool

    def publique(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pseudo": self.pseudo,
            "email": self.email,
            "genre": self.genre,
            "verifie": self.verifie,
        }


class CompteExiste(Exception):
    """L'email est déjà pris — la route en fait un 409 qui invite à se
    connecter plutôt qu'un refus sec."""


class Comptes:
    """Les écritures et lectures de `visiteur.compte` et `visiteur.five`."""

    # --- inscription et vérification ---------------------------------------

    async def inscrire(
        self,
        conn: psycopg.AsyncConnection,
        *,
        pseudo: str,
        email: str,
        mot_de_passe: str,
        genre: str | None = None,
    ) -> tuple[Compte, str]:
        """Crée le compte non vérifié et rend (compte, code à envoyer)."""
        email = email.strip().lower()
        async with conn.cursor() as cur:
            await cur.execute("select 1 from visiteur.compte where email = %s", (email,))
            if await cur.fetchone():
                raise CompteExiste(email)
            await cur.execute(
                "insert into visiteur.compte (pseudo, email, mot_de_passe, genre)"
                " values (%s, %s, %s, %s) returning id",
                (pseudo.strip(), email, hacher(mot_de_passe), genre),
            )
            (compte_id,) = await cur.fetchone()
        code = await self._poser_code(conn, str(compte_id))
        return (
            Compte(
                id=str(compte_id), pseudo=pseudo.strip(), email=email, genre=genre, verifie=False
            ),
            code,
        )

    async def _poser_code(self, conn: psycopg.AsyncConnection, compte_id: str) -> str:
        code = generer_code()
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into visiteur.verification (compte_id, code, expire_le)"
                " values (%s, %s, now() + make_interval(mins => %s))"
                " on conflict (compte_id) do update"
                "   set code = excluded.code, expire_le = excluded.expire_le,"
                "       tentatives = 0, envoye_le = now()",
                (compte_id, code, CODE_VALIDITE_MINUTES),
            )
        return code

    async def renvoyer_code(
        self, conn: psycopg.AsyncConnection, email: str
    ) -> tuple[Compte, str] | None:
        """Un nouveau code pour un compte non vérifié — None si l'email est
        inconnu ou déjà vérifié : la route répond pareil dans les deux cas,
        pour ne pas dire qui est inscrit."""
        compte = await self._par_email(conn, email)
        if compte is None or compte.verifie:
            return None
        return compte, await self._poser_code(conn, compte.id)

    async def verifier(
        self, conn: psycopg.AsyncConnection, *, email: str, code: str
    ) -> Compte | None:
        """Marque le compte vérifié si le code est bon — None sinon.

        Chaque essai compte : au-delà du plafond, le code est mort même s'il
        est juste, et il faut en redemander un — c'est ce qui interdit
        l'énumération des six chiffres.
        """
        compte = await self._par_email(conn, email)
        if compte is None:
            return None
        if compte.verifie:
            return compte
        async with conn.cursor() as cur:
            await cur.execute(
                "update visiteur.verification set tentatives = tentatives + 1"
                " where compte_id = %s and expire_le > now()"
                "   and tentatives < %s"
                " returning code",
                (compte.id, CODE_TENTATIVES_MAX),
            )
            ligne = await cur.fetchone()
            if ligne is None or not hmac.compare_digest(ligne[0], code.strip()):
                return None
            await cur.execute(
                "update visiteur.compte set email_verifie_le = now() where id = %s",
                (compte.id,),
            )
            await cur.execute(
                "delete from visiteur.verification where compte_id = %s", (compte.id,)
            )
        return Compte(
            id=compte.id, pseudo=compte.pseudo, email=compte.email, genre=compte.genre, verifie=True
        )

    # --- connexion ----------------------------------------------------------

    async def connecter(
        self, conn: psycopg.AsyncConnection, *, email: str, mot_de_passe: str
    ) -> Compte | None:
        """Le compte si l'email ET le mot de passe correspondent — None sinon,
        sans distinguer lequel des deux a échoué."""
        email = email.strip().lower()
        async with conn.cursor() as cur:
            await cur.execute(
                "select id, pseudo, genre, email_verifie_le, mot_de_passe"
                " from visiteur.compte where email = %s",
                (email,),
            )
            ligne = await cur.fetchone()
        if ligne is None:
            # Un hachage à vide pour que « email inconnu » et « mauvais mot de
            # passe » prennent le même temps.
            verifier_mot_de_passe(mot_de_passe, hacher("leurre"))
            return None
        compte_id, pseudo, genre, verifie_le, hache = ligne
        if not verifier_mot_de_passe(mot_de_passe, hache):
            return None
        return Compte(
            id=str(compte_id),
            pseudo=pseudo,
            email=email,
            genre=genre,
            verifie=verifie_le is not None,
        )

    async def rattacher_session(
        self, conn: psycopg.AsyncConnection, session_id: str, compte_id: str
    ) -> None:
        """La session anonyme devient celle du compte — ses classements avec."""
        async with conn.cursor() as cur:
            await cur.execute(
                "update visiteur.session set compte_id = %s where id = %s",
                (compte_id, session_id),
            )

    async def detacher_session(self, conn: psycopg.AsyncConnection, session_id: str) -> None:
        async with conn.cursor() as cur:
            await cur.execute(
                "update visiteur.session set compte_id = null where id = %s", (session_id,)
            )

    async def pour_session(self, conn: psycopg.AsyncConnection, session_id: str) -> Compte | None:
        """Le compte rattaché à cette session, s'il y en a un."""
        async with conn.cursor() as cur:
            await cur.execute(
                "select c.id, c.pseudo, c.email, c.genre, c.email_verifie_le"
                " from visiteur.session s join visiteur.compte c on c.id = s.compte_id"
                " where s.id = %s",
                (session_id,),
            )
            ligne = await cur.fetchone()
        if ligne is None:
            return None
        compte_id, pseudo, email, genre, verifie_le = ligne
        return Compte(
            id=str(compte_id),
            pseudo=pseudo,
            email=email,
            genre=genre,
            verifie=verifie_le is not None,
        )

    async def _par_email(self, conn: psycopg.AsyncConnection, email: str) -> Compte | None:
        async with conn.cursor() as cur:
            await cur.execute(
                "select id, pseudo, genre, email_verifie_le from visiteur.compte where email = %s",
                (email.strip().lower(),),
            )
            ligne = await cur.fetchone()
        if ligne is None:
            return None
        compte_id, pseudo, genre, verifie_le = ligne
        return Compte(
            id=str(compte_id),
            pseudo=pseudo,
            email=email.strip().lower(),
            genre=genre,
            verifie=verifie_le is not None,
        )

    # --- les fives ----------------------------------------------------------

    async def fives(
        self, conn: psycopg.AsyncConnection, compte_id: str, univers_interne: str
    ) -> list[dict[str, Any]]:
        """Les cinq rangs de l'univers, hydratés pour l'affichage — les rangs
        vides n'apparaissent pas, le front dessine les cases manquantes."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                select f.rang, f.oeuvre_id,
                       coalesce(tv.id, mv.id, lv.id),
                       coalesce(tv.name, mv.name, lv.name, o.titre),
                       nullif(coalesce(tv.poster_path, mv.poster_path, lv.poster_path), ''),
                       coalesce(extract(year from tv.first_air_date)::int,
                                extract(year from mv.first_air_date)::int,
                                extract(year from lv.first_air_date)::int, o.annee)
                from visiteur.five f
                join sourcing.oeuvre o on o.id = f.oeuvre_id
                left join admin.tv_card tv    on f.univers = 'series' and tv.id = o.id_tmdb
                left join admin.movie_card mv on f.univers = 'movies' and mv.id = o.id_tmdb
                left join admin.livre_card lv on f.univers = 'livres' and lv.id = o.id
                where f.compte_id = %s and f.univers = %s
                order by f.rang
                """,
                (compte_id, univers_interne),
            )
            lignes = await cur.fetchall()
        return [
            {
                "rang": rang,
                "oeuvreId": oeuvre_id,
                "id": vignette,
                "titre": titre,
                "affiche": affiche,
                "annee": annee,
            }
            for rang, oeuvre_id, vignette, titre, affiche, annee in lignes
        ]

    async def poser_five(
        self,
        conn: psycopg.AsyncConnection,
        compte_id: str,
        *,
        univers_interne: str,
        rang: int,
        oeuvre_id: int,
    ) -> None:
        """Pose l'œuvre au rang — et la retire d'abord de son ancien rang si
        elle y était : déplacer un five est un geste, pas une erreur."""
        async with conn.cursor() as cur:
            await cur.execute(
                "delete from visiteur.five"
                " where compte_id = %s and univers = %s and oeuvre_id = %s",
                (compte_id, univers_interne, oeuvre_id),
            )
            await cur.execute(
                "insert into visiteur.five (compte_id, univers, rang, oeuvre_id)"
                " values (%s, %s, %s, %s)"
                " on conflict (compte_id, univers, rang) do update"
                "   set oeuvre_id = excluded.oeuvre_id, creation = now()",
                (compte_id, univers_interne, rang, oeuvre_id),
            )

    async def retirer_five(
        self,
        conn: psycopg.AsyncConnection,
        compte_id: str,
        *,
        univers_interne: str,
        rang: int,
    ) -> None:
        async with conn.cursor() as cur:
            await cur.execute(
                "delete from visiteur.five where compte_id = %s and univers = %s and rang = %s",
                (compte_id, univers_interne, rang),
            )
