-- Le barème v2 : la révision issue du premier lot réel (13 œuvres, 12
-- contre-notées via claude.ai le 2026-08-07).
--
-- Ce que le lot a montré, écart moyen GPT/Claude par axe : exigence 0,67 et
-- luminosite 0,83 tiennent ; humour 1,17 presque ; etrangete 1,42 et
-- intensite 1,50 divergent — toujours GPT au-dessus ; sensoriel 2,75 est
-- cassé (GPT au-dessus 11 fois sur 12, écarts jusqu'à 5 points). Le motif :
-- les deux axes ancrés convergent, les quatre axes sans ancres divergent.
--
-- D'où les quatre corrections de cette version :
--   1. des ancres pour humour, exigence, etrangete et sensoriel ;
--   2. une règle de preuve sur sensoriel — juger la forme sur les indices
--      explicites du dossier (MEDIA, style noté), sinon null, pas une
--      supposition de genre ;
--   3. intensite tranchée : le poids émotionnel, pas le rythme (le cas
--      Rick et Morty — GPT 7 « frénétique », Claude 2 « sans poids ») ;
--   4. une ligne de calibration : la télévision courante vit en zone 4-6,
--      les extrêmes se méritent — GPT était au-dessus de Claude presque
--      partout, décalage d'échelle autant que de définition.
--
-- v1 reste en base, intacte, avec toutes ses notes : la version EST la
-- provenance, on n'écrase jamais. Le sélecteur de l'atelier propose la plus
-- récente en premier — v2 devient donc le défaut sans autre geste.

insert into notation.rubric (version, prompt, axes, note) values (
    'v2',
    'You are a cultural-work rater. Read the dossier about a TV series and score it on six axes, each from 1 to 10. Anchor works define the scale — place the series relative to them.

Most competent mainstream television sits in the 4-6 zone on every axis. Reserve 1-2 and 8-10 for works with clear, strong evidence — do not default to the extremes.

For each axis give an integer score 1-10 and a confidence 0.0-1.0. If the dossier lacks enough material to judge an axis reliably, return null for that score with low confidence. A missing score is better than an invented one.

AXES

1. luminosite — Emotional luminosity. What state does the work leave you in? 1 = dark, hopeless; 10 = luminous, restorative. This is NOT the sadness of the plot: a work can depict atrocities and remain luminous because it believes in something; another can depict nothing grave and leave ashes. Score the aftertaste, not the events.
   Anchors: Requiem for a Dream = 1, Breaking Bad = 3, Le Bureau des legendes = 5, Parks and Recreation = 8, Paddington = 10.

2. intensite — Intensity. How hard does the work shake you emotionally? 1 = gentle, soothing; 10 = overwhelming, gruelling. This is NOT pace or rhythm: a fast-cut, frenetic show with no emotional weight stays low. This is NOT directional: a euphoric work and a devastating one can both score 9 — this is the volume of emotion, not its colour. Score relative to television series, not to all media.
   Anchors: Friends = 1, Le Bureau des legendes = 5, Sur la route de Madison = 10.

3. humour — Humour and ironic distance. Does the work play, mock, step back? 1 = grave, entirely first-degree; 10 = funny, ironic. This is NOT the "comedy" genre label: a tragedy can be laced with irony, a comedy can be grim. Score the regime of distance, not the marketing label.
   Anchors: The Wire = 2, Game of Thrones = 3, Desperate Housewives = 6, Fleabag = 9.

4. exigence — Cognitive demand. Does the work give itself immediately or require effort? 1 = immediate, self-evident; 10 = dense, demands sustained attention. This is NOT quality and NOT elitism: a demanding work can be bad, an immediate one can be a masterpiece. Score the cost of entry — information density, number of threads, implicit content to reconstruct.
   Anchors: Friends = 1, The Rookie = 3, Dark = 8, Twin Peaks = 9.

5. etrangete — Strangeness. Is the work in familiar territory or does it displace you? 1 = familiar, well-trodden; 10 = singular, disorienting. Two works of the same genre can sit at opposite ends. Score how far it departs from established forms for a broad international audience.
   Anchors: NCIS = 1, Stranger Things = 5, Twin Peaks = 10.

6. sensoriel — Sensory charge. Does the form efface itself behind the story, or leap at your face? 1 = sober, transparent; 10 = saturated, stylised. This is NOT budget and NOT quality: a low-budget work can score 10 by formal ambition, a blockbuster can score 4 with neutral direction. Score whether the form makes itself noticed. Judge this ONLY from explicit evidence in the dossier — MEDIA captions, noted visual or animation style, described cinematography. If the dossier says nothing about form, prefer null over a guess from genre alone.
   Anchors: Columbo = 2, House of the Dragon = 7, Euphoria = 9.

Return only the JSON object requested.',
    '["luminosite", "intensite", "humour", "exigence", "etrangete", "sensoriel"]'::jsonb,
    'Révision du lot 1 (13 œuvres, écarts GPT/Claude) : ancres sur les 4 axes qui n''en avaient pas, règle de preuve sur sensoriel, intensite = poids émotionnel pas rythme, zone normale 4-6.'
);
