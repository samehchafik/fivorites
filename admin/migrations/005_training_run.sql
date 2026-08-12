-- Le journal des essais d'entraînement : une ligne par notation de phase 1.
--
-- `notation.score` reste la table de travail — normalisée, un axe par ligne,
-- c'est elle que l'entraînement des poids lit. Mais elle ne garde du prompt
-- que son empreinte : impossible, trois semaines plus tard, de relire ce qui
-- avait été demandé au juge. Cette table-ci est le journal de bord : le
-- prompt en clair, la fiche brute exacte qui a nourri le dossier, et les deux
-- verdicts côte à côte, tels qu'ils ont été rendus.
--
-- Les deux verdicts n'arrivent pas en même temps : OpenAI répond dans la
-- seconde, la contre-note de claude.ai se fait à la main et revient plus
-- tard — d'où `claude` remplissable après coup, avec son propre horodatage.

create table notation.training_run (
    id bigserial primary key,

    -- Sans clé étrangère : la migration 012 la remplace par `oeuvre_id`, qui la
    -- porte. Voir 003_notation.sql pour le raisonnement.
    id_tmdb       integer not null,
    -- La fiche brute qui a nourri le dossier au moment de l'essai. `set null`
    -- et non cascade : si une purge du brut emportait la fiche, le journal
    -- de l'essai doit survivre — c'est lui, l'historique.
    raw_source_id bigint references sourcing.raw_source (id) on delete set null,

    rubric_version text not null references notation.rubric (version),
    prompt         text not null,           -- en clair : le journal doit se relire
    dossier_sha256 text not null,

    openai jsonb,                           -- {model, scores: {axe: {score, confidence}}}
    claude jsonb,                           -- même forme — Haiku par l'API, ou claude.ai recopié

    created_at timestamptz not null default now(),
    claude_at  timestamptz                  -- quand la contre-note est arrivée
);

comment on table notation.training_run is
    'Journal des essais de phase 1 : prompt en clair, fiche brute référencée, verdicts OpenAI et Claude côte à côte.';
comment on column notation.training_run.claude is
    'Le contre-juge, quel que soit son chemin : Haiku par l''API (immédiat) ou claude.ai recopié à la main (claude_at le date).';

-- « Les essais de cette série, du plus récent au plus ancien » — la lecture
-- de la page Training 1.
create index training_run_work_idx on notation.training_run (id_tmdb, created_at desc);
