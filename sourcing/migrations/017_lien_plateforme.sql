-- Le répertoire des pages de titre par plateforme.
--
-- TMDB dit QUI diffuse une œuvre, jamais OÙ exactement — l'URL de la page
-- du titre chez Netflix ou Prime est l'actif de JustWatch, absent de l'API.
-- Wikidata, lui, porte ces identifiants en propriétés publiques (P1874
-- Netflix, P8055 Prime Video, P7595/P7596 Disney+, P9586/P9751 Apple TV,
-- P4110 Crunchyroll), indexées par nos clés TMDB (P4947/P4983).
--
-- Cette table est la récolte : un identifiant de titre par (œuvre,
-- plateforme). Le site en fait un lien EXACT (netflix.com/title/…) ; une
-- œuvre absente d'ici garde le lien de recherche — le repli existant.

create table sourcing.lien_plateforme (
    oeuvre_id   bigint      not null references sourcing.oeuvre (id) on delete cascade,
    -- La clé interne de l'enseigne : netflix, prime, disney, apple,
    -- crunchyroll. Le gabarit d'URL vit dans le code du site, pas ici — un
    -- identifiant survit à un changement de format d'URL, pas l'inverse.
    plateforme  text        not null,
    identifiant text        not null,
    maj         timestamptz not null default now(),
    primary key (oeuvre_id, plateforme)
);

comment on table sourcing.lien_plateforme is
    'L''identifiant du titre chez chaque plateforme connue — récolté sur '
    'Wikidata par lots SPARQL (commande liens-plateformes). Le site '
    'construit le lien exact ; sans ligne ici, il retombe sur la recherche.';
