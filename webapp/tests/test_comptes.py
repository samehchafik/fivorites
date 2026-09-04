"""Le cycle de compte, de bout en bout, sur les routes.

Un faux courriel CAPTURE les codes au lieu de les envoyer : le test joue le
parcours réel — s'inscrire, recevoir le code, le donner, être connecté — et
les fives derrière, qui exigent ce parcours.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from fiv_webapp.app import create_app
from fiv_webapp.comptes import generer_code, hacher, verifier_mot_de_passe
from fiv_webapp.config import Settings
from fiv_webapp.deps import obtenir_conn, obtenir_courriel, obtenir_signaux


class FauxCourriel:
    """Capture les codes envoyés — le « courrier » du test."""

    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    @property
    def configure(self) -> bool:
        return True

    async def envoyer_code(self, email: str, pseudo: str, code: str, langue: str = "fr") -> None:
        self.codes[email] = code


class FauxeBase:
    """Une base en mémoire qui joue `visiteur.compte`, `verification`,
    `session` et `five` — le SQL des méthodes de `Comptes` est simple et
    chaque requête se reconnaît à sa table."""

    def __init__(self) -> None:
        self.comptes: dict[str, dict[str, Any]] = {}
        self.verifs: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, str | None] = {}
        self.fives: dict[tuple[str, str, int], int] = {}
        self._resultat: list[tuple] = []

    def cursor(self) -> Any:
        return self

    async def __aenter__(self) -> FauxeBase:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, requete: str, parametres: tuple = ()) -> None:
        self._resultat = []
        r = " ".join(requete.split())
        if r.startswith("insert into visiteur.session"):
            sid = f"session-{len(self.sessions) + 1}"
            self.sessions[sid] = None
            self._resultat = [(sid,)]
        elif r.startswith("select 1 from visiteur.session"):
            if parametres and parametres[0] in self.sessions:
                self._resultat = [(1,)]
        elif r.startswith("update visiteur.session set derniere_activite"):
            pass
        elif r.startswith("select 1 from visiteur.compte"):
            if any(c["email"] == parametres[0] for c in self.comptes.values()):
                self._resultat = [(1,)]
        elif r.startswith("insert into visiteur.compte"):
            pseudo, email, hache, genre = parametres
            cid = f"compte-{len(self.comptes) + 1}"
            self.comptes[cid] = {
                "pseudo": pseudo,
                "email": email,
                "hache": hache,
                "genre": genre,
                "verifie_le": None,
                "avatar": None,
            }
            self._resultat = [(cid,)]
        elif r.startswith("insert into visiteur.verification"):
            cid, code, _minutes = parametres
            self.verifs[cid] = {"code": code, "tentatives": 0}
        elif r.startswith("update visiteur.verification"):
            cid, plafond = parametres
            v = self.verifs.get(cid)
            if v is not None and v["tentatives"] < plafond:
                v["tentatives"] += 1
                self._resultat = [(v["code"],)]
        elif r.startswith("update visiteur.compte set email_verifie_le"):
            self.comptes[parametres[0]]["verifie_le"] = "now"
        elif r.startswith("delete from visiteur.verification"):
            self.verifs.pop(parametres[0], None)
        elif r.startswith("select id, pseudo, genre, email_verifie_le, mot_de_passe"):
            for cid, c in self.comptes.items():
                if c["email"] == parametres[0]:
                    self._resultat = [
                        (cid, c["pseudo"], c["genre"], c["verifie_le"], c["hache"], c["avatar"])
                    ]
        elif r.startswith("select id, pseudo, genre, email_verifie_le, avatar"):
            for cid, c in self.comptes.items():
                if c["email"] == parametres[0]:
                    self._resultat = [(cid, c["pseudo"], c["genre"], c["verifie_le"], c["avatar"])]
        elif (
            r.startswith("update visiteur.compte set pseudo")
            or r.startswith("update visiteur.compte set")
            and "returning pseudo, avatar, genre" in r
        ):
            pseudo, av1, _av2, _av3, genre, cid = parametres
            c = self.comptes[cid]
            if pseudo is not None:
                c["pseudo"] = pseudo
            if av1 is not None:
                c["avatar"] = None if av1 == "" else av1
            if genre is not None:
                c["genre"] = genre
            self._resultat = [(c["pseudo"], c["avatar"], c["genre"])]
        elif r.startswith("update visiteur.session set compte_id = %s"):
            self.sessions[parametres[1]] = parametres[0]
        elif r.startswith("update visiteur.session set compte_id = null"):
            self.sessions[parametres[0]] = None
        elif r.startswith("select c.id, c.pseudo, c.email, c.genre, c.email_verifie_le"):
            cid = self.sessions.get(parametres[0])
            if cid and cid in self.comptes:
                c = self.comptes[cid]
                self._resultat = [
                    (cid, c["pseudo"], c["email"], c["genre"], c["verifie_le"], c["avatar"])
                ]
        elif r.startswith(
            "delete from visiteur.five where compte_id = %s and univers = %s"
            " and liste = %s and oeuvre_id"
        ):
            cid, univers, liste, oeuvre = parametres
            for cle in [
                k
                for k, v in self.fives.items()
                if k[0] == cid and k[1] == univers and k[2] == liste and v == oeuvre
            ]:
                del self.fives[cle]
        elif r.startswith("insert into visiteur.five"):
            cid, univers, liste, rang, oeuvre = parametres
            self.fives[(cid, univers, liste, rang)] = oeuvre
        elif r.startswith(
            "delete from visiteur.five where compte_id = %s and univers = %s"
            " and liste = %s and rang"
        ):
            self.fives.pop((parametres[0], parametres[1], parametres[2], parametres[3]), None)
        elif "from membre.five f" in r:
            # Les fives de la communauté : la vraie table n'existe pas ici —
            # un five anonyme suffit à verrouiller la forme de la réponse.
            self._resultat = [
                (
                    "five-v1",
                    "Mes séries cultes",
                    "life",
                    "ancien",
                    True,
                    1,
                    42,
                    999,
                    "Œuvre 42",
                    None,
                    2015,
                ),
                (
                    "five-v1",
                    "Mes séries cultes",
                    "life",
                    "ancien",
                    True,
                    2,
                    43,
                    998,
                    "Œuvre 43",
                    None,
                    2016,
                ),
            ]
        elif "from visiteur.five f" in r:
            cid, univers, liste = parametres
            self._resultat = [
                (rang, oeuvre, oeuvre - 1000, f"Œuvre {oeuvre}", None, 2020)
                for (c, u, li, rang), oeuvre in sorted(self.fives.items())
                if c == cid and u == univers and li == liste
            ]

    async def fetchone(self):
        return self._resultat[0] if self._resultat else None

    async def fetchall(self):
        return self._resultat


class SignauxFeints:
    def __init__(self) -> None:
        self.poses: list[tuple] = []

    async def session_existe(self, conn: Any, session_id: str) -> bool:
        return True

    async def creer_session(self, conn: Any) -> str:
        return "session-test"

    async def poser(self, conn: Any, session_id: str, **kwargs: Any) -> None:
        self.poses.append((session_id, kwargs))


@pytest.fixture
def monde() -> tuple[TestClient, FauxCourriel, FauxeBase, SignauxFeints]:
    app = create_app(Settings(secret_key="pour-les-tests"))
    base = FauxeBase()
    courriel = FauxCourriel()
    signaux = SignauxFeints()
    app.dependency_overrides[obtenir_conn] = lambda: base
    app.dependency_overrides[obtenir_courriel] = lambda: courriel
    app.dependency_overrides[obtenir_signaux] = lambda: signaux
    return TestClient(app), courriel, base, signaux


def test_hachage_scrypt_aller_retour() -> None:
    hache = hacher("mon mot de passe")
    assert hache.startswith("scrypt$")
    assert verifier_mot_de_passe("mon mot de passe", hache)
    assert not verifier_mot_de_passe("un autre", hache)


def test_generer_code_six_chiffres() -> None:
    assert all(len(generer_code()) == 6 and generer_code().isdigit() for _ in range(20))


class TestCycleComplet:
    def test_inscrire_verifier_et_poser_un_five(self, monde) -> None:
        client, courriel, base, signaux = monde

        # Les fives sans compte : le 401 qui ouvre la modale.
        refus = client.get("/api/public/fives?univers=series")
        assert refus.status_code == 401
        assert refus.json()["detail"]["raison"] == "connexion_requise"

        # L'inscription envoie un code…
        r = client.post(
            "/api/public/compte/inscrire",
            json={
                "pseudo": "Amina",
                "email": "Amina@Exemple.FR",
                "motDePasse": "un mot de passe",
                "genre": "fille",
            },
        )
        assert r.status_code == 200
        assert "amina@exemple.fr" in courriel.codes  # l'adresse est normalisée

        # …un mauvais code est refusé, le bon vérifie ET connecte.
        assert client.post(
            "/api/public/compte/verifier", json={"email": "amina@exemple.fr", "code": "000000"}
        ).status_code in (400,)
        bon = courriel.codes["amina@exemple.fr"]
        r = client.post(
            "/api/public/compte/verifier", json={"email": "amina@exemple.fr", "code": bon}
        )
        assert r.status_code == 200
        assert r.json()["compte"]["pseudo"] == "Amina"
        assert r.json()["compte"]["verifie"] is True

        # La session porte le compte : GET /compte le dit.
        r = client.get("/api/public/compte")
        assert r.json()["compte"]["email"] == "amina@exemple.fr"

        # Les fives s'ouvrent, se posent — et posent le signal « aime ».
        r = client.post(
            "/api/public/fives", json={"univers": "series", "rang": 1, "oeuvreId": 4280}
        )
        assert r.status_code == 200
        assert signaux.poses and signaux.poses[0][1]["statut"] == "aime"
        r = client.get("/api/public/fives?univers=series")
        assert [f["rang"] for f in r.json()["items"]] == [1]

        # Le top du moment est un palmarès à part : y poser la même œuvre ne
        # touche pas au TOP 5 de ma vie.
        r = client.post(
            "/api/public/fives",
            json={"univers": "series", "liste": "moment", "rang": 2, "oeuvreId": 4280},
        )
        assert r.status_code == 200
        assert [
            f["rang"] for f in client.get("/api/public/fives?univers=series").json()["items"]
        ] == [1]
        moment = client.get("/api/public/fives?univers=series&liste=moment").json()
        assert [f["rang"] for f in moment["items"]] == [2]
        assert moment["liste"] == "moment"
        # Une liste inconnue : 400, pas un palmarès fantôme.
        assert client.get("/api/public/fives?univers=series&liste=annee").status_code == 400

        # Le profil se modifie : avatar posé, pseudo gardé.
        r = client.patch("/api/public/compte", json={"avatar": "🦊"})
        assert r.status_code == 200
        assert r.json()["compte"]["avatar"] == "🦊"
        assert r.json()["compte"]["pseudo"] == "Amina"

        # Les fives de la communauté : publics, anonymes (membres masqués).
        r = client.get("/api/public/fives/communaute?univers=series")
        assert r.status_code == 200
        vitrine = r.json()["items"]
        assert vitrine and vitrine[0]["pseudo"] is None
        assert vitrine[0]["titre"] == "Mes séries cultes"
        assert [o["rang"] for o in vitrine[0]["oeuvres"]] == [1, 2]

        # Retirer, lister : vide — le moment, lui, ne bouge pas.
        assert client.delete("/api/public/fives/series/vie/1").status_code == 200
        assert client.get("/api/public/fives?univers=series").json()["items"] == []
        assert client.delete("/api/public/fives/series/moment/2").status_code == 200

    def test_connexion_apres_coup(self, monde) -> None:
        client, courriel, base, _ = monde
        client.post(
            "/api/public/compte/inscrire",
            json={"pseudo": "Sam", "email": "sam@exemple.fr", "motDePasse": "huit car."},
        )
        code = courriel.codes["sam@exemple.fr"]
        client.post("/api/public/compte/verifier", json={"email": "sam@exemple.fr", "code": code})
        client.post("/api/public/compte/deconnecter")
        assert client.get("/api/public/compte").json()["compte"] is None

        # Mauvais mot de passe : 401 indistinct. Bon : reconnecté.
        assert (
            client.post(
                "/api/public/compte/connecter",
                json={"email": "sam@exemple.fr", "motDePasse": "faux"},
            ).status_code
            == 401
        )
        r = client.post(
            "/api/public/compte/connecter",
            json={"email": "sam@exemple.fr", "motDePasse": "huit car."},
        )
        assert r.json()["compte"]["pseudo"] == "Sam"

    def test_connexion_avant_verification_relance_le_code(self, monde) -> None:
        client, courriel, base, _ = monde
        client.post(
            "/api/public/compte/inscrire",
            json={"pseudo": "Lou", "email": "lou@exemple.fr", "motDePasse": "huit car."},
        )
        premier = courriel.codes["lou@exemple.fr"]
        r = client.post(
            "/api/public/compte/connecter",
            json={"email": "lou@exemple.fr", "motDePasse": "huit car."},
        )
        assert r.json() == {"verificationRequise": True, "email": "lou@exemple.fr"}
        assert courriel.codes["lou@exemple.fr"] != premier  # un nouveau code est parti
