"""L'export quotidien de TMDB : la liste de toutes les séries.

TMDB publie chaque jour, vers 08h00 UTC, un fichier gzip contenant une ligne
JSON par série — id, titre original et popularité. Il est public, ne demande
aucune clé, et ne consomme aucun quota d'API.

C'est la seule façon raisonnable de connaître le catalogue : l'alternative
serait de balayer les ids un par un, soit des centaines de milliers de requêtes
pour obtenir une information que ce fichier donne en quelques secondes.
"""

from __future__ import annotations

import gzip
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

import psycopg

from fiv_sourcing.http import HttpFetcher

log = logging.getLogger(__name__)

EXPORT_BASE = "http://files.tmdb.org/p/exports"

# L'univers de ce module. Une constante et non une valeur en dur dans les
# requêtes : le jour où l'export des films arrive, c'est le seul endroit qui
# doit apprendre à en changer, et `grep UNIVERS` donne la liste exacte des
# points à plomber.
UNIVERS = "series"

# Recopie la date de première diffusion du brut vers l'inventaire.
#
# Le garde-fou par expression régulière n'est pas de la superstition : TMDB
# renvoie parfois une chaîne vide, et un cast qui échoue sur **une** ligne
# annulerait la mise à jour des 148 000 autres. `case` écarte ce qui n'est pas
# une date ISO au lieu de faire tomber la transaction.
MAJ_DATES = """
update tmdb_catalog c
set first_air_date = d.date_diffusion
from (
    select distinct on (source_id)
           source_id::int as id,
           case when payload ->> 'first_air_date' ~ '^\\d{4}-\\d{2}-\\d{2}$'
                then (payload ->> 'first_air_date')::date
           end as date_diffusion
    from raw_source
    where source = 'tmdb' and kind = 'tv'
      and http_status between 200 and 299
    order by source_id, fetched_at desc
) d
where c.univers = 'series' and c.id = d.id
  and c.first_air_date is distinct from d.date_diffusion
"""


async def refresh_air_dates(conn) -> int:
    """Remplit `tmdb_catalog.first_air_date` depuis `raw_source`.

    Idempotent, sans réseau, et à relancer après chaque passe de collecte : une
    série fraîchement collectée n'a sa date ici qu'après ce passage.
    """
    async with conn.cursor() as cur:
        await cur.execute(MAJ_DATES)
        return cur.rowcount


# L'export du jour n'est publié qu'en milieu de matinée UTC. Plutôt que
# d'échouer si on demande trop tôt, on remonte de quelques jours : un catalogue
# vieux de 48 h reste une base de sondage parfaitement valable.
FALLBACK_DAYS = 3


class ExportUnavailable(RuntimeError):
    """Aucun export trouvé sur la fenêtre essayée."""


@dataclass(slots=True)
class ExportReport:
    exported_on: date
    url: str
    series_read: int
    inserted: int
    updated: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated


def export_url(day: date) -> str:
    """TMDB nomme ses exports en MM_DD_YYYY — pas en ISO."""
    return f"{EXPORT_BASE}/tv_series_ids_{day:%m_%d_%Y}.json.gz"


def parse_export(blob: bytes) -> Iterator[dict]:
    """Le fichier est du JSON par lignes, pas un tableau JSON.

    On saute les lignes illisibles au lieu d'abandonner : un export tronqué
    reste plus utile qu'aucun catalogue, et le compte final le signalera.
    """
    for line in gzip.decompress(blob).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except ValueError:
            log.warning("ligne d'export illisible, ignorée : %.80s", line)


async def download_export(
    fetcher: HttpFetcher,
    *,
    start: date | None = None,
    strict: bool = False,
    fallback_days: int = FALLBACK_DAYS,
) -> tuple[date, str, bytes]:
    """Télécharge l'export le plus récent disponible.

    `start` est le jour d'où l'on part, aujourd'hui par défaut. `strict` coupe
    le repli : une date demandée explicitement est un ordre, et renvoyer
    l'export de la veille sous une date que l'appelant n'a pas demandée serait
    un mensonge silencieux.
    """
    origin = start or date.today()
    attempts = 1 if strict else fallback_days + 1
    tried: list[str] = []

    for offset in range(attempts):
        current = origin - timedelta(days=offset)
        url = export_url(current)
        status, blob = await fetcher.get_bytes(url, timeout=300.0)
        if status == 200 and blob:
            if offset:
                log.info("export du %s indisponible, repli sur le %s", origin, current)
            return current, url, blob
        tried.append(f"{url} → HTTP {status or 'aucune réponse'}")

    raise ExportUnavailable("aucun export téléchargeable :\n  " + "\n  ".join(tried))


async def load_catalog(
    conn: psycopg.AsyncConnection,
    records: Iterator[dict],
    exported_on: date,
    *,
    univers: str = UNIVERS,
) -> tuple[int, int, int]:
    """Charge l'export dans `tmdb_catalog`. Renvoie (lues, insérées, mises à jour).

    Passe par une table temporaire et un COPY : un `INSERT` ligne à ligne sur
    250 000 séries prendrait des minutes là où celui-ci prend des secondes.
    """
    read = 0
    async with conn.transaction(), conn.cursor() as cur:
        await cur.execute(
            "create temp table tmdb_catalog_load ("
            " id integer, original_name text, popularity real, adult boolean"
            ") on commit drop"
        )

        copy_sql = "copy tmdb_catalog_load (id, original_name, popularity, adult) from stdin"
        async with cur.copy(copy_sql) as copy:
            for record in records:
                identifier = record.get("id")
                if identifier is None:
                    continue
                read += 1
                await copy.write_row(
                    (
                        identifier,
                        record.get("original_name"),
                        float(record.get("popularity") or 0.0),
                        bool(record.get("adult")),
                    )
                )

        # `distinct on` par sécurité : un id en double dans l'export ferait
        # échouer l'upsert avec « ON CONFLICT DO UPDATE ne peut affecter la
        # ligne une seconde fois ».
        # `on conflict (univers, id)` et non `(id)` seul : c'est la clé primaire
        # depuis la migration 012, et c'est ce qui empêche l'export d'un univers
        # d'écraser celui d'un autre. Les identifiants TMDB de films et de
        # séries se chevauchent — l'ancienne forme aurait remplacé Game of
        # Thrones par le film qui porte le numéro 1399.
        await cur.execute(
            """
            insert into sourcing.tmdb_catalog
                   (univers, id, original_name, popularity, adult, exported_on)
            select distinct on (id) %s, id, original_name, popularity, adult, %s
            from tmdb_catalog_load
            order by id
            on conflict (univers, id) do update set
                original_name = excluded.original_name,
                popularity    = excluded.popularity,
                adult         = excluded.adult,
                exported_on   = excluded.exported_on,
                last_seen_at  = now()
            returning (xmax = 0) as est_nouvelle
            """,
            (univers, exported_on),
        )
        flags = [row[0] for row in await cur.fetchall()]

    inserted = sum(flags)
    return read, inserted, len(flags) - inserted


async def refresh_catalog(
    conn: psycopg.AsyncConnection, fetcher: HttpFetcher, day: date | None = None
) -> ExportReport:
    exported_on, url, blob = await download_export(fetcher, start=day, strict=day is not None)
    read, inserted, updated = await load_catalog(conn, parse_export(blob), exported_on)
    return ExportReport(exported_on, url, read, inserted, updated)
