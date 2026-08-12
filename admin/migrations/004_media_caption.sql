-- Les légendes visuelles : ce que le modèle de vision « voit » dans les images
-- officielles d'une série — backdrops de la fiche, stills d'épisodes.
--
-- Pourquoi dans `notation` et pas dans `sourcing` : les chemins d'images sont
-- déjà dans le brut (l'append_to_response des fiches et des saisons collecte
-- `images`), et une légende n'est pas une donnée de source — c'est une lecture
-- par LLM, de la matière de notation dérivée, exactement comme un score. Et
-- l'admin n'écrit jamais dans `sourcing`.
--
-- Une ligne par (série, url), **figée** : la légende est payée une fois puis
-- relue telle quelle par le constructeur de dossier — c'est ce qui garde
-- l'empreinte sha256 du dossier stable d'une notation à l'autre. Re-légender
-- une image existante n'est pas prévu : si le besoin arrive, il passera par
-- une suppression explicite, pas par un écrasement silencieux.

create table notation.media_caption (
    -- Sans clé étrangère : la migration 012 la remplace par `oeuvre_id`, qui la
    -- porte. Voir 003_notation.sql pour le raisonnement.
    id_tmdb integer not null,
    url     text    not null,             -- l'image exacte qui a été lue
    kind    text    not null,             -- backdrop | still
    label   text    not null default '',  -- 'backdrop 1' | 'S01E03' — l'étiquette du dossier
    caption text    not null,             -- une ligne anglaise : lumière, ambiance, sujets
    modele  text    not null,             -- provenance, comme sur notation.score

    captioned_at timestamptz not null default now(),

    primary key (id_tmdb, url)
);

comment on table notation.media_caption is
    'Légendes des visuels officiels (vision LLM), figées : le dossier de notation les relit sans jamais repayer l''appel.';
comment on column notation.media_caption.label is
    'L''étiquette sous laquelle la ligne apparaît dans la section MEDIA du dossier. Zéro-paddée (S01E03) pour que l''ordre lexicographique soit l''ordre de diffusion.';

-- Le dossier lit « toutes les légendes d'une série, dans un ordre stable ».
create index media_caption_dossier_idx on notation.media_caption (id_tmdb, kind, label, url);
