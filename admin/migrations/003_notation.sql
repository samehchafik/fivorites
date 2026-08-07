-- Schéma `notation` : la couche 2 — le barème, les notes, les poids.
--
-- Créé par les migrations de l'admin parce que c'est l'admin qui pilote
-- l'entraînement (les pages Training 1 et 2) : le barème s'y édite, les appels
-- LLM s'y déclenchent, les notes s'y lisent. Le schéma reste distinct — le jour
-- où la notation devient un traitement par lots autonome, il part avec elle.
--
-- Le principe, repris de doc/v2-notation-axes.md §4.1 : on ne remplace jamais
-- une note, on en ajoute une nouvelle et on lit la plus récente. C'est ce qui
-- permet de comparer deux barèmes ou deux modèles sans rien perdre.

create schema if not exists notation;


-- Le barème, versionné. Changer une ancre change toutes les notes qui en
-- découlent : la version fait donc partie de la provenance de chaque note.
create table notation.rubric (
    version    text        primary key,          -- 'v1', 'v2-ancres-resserrees'
    prompt     text        not null,             -- la consigne complète envoyée au modèle
    axes       jsonb       not null,             -- ["luminosite", "intensite", ...]
    note       text,
    created_at timestamptz not null default now(),

    constraint rubric_axes_is_array check (jsonb_typeof(axes) = 'array')
);

comment on table notation.rubric is
    'Le barème de notation, versionné. Une note sans version de barème est ininterprétable.';


-- Une ligne par (œuvre, axe, barème, modèle, date). Jamais d''UPDATE : la
-- lecture courante prend la plus récente.
create table notation.score (
    id             bigserial   primary key,
    id_tmdb        integer     not null references sourcing.tmdb_catalog (id),
    axe            text        not null,
    valeur         numeric(3, 1),               -- 1.0 à 10.0 — null = « ne sait pas »
    confiance      numeric(3, 2),               -- 0.00 à 1.00
    rubric_version text        not null references notation.rubric (version),
    modele         text        not null,        -- 'gpt-...', 'claude-haiku-...', 'interne-ridge'
    -- Le texte réellement soumis, et la consigne réellement envoyée : sans ces
    -- deux empreintes, impossible de dire si une divergence vient du modèle,
    -- d'un enrichissement de la source, ou d'un prompt retouché sans être sauvé.
    input_sha256   text        not null,
    prompt_sha256  text        not null,
    scored_at      timestamptz not null default now()
);

comment on table notation.score is
    'Append-only. La note courante d''une œuvre est la plus récente par (axe, modèle, barème).';

-- La lecture courante : « les dernières notes de cette œuvre ».
create index score_courant_idx
    on notation.score (id_tmdb, axe, modele, scored_at desc);

-- L'entraînement des poids : « toutes les notes de ce barème et de ce modèle ».
create index score_entrainement_idx
    on notation.score (rubric_version, modele, id_tmdb);


-- Les poids de la régression interne (phase 2) : un jeu par (barème, axe).
-- Remplacés à chaque réentraînement — contrairement aux notes, un poids
-- intermédiaire n'a pas de valeur d'archive, seule la traçabilité de ce qui a
-- servi à l'entraîner compte.
create table notation.weights (
    rubric_version text        not null references notation.rubric (version),
    axe            text        not null,
    intercept      double precision not null,
    coef           jsonb       not null,        -- les coefficients, dans l'ordre des dimensions
    embedder       text        not null,        -- 'text-embedding-3-small@256'
    trained_on     integer     not null,        -- nombre d'œuvres du jeu d'entraînement
    mae_fit        double precision,            -- écart moyen d'ajustement (in-sample)
    trained_at     timestamptz not null default now(),

    primary key (rubric_version, axe)
);

comment on table notation.weights is
    'La régression interne : axes ≈ intercept + coef · embedding. Réentraînée d''un bloc.';


-- Le cache des embeddings : un vecteur par (œuvre, texte soumis). Le sha de
-- l'entrée fait partie de la clé — si le dossier change, le vecteur est
-- recalculé, jamais réutilisé à tort.
create table notation.embedding (
    id_tmdb      integer     not null references sourcing.tmdb_catalog (id),
    input_sha256 text        not null,
    embedder     text        not null,
    vector       jsonb       not null,
    created_at   timestamptz not null default now(),

    primary key (id_tmdb, input_sha256, embedder)
);


-- Le barème de départ : les six axes du socle (doc/v2-notation-axes.md §2),
-- en anglais — la langue de notation décidée le 2026-08-07. Les ancres sont
-- celles du doc ; elles se raffinent depuis la page Training 1, chaque
-- révision devenant une nouvelle version.
insert into notation.rubric (version, prompt, axes, note) values (
    'v1',
    'You are a cultural-work rater. Read the dossier about a TV series and score it on six axes, each from 1 to 10. Anchor works define the scale — place the series relative to them.

For each axis give an integer score 1-10 and a confidence 0.0-1.0. If the dossier lacks enough material to judge an axis reliably, return null for that score with low confidence. A missing score is better than an invented one.

AXES

1. luminosite — Emotional luminosity. What state does the work leave you in? 1 = dark, hopeless; 10 = luminous, restorative. This is NOT the sadness of the plot: a work can depict atrocities and remain luminous because it believes in something; another can depict nothing grave and leave ashes. Score the aftertaste, not the events.
   Anchors: Requiem for a Dream = 1, Breaking Bad = 3, Le Bureau des legendes = 5, Parks and Recreation = 8, Paddington = 10.

2. intensite — Intensity. How hard does the work shake you? 1 = gentle, soothing; 10 = overwhelming, gruelling. This is NOT directional: a euphoric work and a devastating one can both score 9 — this is the volume of emotion, not its colour. Score relative to television series, not to all media.
   Anchors: Friends = 1, Le Bureau des legendes = 5, Sur la route de Madison = 10.

3. humour — Humour and ironic distance. Does the work play, mock, step back? 1 = grave, entirely first-degree; 10 = funny, ironic. This is NOT the "comedy" genre label: a tragedy can be laced with irony, a comedy can be grim. Score the regime of distance, not the marketing label.

4. exigence — Cognitive demand. Does the work give itself immediately or require effort? 1 = immediate, self-evident; 10 = dense, demands sustained attention. This is NOT quality and NOT elitism: a demanding work can be bad, an immediate one can be a masterpiece. Score the cost of entry — information density, number of threads, implicit content to reconstruct.

5. etrangete — Strangeness. Is the work in familiar territory or does it displace you? 1 = familiar, well-trodden; 10 = singular, disorienting. Two works of the same genre can sit at opposite ends. Score how far it departs from established forms for a broad international audience.

6. sensoriel — Sensory charge. Does the form efface itself behind the story, or leap at your face? 1 = sober, transparent; 10 = saturated, stylised. This is NOT budget and NOT quality: a low-budget work can score 10 by formal ambition, a blockbuster can score 4 with neutral direction. Score whether the form makes itself noticed.

Return only the JSON object requested.',
    '["luminosite", "intensite", "humour", "exigence", "etrangete", "sensoriel"]'::jsonb,
    'Barème de départ — six axes du socle, ancres du doc. À raffiner en Training 1.'
);
