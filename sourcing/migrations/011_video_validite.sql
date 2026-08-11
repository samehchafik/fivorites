-- La validité des vidéos : une bande-annonce meurt sans prévenir.
--
-- Une clé YouTube n'est pas une donnée stable. La vidéo est retirée pour
-- droits, passée en privée à la fin d'une campagne promotionnelle, ou la chaîne
-- entière disparaît. Rien ne nous en avertit : la ligne reste en base, la
-- fiche propose un lecteur, et l'utilisateur tombe sur « Cette vidéo n'est plus
-- disponible ». C'est la panne la plus visible qu'un catalogue puisse offrir,
-- et la seule façon de l'éviter est d'aller regarder régulièrement.
--
-- On ne supprime pas les vidéos mortes. Trois raisons : la re-projection
-- depuis le brut les recréerait aussitôt, puisque le payload TMDB les contient
-- toujours ; une vidéo privée redevient parfois publique ; et savoir qu'une
-- bande-annonce a existé puis disparu est une information sur l'œuvre. La
-- ligne reste, marquée.
--
-- `verifiee_le` sépare « jamais vérifiée » de « vérifiée et vivante », ce que
-- `vivante` seule ne peut pas dire — un booléen n'a pas de troisième état
-- utilisable comme date de reprise.

alter table sourcing.video
    add column vivante     boolean,      -- null = jamais vérifiée
    add column statut      integer,      -- le code HTTP de la dernière vérification
    add column verifiee_le timestamptz;

comment on column sourcing.video.vivante is
    'null = jamais vérifiée ; true = lisible ; false = retirée, privée, ou géobloquée.';
comment on column sourcing.video.statut is
    'Code HTTP rendu par l''hébergeur. 200 = lisible ; 401/403 = privée ; 404 = retirée.';

-- La requête de la passe : « les plus anciennement vérifiées d'abord ».
-- `nulls first` met les jamais-vues en tête, ce qui est exactement l'ordre
-- voulu au premier lancement comme après l'arrivée de nouvelles vidéos.
create index video_a_verifier_idx on sourcing.video (verifiee_le nulls first);

-- La fiche ne montre que ce qui se lit — mais une vidéo jamais vérifiée reste
-- montrée : la prudence ne doit pas vider l'onglet le jour de la mise en
-- service, avant que la première passe ait tourné.
create index video_vivante_idx on sourcing.video (id_tmdb, priorite)
    where vivante is not false;
