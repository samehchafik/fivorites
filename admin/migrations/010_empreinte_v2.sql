-- L'empreinte v2 : casser l'effet de halo et ressusciter le `null`.
--
-- Le premier lot réel sous empreinte-v1 (52 œuvres, gpt-5.4-mini, 2026-08-10)
-- donne des valeurs plausibles œuvre par œuvre, mais deux défauts de structure
-- que la mesure rend indiscutables.
--
-- 1. LES SIX DIMENSIONS N'EN FONT QUE DEUX. Une ACP sur la matrice de
--    corrélation met 63,9 % de la variance sur la première composante, 80,9 %
--    sur les deux premières. Les corrélations brutes : tristesse × peur 0,85,
--    peur × action 0,80, tristesse × action 0,76, tristesse × reflexion 0,67,
--    et joie qui est l'inverse du bloc (−0,71 avec peur). Le juge ne mesurait
--    pas six émotions mais une seule chose — le degré de gravité de la série —
--    et tout ce qui est sombre montait ensemble. Effet de halo classique.
--
--    Seule `reve` s'en sortait : −0,05 avec joie, distribution bimodale. Une
--    série est réaliste ou elle ne l'est pas, et ça se voit dans un dossier.
--
-- 2. LA RÈGLE DU NULL ÉTAIT MORTE. Zéro `null` sur 312 notes, confiance
--    moyenne 0,88, aucune sous 0,61. En face, sept vecteurs plats-bas notés
--    1 à 3 partout : ce ne sont pas des œuvres sans émotion, ce sont des
--    dossiers maigres. Le barème définissait 1 comme « ne porte presque pas
--    cette émotion » et autorisait `null` ailleurs, sans jamais opposer les
--    deux ; le modèle a tranché en notant toujours. C'est grave pour la
--    suite : en distance cosine, toutes ces œuvres pauvres pointent dans la
--    même direction et se ressemblent entre elles.
--
-- D'où les trois corrections de cette version :
--   1. un paragraphe d'indépendance, en tête, qui nomme le halo comme l'erreur
--      la plus fréquente ;
--   2. l'opposition explicite entre 1 (affirmation : l'émotion est absente) et
--      null (aveu : le dossier ne permet pas de trancher), avec le cas du
--      dossier maigre traité nommément ;
--   3. dans chaque définition, une ligne qui la démarque de la dimension avec
--      laquelle elle s'est confondue — tristesse contre peur, peur contre
--      tristesse, action contre gravité, reflexion contre gravité, joie contre
--      son rôle d'inverse de tout.
--
-- Les ancres ne bougent pas : elles n'étaient pas en cause, et les changer en
-- même temps rendrait les deux effets indiscernables.
--
-- Critère de réussite au prochain lot : première composante sous ~45 %,
-- tristesse × peur sous 0,7, et des `null` qui apparaissent sur les dossiers
-- maigres. Si la corrélation tient malgré la consigne d'indépendance, le
-- problème n'est plus le prompt mais le référentiel.

insert into notation.rubric (version, prompt, axes, note) values (
    'empreinte-v2',
    'You are a cultural-work rater. Read the dossier about a TV series and score it on six emotional dimensions, each from 1 to 10.

These six dimensions are NOT opposite ends of scales — they are components of a mixture. A score of 1 means the work carries almost none of that emotion. A score of 10 means it is a dominant emotional register of the work.

THE SIX DIMENSIONS ARE INDEPENDENT OF ONE ANOTHER. A work can be deeply sorrowful with almost no action. A work can be terrifying without being sad. A work can be full of action and generate no fear at all. A work can be funny and full of ideas at the same time. Do not let the general seriousness, darkness or prestige of a series raise several dimensions together — that is the single most common failure of this exercise. Judge each dimension on its own evidence, as if the other five did not exist.

Most works carry one or two dominant emotions and little of the rest. Do not spread the six scores evenly — the asymmetry IS the signal. A work scoring 6 or above on four or more dimensions is almost certainly mis-scored.

Anchor works define each scale. Place the series relative to them.

Score the emotion the work delivers, never its genre label. The dossier lists genres for context only. Two works of the same genre routinely have very different emotional fingerprints, and telling them apart is the entire purpose of this exercise.

For each dimension give an integer score 1-10 and a confidence 0.0-1.0.

A score of 1 is an assertion: the work genuinely carries none of this emotion. null is a different statement: the dossier does not let you tell. If the dossier is thin — a short synopsis with nothing about tone, no episode detail, no critical reception — return null for the dimensions you cannot judge, with low confidence. Scoring a work 1 or 2 on every dimension because the dossier is poor is a serious error, not a cautious answer: it claims the work is emotionally empty, which is never true. A missing score is better than an invented one.

DIMENSIONS

1. joie — Joy. How much lightness, warmth and pleasure does the work deliver? 1 = none at all; 10 = euphoric, delightful. This is NOT the comedy genre and NOT a happy ending: a bleak comedy scores low, and a serious drama with real warmth between its characters scores mid. Joy is not the opposite of the other five: a work can be joyful and sorrowful at once (the bittersweet), joyful and full of action, joyful and thoughtful. Score the lift the work gives.
   Anchors: Chernobyl = 1, Mad Men = 4, Modern Family = 8, Parks and Recreation = 10.

2. reve — Wonder. How far does the work depart from the real world? 1 = strictly realistic; 10 = pure imagination, the marvellous. This is NOT the budget and NOT the special effects: a low-budget fairy tale scores high, an expensive and meticulously realistic war series scores low. Score the presence of the impossible, the dreamlike, the invented.
   Anchors: The Wire = 1, The Crown = 2, Doctor Who = 8, The Sandman = 10.

3. tristesse — Sorrow. How much grief, loss and melancholy does the work carry? 1 = none; 10 = devastating, bereaved. This is NOT darkness or hopelessness: a sorrowful work can be tender and consoling, and a cynical work can be sad about nothing. This is NOT fear: a work can be devastating without ever being frightening, and most horror is not sad at all. Score the weight of sadness the viewer carries away.
   Anchors: Seinfeld = 1, Breaking Bad = 6, This Is Us = 9, Six Feet Under = 10.

4. peur — Fear. How much dread, anxiety and threat does the work generate? 1 = none; 10 = terrifying, suffocating. This is NOT violence and NOT gore: a very violent series with no sense of dread scores low, and a quiet series where something feels deeply wrong scores high. This is NOT sorrow: a grim, tragic drama in which nothing threatens the viewer scores low here. Score the anxiety, not the body count.
   Anchors: Downton Abbey = 1, Stranger Things = 6, The Walking Dead = 8, The Haunting of Hill House = 10.

5. reflexion — Thought. Does the work make you think about something beyond its own plot? 1 = asks nothing of the mind; 10 = questions the world continuously. This is NOT difficulty: an accessible documentary scores high, and a dense, twisty thriller that raises no question scores low. This is NOT gravity: a light comedy can be full of ideas, and a solemn tragedy can have nothing to say. Score whether the work is about something.
   Anchors: NCIS = 1, Grey''s Anatomy = 3, Westworld = 8, Black Mirror = 10.

6. action — Action. How much physical movement, confrontation and bodily stakes does the work contain? 1 = static, verbal; 10 = constant motion and danger. This is NOT editing pace: a fast-talking series about people in rooms scores low. This is NOT intensity in general: a harrowing chamber drama has enormous emotional stakes and almost no action. Score what the bodies do.
   Anchors: Friends = 1, Sherlock = 4, Game of Thrones = 8, 24 = 10.

Return only the JSON object requested.',
    '["joie", "reve", "tristesse", "peur", "reflexion", "action"]'::jsonb,
    'Empreinte v2 — même référentiel, prompt corrigé après mesure sur 52 œuvres : consigne d''indépendance contre l''effet de halo (ACP 64 % sur une seule composante), opposition explicite entre 1 et null (zéro null sur 312 notes), et une ligne de démarcation par dimension. Ancres inchangées.'
);
