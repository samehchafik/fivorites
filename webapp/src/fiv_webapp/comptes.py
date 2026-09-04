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
    avatar: str | None = None

    def publique(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pseudo": self.pseudo,
            "email": self.email,
            "genre": self.genre,
            "verifie": self.verifie,
            "avatar": self.avatar,
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
            id=compte.id,
            pseudo=compte.pseudo,
            email=compte.email,
            genre=compte.genre,
            verifie=True,
            avatar=compte.avatar,
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
                "select id, pseudo, genre, email_verifie_le, mot_de_passe, avatar"
                " from visiteur.compte where email = %s",
                (email,),
            )
            ligne = await cur.fetchone()
        if ligne is None:
            # Un hachage à vide pour que « email inconnu » et « mauvais mot de
            # passe » prennent le même temps.
            verifier_mot_de_passe(mot_de_passe, hacher("leurre"))
            return None
        compte_id, pseudo, genre, verifie_le, hache, avatar = ligne
        if not verifier_mot_de_passe(mot_de_passe, hache):
            return None
        return Compte(
            id=str(compte_id),
            pseudo=pseudo,
            email=email,
            genre=genre,
            verifie=verifie_le is not None,
            avatar=avatar,
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
                "select c.id, c.pseudo, c.email, c.genre, c.email_verifie_le, c.avatar"
                " from visiteur.session s join visiteur.compte c on c.id = s.compte_id"
                " where s.id = %s",
                (session_id,),
            )
            ligne = await cur.fetchone()
        if ligne is None:
            return None
        compte_id, pseudo, email, genre, verifie_le, avatar = ligne
        return Compte(
            id=str(compte_id),
            pseudo=pseudo,
            email=email,
            genre=genre,
            verifie=verifie_le is not None,
            avatar=avatar,
        )

    async def _par_email(self, conn: psycopg.AsyncConnection, email: str) -> Compte | None:
        async with conn.cursor() as cur:
            await cur.execute(
                "select id, pseudo, genre, email_verifie_le, avatar"
                " from visiteur.compte where email = %s",
                (email.strip().lower(),),
            )
            ligne = await cur.fetchone()
        if ligne is None:
            return None
        compte_id, pseudo, genre, verifie_le, avatar = ligne
        return Compte(
            id=str(compte_id),
            pseudo=pseudo,
            email=email.strip().lower(),
            genre=genre,
            verifie=verifie_le is not None,
            avatar=avatar,
        )

    # --- le profil ----------------------------------------------------------

    async def modifier(
        self,
        conn: psycopg.AsyncConnection,
        compte: Compte,
        *,
        pseudo: str | None = None,
        avatar: str | None = None,
        genre: str | None = None,
    ) -> Compte:
        """Change ce qui est fourni, rend le compte à jour. `avatar=''`
        efface la pastille (retour à l'initiale du pseudo)."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                update visiteur.compte
                   set pseudo = coalesce(%s, pseudo),
                       avatar = case when %s::text is null then avatar
                                     when %s = '' then null
                                     else %s end,
                       genre  = coalesce(%s, genre)
                 where id = %s
                 returning pseudo, avatar, genre
                """,
                (pseudo, avatar, avatar, avatar, genre, compte.id),
            )
            ligne = await cur.fetchone()
        pseudo_neuf, avatar_neuf, genre_neuf = ligne
        return Compte(
            id=compte.id,
            pseudo=pseudo_neuf,
            email=compte.email,
            genre=genre_neuf,
            verifie=compte.verifie,
            avatar=avatar_neuf,
        )

    # --- les palmarès -------------------------------------------------------

    async def palmares(
        self, conn: psycopg.AsyncConnection, compte_id: str, univers_interne: str
    ) -> list[dict[str, Any]]:
        """Tous les TOP 5 de l'univers, positions hydratées — celui de la
        vie d'abord, puis les autres du plus ancien au plus récent."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                select p.id, p.titre, p.vie,
                       pos.rang, pos.oeuvre_id,
                       coalesce(tv.id, mv.id, lv.id),
                       coalesce(tv.name, mv.name, lv.name, o.titre),
                       nullif(coalesce(tv.poster_path, mv.poster_path, lv.poster_path), ''),
                       coalesce(extract(year from tv.first_air_date)::int,
                                extract(year from mv.first_air_date)::int,
                                extract(year from lv.first_air_date)::int, o.annee)
                from visiteur.palmares p
                left join visiteur.palmares_position pos on pos.palmares_id = p.id
                left join sourcing.oeuvre o on o.id = pos.oeuvre_id
                left join admin.tv_card tv    on p.univers = 'series' and tv.id = o.id_tmdb
                left join admin.movie_card mv on p.univers = 'movies' and mv.id = o.id_tmdb
                left join admin.livre_card lv on p.univers = 'livres' and lv.id = o.id
                where p.compte_id = %s and p.univers = %s
                order by p.vie desc, p.creation, pos.rang
                """,
                (compte_id, univers_interne),
            )
            lignes = await cur.fetchall()
        retenus: dict[str, dict[str, Any]] = {}
        for pid, titre, vie, rang, oeuvre_id, vignette, nom, affiche, annee in lignes:
            palm = retenus.setdefault(
                str(pid), {"id": str(pid), "titre": titre, "vie": vie, "oeuvres": []}
            )
            if rang is not None:
                palm["oeuvres"].append(
                    {
                        "rang": rang,
                        "oeuvreId": oeuvre_id,
                        "id": vignette,
                        "titre": nom,
                        "affiche": affiche,
                        "annee": annee,
                    }
                )
        return list(retenus.values())

    async def creer_palmares(
        self,
        conn: psycopg.AsyncConnection,
        compte_id: str,
        *,
        univers_interne: str,
        titre: str | None = None,
    ) -> dict[str, Any]:
        """Crée un TOP 5 vide. Le PREMIER d'un univers devient d'office « le
        TOP 5 de ma vie » — c'est le geste fondateur qu'on attend, et les
        suivants naissent ordinaires (promouvables ensuite)."""
        async with conn.cursor() as cur:
            await cur.execute(
                "select 1 from visiteur.palmares where compte_id = %s and univers = %s and vie",
                (compte_id, univers_interne),
            )
            vie = await cur.fetchone() is None
            await cur.execute(
                "insert into visiteur.palmares (compte_id, univers, titre, vie)"
                " values (%s, %s, %s, %s) returning id",
                (compte_id, univers_interne, titre, vie),
            )
            (palmares_id,) = await cur.fetchone()
        return {"id": str(palmares_id), "titre": titre, "vie": vie, "oeuvres": []}

    async def _univers_du_palmares(
        self, conn: psycopg.AsyncConnection, compte_id: str, palmares_id: str
    ) -> str | None:
        """L'univers du palmarès SI ce compte le possède — None sinon. C'est
        la garde de toutes les écritures : pas de palmarès d'autrui."""
        async with conn.cursor() as cur:
            await cur.execute(
                "select univers from visiteur.palmares where id = %s and compte_id = %s",
                (palmares_id, compte_id),
            )
            ligne = await cur.fetchone()
        return ligne[0] if ligne else None

    async def promouvoir_palmares(
        self, conn: psycopg.AsyncConnection, compte_id: str, palmares_id: str
    ) -> bool:
        """En fait « le TOP 5 de ma vie » de son univers — l'ancien roi
        redevient un palmarès ordinaire."""
        univers = await self._univers_du_palmares(conn, compte_id, palmares_id)
        if univers is None:
            return False
        async with conn.cursor() as cur:
            await cur.execute(
                "update visiteur.palmares set vie = false"
                " where compte_id = %s and univers = %s and vie",
                (compte_id, univers),
            )
            await cur.execute(
                "update visiteur.palmares set vie = true where id = %s", (palmares_id,)
            )
        return True

    async def renommer_palmares(
        self,
        conn: psycopg.AsyncConnection,
        compte_id: str,
        palmares_id: str,
        titre: str | None,
    ) -> bool:
        if await self._univers_du_palmares(conn, compte_id, palmares_id) is None:
            return False
        async with conn.cursor() as cur:
            await cur.execute(
                "update visiteur.palmares set titre = %s where id = %s", (titre, palmares_id)
            )
        return True

    async def supprimer_palmares(
        self, conn: psycopg.AsyncConnection, compte_id: str, palmares_id: str
    ) -> bool:
        if await self._univers_du_palmares(conn, compte_id, palmares_id) is None:
            return False
        async with conn.cursor() as cur:
            await cur.execute("delete from visiteur.palmares where id = %s", (palmares_id,))
        return True

    async def poser_position(
        self,
        conn: psycopg.AsyncConnection,
        compte_id: str,
        palmares_id: str,
        *,
        rang: int,
        oeuvre_id: int,
    ) -> str | None:
        """Pose l'œuvre au rang du palmarès — et la retire d'abord de son
        ancien rang du MÊME palmarès si elle y était : déplacer est un geste,
        pas une erreur. Rend l'univers du palmarès (pour le signal), None si
        le palmarès n'est pas à ce compte."""
        univers = await self._univers_du_palmares(conn, compte_id, palmares_id)
        if univers is None:
            return None
        async with conn.cursor() as cur:
            await cur.execute(
                "delete from visiteur.palmares_position where palmares_id = %s and oeuvre_id = %s",
                (palmares_id, oeuvre_id),
            )
            await cur.execute(
                "insert into visiteur.palmares_position (palmares_id, rang, oeuvre_id)"
                " values (%s, %s, %s)"
                " on conflict (palmares_id, rang) do update"
                "   set oeuvre_id = excluded.oeuvre_id, creation = now()",
                (palmares_id, rang, oeuvre_id),
            )
        return univers

    async def retirer_position(
        self, conn: psycopg.AsyncConnection, compte_id: str, palmares_id: str, rang: int
    ) -> bool:
        if await self._univers_du_palmares(conn, compte_id, palmares_id) is None:
            return False
        async with conn.cursor() as cur:
            await cur.execute(
                "delete from visiteur.palmares_position where palmares_id = %s and rang = %s",
                (palmares_id, rang),
            )
        return True

    # --- les fives de la communauté -----------------------------------------

    async def fives_communaute(
        self, conn: psycopg.AsyncConnection, univers_interne: str, *, limite: int = 4
    ) -> list[dict[str, Any]]:
        """Des fives de membres de la V1, tirés au sort — pour montrer, sous
        les siens, ce que la communauté a posé.

        **Anonymes par construction** : l'import V1 a masqué tous les membres
        (colonne `masque`), leur pseudo ne sort donc jamais tant que ce
        drapeau est levé — seul le TITRE que le membre avait donné à son five
        est montré, c'est une œuvre publique. Le tirage est aléatoire : la
        communauté est figée depuis 2019, un ordre fixe montrerait toujours
        les cinq mêmes listes.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                """
                with choisis as (
                    select f.id, f.titre, f.periode, m.pseudo, m.masque
                    from membre.five f
                    join membre.membre m
                      on m.id = f.membre_id and m.valide and not m.bani
                    where f.valide and f.visibilite = 'public'
                      and f.univers = %(univers)s
                    order by random()
                    limit %(limite)s
                )
                select c.id, c.titre, c.periode, c.pseudo, c.masque,
                       p.rang, p.oeuvre_id,
                       coalesce(tv.id, mv.id, lv.id),
                       coalesce(tv.name, mv.name, lv.name, o.titre, p.titre_saisi),
                       nullif(coalesce(tv.poster_path, mv.poster_path,
                                       lv.poster_path), ''),
                       coalesce(extract(year from tv.first_air_date)::int,
                                extract(year from mv.first_air_date)::int,
                                extract(year from lv.first_air_date)::int, o.annee)
                from choisis c
                join membre.five_position p on p.five_id = c.id
                left join sourcing.oeuvre o on o.id = p.oeuvre_id
                left join admin.tv_card tv
                       on %(univers)s = 'series' and tv.id = o.id_tmdb
                left join admin.movie_card mv
                       on %(univers)s = 'movies' and mv.id = o.id_tmdb
                left join admin.livre_card lv
                       on %(univers)s = 'livres' and lv.id = o.id
                order by c.id, p.rang
                """,
                {"univers": univers_interne, "limite": limite},
            )
            lignes = await cur.fetchall()
        fives: dict[Any, dict[str, Any]] = {}
        for ligne in lignes:
            (
                five_id,
                titre,
                periode,
                pseudo,
                masque,
                rang,
                oeuvre_id,
                vignette,
                nom,
                affiche,
                annee,
            ) = ligne
            five = fives.setdefault(
                five_id,
                {
                    "titre": titre,
                    "liste": "moment" if periode == "moment" else "vie",
                    "pseudo": None if masque else pseudo,
                    "oeuvres": [],
                },
            )
            five["oeuvres"].append(
                {
                    "rang": rang,
                    "oeuvreId": oeuvre_id,
                    "id": vignette,
                    "titre": nom,
                    "affiche": affiche,
                    "annee": annee,
                }
            )
        # Un five dont aucune œuvre n'a de nom ne montre rien : écarté.
        return [
            five for five in fives.values() if any(oeuvre["titre"] for oeuvre in five["oeuvres"])
        ]
