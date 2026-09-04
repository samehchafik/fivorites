-- Deux palmarès par univers, et l'avatar du compte.
--
-- « Le TOP 5 de ma vie » n'est pas le seul geste : la V1 avait déjà le top
-- périodique (periode = 'life' / 'moment' dans membre.five), et le carnet du
-- designer le ramène — « le top du moment ». La colonne `liste` reprend ce
-- vocabulaire, en français comme le reste du schéma : 'vie' ou 'moment'.
-- Les fives déjà posés sont de la vie — c'est ce que l'interface promettait.

alter table visiteur.five
    add column liste text not null default 'vie' check (liste in ('vie', 'moment'));

-- Les clés s'élargissent : un rang (et une œuvre) par liste, plus par univers.
alter table visiteur.five drop constraint five_pkey;
alter table visiteur.five add primary key (compte_id, univers, liste, rang);
alter table visiteur.five drop constraint five_compte_id_univers_oeuvre_id_key;
alter table visiteur.five add unique (compte_id, univers, liste, oeuvre_id);

comment on column visiteur.five.liste is
    'Le palmarès : ''vie'' (le TOP 5 de ma vie) ou ''moment'' (le top du '
    'moment) — les periode life/moment de la V1, pour les comptes V2.';

-- L'avatar : une pastille choisie parmi celles que le site propose (un
-- emoji), modifiable depuis le menu du compte. Nul = l'initiale du pseudo.
alter table visiteur.compte
    add column avatar text check (length(avatar) <= 8);
