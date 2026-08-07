-- Le journal des poids : une ligne par prompt distinct, la plus récente fait foi.
--
-- `notation.weights` reste la table de travail (une ligne par axe, écrasée à
-- chaque réentraînement) — mais elle ne dit ni pour quel prompt les poids ont
-- été appris, ni ce qu'ils valaient avant. Cette table-ci journalise chaque
-- entraînement en entier : tous les axes dans un seul json, le prompt en
-- clair, l'horodatage qui sert de version.
--
-- Une ligne par prompt (`prompt_sha256` unique) : réentraîner sur le même
-- prompt — plus d'œuvres notées entre-temps — met sa ligne à jour et la
-- redate, donc la remet en tête. La « version par défaut », celle que la
-- phase 2 utilise, est simplement la ligne la plus récente.

create table notation.training_weights (
    id bigserial primary key,

    rubric_version text not null references notation.rubric (version),
    prompt         text not null,          -- en clair, comme dans training_run
    prompt_sha256  text not null unique,   -- une ligne par prompt distinct

    embedder text  not null,               -- ex. text-embedding-3-small@256
    weights  jsonb not null,               -- {axe: {intercept, coef, trainedOn, maeFit}}
    works    integer not null,             -- combien d'œuvres ont nourri l'entraînement

    trained_at timestamptz not null default now()
);

comment on table notation.training_weights is
    'Journal des entraînements de la régression : une ligne par prompt, tous les axes en json. La plus récente est la version par défaut de la phase 2.';
comment on column notation.training_weights.trained_at is
    'La version. Réentraîner le même prompt redate sa ligne — et la remet en tête.';

-- « La version par défaut » : la plus récente, éventuellement par barème.
create index training_weights_recent_idx
    on notation.training_weights (rubric_version, trained_at desc);
