-- Des TOP 5 en nombre libre — dont UN est « le TOP 5 de ma vie ».
--
-- Le modèle vie/moment (migration 003) était trop rigide : on crée autant de
-- TOP 5 qu'on veut, on les nomme, et on en promeut un seul au rang de « TOP
-- 5 de ma vie ». C'est exactement le modèle de la V1 (membre.five, avec son
-- titre, et membre.five_position) — la V2 le retrouve pour ses comptes.
--
-- La table plate visiteur.five (compte, univers, liste, rang, œuvre) devient
-- deux tables : le palmarès (l'objet qu'on nomme et qu'on promeut) et ses
-- positions. Les fives déjà posés migrent : la liste 'vie' devient LE
-- palmarès de ma vie, la liste 'moment' un palmarès ordinaire.

create table visiteur.palmares (
    id        uuid        primary key default gen_random_uuid(),
    compte_id uuid        not null references visiteur.compte (id) on delete cascade,
    univers   text        not null,
    -- Le nom que son auteur lui donne — nul : le front affiche le générique.
    titre     text        check (length(titre) between 1 and 80),
    -- « Le TOP 5 de ma vie » : un seul par univers, l'index partiel le tient.
    vie       boolean     not null default false,
    creation  timestamptz not null default now()
);

create unique index palmares_vie_unique
    on visiteur.palmares (compte_id, univers) where vie;

create index palmares_compte_idx on visiteur.palmares (compte_id, univers);

comment on table visiteur.palmares is
    'Un TOP 5 d''un compte : nommé, par univers — et UN d''entre eux est '
    '« le TOP 5 de ma vie » (vie = true, unique par univers).';

create table visiteur.palmares_position (
    palmares_id uuid        not null references visiteur.palmares (id) on delete cascade,
    rang        int         not null check (rang between 1 and 5),
    oeuvre_id   bigint      not null references sourcing.oeuvre (id) on delete cascade,
    creation    timestamptz not null default now(),
    primary key (palmares_id, rang),
    unique (palmares_id, oeuvre_id)
);

-- La reprise : un palmarès par (compte, univers, liste) qui avait des rangs.
with groupes as (
    select distinct compte_id, univers, liste from visiteur.five
), crees as (
    insert into visiteur.palmares (compte_id, univers, vie)
    select compte_id, univers, liste = 'vie' from groupes
    returning id, compte_id, univers, vie
)
insert into visiteur.palmares_position (palmares_id, rang, oeuvre_id, creation)
select c.id, f.rang, f.oeuvre_id, f.creation
from visiteur.five f
join crees c on c.compte_id = f.compte_id
           and c.univers = f.univers
           and c.vie = (f.liste = 'vie');

drop table visiteur.five;
