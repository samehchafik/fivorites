-- L'empreinte v3 : les ancres, et rien que les ancres.
--
-- La v2 avait ajouté un paragraphe d'indépendance en majuscules et une ligne
-- de démarcation par dimension. Le modèle l'a lu — 48 œuvres sur 51 renotées,
-- écart moyen 0,4 par dimension — et la structure n'a pas bougé d'un pouce :
-- première composante 63,5 % → 62,7 %, tristesse × peur 0,84 → 0,84.
--
-- On ne supprime pas un effet de halo en demandant à un modèle de ne pas en
-- avoir. Le levier était ailleurs, et il était sous nos yeux.
--
-- LES ANCRES HAUTES ENSEIGNAIENT LA CORRÉLATION QUE LA PROSE INTERDISAIT.
-- `peur` était ancrée à 8 sur The Walking Dead et à 10 sur The Haunting of
-- Hill House : deux séries terrifiantes ET profondément tristes — la seconde
-- est littéralement un récit de deuil familial. Juste au-dessus, la définition
-- affirmait « This is NOT sorrow ». Entre une assertion et un exemple, le
-- modèle suit l'exemple.
--
-- La règle « aucune œuvre ne sert d'ancre à deux dimensions » était respectée
-- à la lettre — aucun titre partagé — mais pas dans l'esprit : ce n'est pas le
-- partage d'un titre qui enseigne la corrélation, c'est l'uniformité de ton du
-- haut de l'échelle.
--
-- Le motif se vérifie sur les six dimensions. Information propre de chacune
-- (part que les cinq autres ne prédisent pas), face à la tonalité de ses
-- ancres hautes :
--
--   reflexion  57 %   NCIS, Grey's, Westworld, Black Mirror     variée
--   reve       53 %   The Wire, The Crown, Doctor Who, Sandman  TRÈS variée
--   action     34 %   Game of Thrones, 24                       tendues, sombres
--   joie       29 %   —
--   tristesse  25 %   Breaking Bad, This Is Us, Six Feet Under  toutes graves
--   peur       16 %   The Walking Dead, Hill House              toutes graves
--
-- Les dimensions dont les ancres hautes sont uniformément sombres sont
-- exactement celles qui se sont effondrées dans le facteur « gravité ». `reve`,
-- dont les ancres vont du polar sinistre au feuilleton joyeux, est la moins
-- corrélée du lot. Le corpus le confirme : zéro série sur 52 avec peur ≥ 6 et
-- joie ≥ 5. Le gore drôle n'existait ni dans les ancres, ni dans les données.
--
-- D'où quatre remplacements, chacun apportant une œuvre qui porte l'émotion
-- dans un registre léger :
--
--   peur       The Walking Dead 8   → American Horror Story 8
--              Stranger Things 6    → Ash vs Evil Dead 6      (gore et comique)
--   tristesse  This Is Us 9         → BoJack Horseman 9       (comédie qui dévaste)
--   action     Game of Thrones 8    → The Mandalorian 8       (action sans deuil)
--   reflexion  Westworld 8          → The Good Place 8        (sitcom philosophique)
--
-- RIEN D'AUTRE NE CHANGE. Pas une virgule aux définitions, au paragraphe
-- d'indépendance, à la règle du null. C'est délibéré : la v2 avait changé
-- plusieurs choses à la fois et n'avait donc rien appris. Ici une seule
-- variable bouge, et le résultat sera interprétable.
--
-- `joie` et `reve` gardent leurs ancres : ce sont les deux qui se portent
-- bien, et `reve` est le témoin de l'expérience.
--
-- Critère de réussite : tristesse × peur nettement sous 0,84, information
-- propre de `peur` au-dessus de 30 %. Si ça tombe, c'était bien le prompt — par
-- ses exemples, pas par ses consignes. Si ça ne bouge pas, c'est le corpus, et
-- il faudra un échantillon délibérément divers pour trancher.

insert into notation.rubric (version, prompt, axes, note) values (
    'empreinte-v3',
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
   Anchors: Seinfeld = 1, Breaking Bad = 6, BoJack Horseman = 9, Six Feet Under = 10.

4. peur — Fear. How much dread, anxiety and threat does the work generate? 1 = none; 10 = terrifying, suffocating. This is NOT violence and NOT gore: a very violent series with no sense of dread scores low, and a quiet series where something feels deeply wrong scores high. This is NOT sorrow: a grim, tragic drama in which nothing threatens the viewer scores low here. Score the anxiety, not the body count.
   Anchors: Downton Abbey = 1, Ash vs Evil Dead = 6, American Horror Story = 8, The Haunting of Hill House = 10.

5. reflexion — Thought. Does the work make you think about something beyond its own plot? 1 = asks nothing of the mind; 10 = questions the world continuously. This is NOT difficulty: an accessible documentary scores high, and a dense, twisty thriller that raises no question scores low. This is NOT gravity: a light comedy can be full of ideas, and a solemn tragedy can have nothing to say. Score whether the work is about something.
   Anchors: NCIS = 1, Grey''s Anatomy = 3, The Good Place = 8, Black Mirror = 10.

6. action — Action. How much physical movement, confrontation and bodily stakes does the work contain? 1 = static, verbal; 10 = constant motion and danger. This is NOT editing pace: a fast-talking series about people in rooms scores low. This is NOT intensity in general: a harrowing chamber drama has enormous emotional stakes and almost no action. Score what the bodies do.
   Anchors: Friends = 1, Sherlock = 4, The Mandalorian = 8, 24 = 10.

Return only the JSON object requested.',
    '["joie", "reve", "tristesse", "peur", "reflexion", "action"]'::jsonb,
    'Empreinte v3 — seules les ancres changent. Les ancres hautes de peur, tristesse, action et reflexion étaient uniformément sombres et enseignaient la corrélation que la prose interdisait ; chacune reçoit une œuvre qui porte l''émotion dans un registre léger. Définitions et consignes inchangées, pour que l''effet soit interprétable.'
);
