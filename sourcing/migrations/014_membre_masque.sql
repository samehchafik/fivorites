-- Les membres venus de la V1 sont masqués : leurs citations comptent, eux ne
-- paraissent pas.
--
-- LE FAIT QUI COMMANDE : 69 355 personnes sont entrées en V2 sans l'avoir
-- demandé. Elles se sont inscrites sur un autre site, il y a cinq à huit ans,
-- et 37 006 d'entre elles n'ont même jamais créé de compte. Leur donner une
-- page publique en V2 serait republier des gens sans leur accord.
--
-- Ce qu'on garde d'elles est ailleurs, et c'est tout ce qui nous intéresse :
-- le voisinage five → personne → five → personne (doc/migration-v1-v2.md §6).
-- Ce voisinage n'a besoin d'aucune identité — deux membres qui citent la même
-- œuvre sont voisins, que l'on sache leur nom ou non. Le graphe ne porte donc
-- qu'un identifiant interne, jamais un pseudo ni une adresse.
--
-- LE DÉFAUT EST `true`, ET C'EST DÉLIBÉRÉ. Un défaut à `false` ferait d'un
-- oubli une publication : la prochaine table alimentée, le prochain import,
-- rendraient des gens visibles sans que personne l'ait décidé. À l'envers,
-- l'oubli ne coûte qu'une absence — visible dans l'administration, rattrapable
-- d'un `update`. Le jour où la V2 aura des inscriptions, c'est le code
-- d'inscription qui dira explicitement `masque = false`.

alter table membre.membre
    add column masque boolean not null default true;

comment on column membre.membre.masque is
    'Ne paraît jamais côté public. Vrai pour tout ce qui vient de la V1.';

-- Le chemin de lecture du site public est cet index : il ne porte que les
-- membres visibles, donc aujourd'hui aucun. Un index partiel plutôt qu'un
-- index complet sur un booléen à 100 % vrai — ce dernier ne servirait jamais.
create index membre_visible_idx on membre.membre (id) where not masque;


-- LES DEUX PORTES DU CÔTÉ PUBLIC.
--
-- Un drapeau qu'il faut penser à filtrer finit par ne pas l'être : il suffit
-- d'une requête écrite un soir. Ces vues existent pour que le code public
-- n'ait jamais à y penser — il lit `membre.public_*`, jamais les tables. Une
-- requête publique qui viserait la table directement se verra en revue de
-- code, ce qu'un `where` oublié ne fait pas.
--
-- L'administration, elle, continue de lire les tables : c'est son métier de
-- voir ce qui est masqué, et de savoir qu'il l'est.

create view membre.public_membre as
    select id, pseudo, profil, creation
      from membre.membre
     where not masque and valide and not bani;

comment on view membre.public_membre is
    'Les membres que le site a le droit de montrer. Le public lit cette vue.';

-- Un top n'apparaît pas sans son auteur : le montrer en masquant seulement le
-- nom ne masque rien du tout, puisqu'un top de cinq œuvres est déjà signant.
create view membre.public_five as
    select f.id, f.membre_id, f.univers, f.periode, f.titre, f.creation,
           f.derniere_maj
      from membre.five f
      join membre.public_membre m on m.id = f.membre_id
     where f.valide and f.visibilite = 'public';

comment on view membre.public_five is
    'Les tops publiables : ceux d''un membre visible. Le public lit cette vue.';
