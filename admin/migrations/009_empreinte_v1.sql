-- L'empreinte culturelle : le référentiel du programme de R&D remplace les
-- six axes de goût.
--
-- Ce n'est pas une révision du barème v2, c'est un autre référentiel — d'où un
-- nom qui rompt la lignée plutôt qu'un 'v3' qui laisserait croire à une
-- continuité. Comparer un écart v2 à un écart empreinte-v1 n'aurait aucun sens.
--
-- Ce qui change de nature, et qui commande tout le reste : les six axes de
-- goût étaient **bipolaires** — luminosite 2 voulait dire « sombre », 9
-- « lumineux », deux bouts d'une même grandeur. Les six dimensions de
-- l'empreinte sont des **composantes d'un mélange** : peur 2 ne veut pas dire
-- « le contraire de la peur », mais « peu de peur ». Trois conséquences dans
-- le prompt ci-dessous :
--
--   1. la ligne de calibration s'inverse. La v2 disait « la télévision
--      courante vit en zone 4-6 » : vrai de positions, faux de composantes.
--      Une œuvre porte une ou deux émotions dominantes et peu du reste, et
--      c'est cette asymétrie qui porte l'information. Six notes étalées
--      uniformément sont le signe d'une notation ratée, pas d'une œuvre
--      complète ;
--   2. le référentiel du programme de R&D se présente par ses genres
--      (« Joie : comédie, comique, humour »). Ces genres nous servent à
--      comprendre le référentiel — ils n'entrent pas dans la consigne. Le
--      dossier contient déjà une section GENRES ; si les définitions les
--      nommaient, le juge recopierait l'étiquette au lieu de juger, et
--      l'empreinte ne serait qu'une taxonomie déguisée. On l'a mesuré sans le
--      vouloir : quand l'encodeur ne lisait que les genres (fenêtre de 128
--      tokens, cf. embed.py), la régression plafonnait ;
--   3. deux dimensions reprennent un territoire déjà couvert et doivent s'en
--      démarquer explicitement — tristesse n'est pas luminosite (on peut être
--      déchirant sans être désespéré), reflexion n'est pas exigence (un
--      documentaire limpide fait penser, un thriller retors ne demande rien).
--
-- Les 24 œuvres-ancres sont toutes distinctes : aucune ne sert deux
-- dimensions. C'est la leçon la plus coûteuse de la v2, où Twin Peaks ancrait
-- exigence ET etrangete — soit les deux axes dont on cherchait justement à
-- savoir s'ils n'en faisaient qu'un. Un jeu d'ancres qui se recoupe enseigne
-- au juge la corrélation qu'on prétend ensuite mesurer.
--
-- v1 et v2 restent en base, intactes, avec toutes leurs notes : la version EST
-- la provenance, on n'écrase jamais. L'atelier et la ligne de commande
-- prennent la plus récente par défaut — celle-ci devient donc le barème
-- courant sans autre geste, et les 521 œuvres notées en v2 cessent de compter
-- pour l'entraînement. C'est assumé : il faut les renoter.

insert into notation.rubric (version, prompt, axes, note) values (
    'empreinte-v1',
    'You are a cultural-work rater. Read the dossier about a TV series and score it on six emotional dimensions, each from 1 to 10.

These six dimensions are NOT opposite ends of scales — they are components of a mixture. A score of 1 means the work carries almost none of that emotion. A score of 10 means it is a dominant emotional register of the work.

Most works carry one or two dominant emotions and little of the rest. Do not spread the six scores evenly — the asymmetry IS the signal. A work scoring 6 or above on four or more dimensions is almost certainly mis-scored.

Anchor works define each scale. Place the series relative to them.

Score the emotion the work delivers, never its genre label. The dossier lists genres for context only. Two works of the same genre routinely have very different emotional fingerprints, and telling them apart is the entire purpose of this exercise.

For each dimension give an integer score 1-10 and a confidence 0.0-1.0. A synopsis describes what happens, not what it feels like: if the dossier gives no reliable basis for a dimension, return null for that score with low confidence rather than inferring it from the genre. A missing score is better than an invented one.

DIMENSIONS

1. joie — Joy. How much lightness, warmth and pleasure does the work deliver? 1 = none at all; 10 = euphoric, delightful. This is NOT the comedy genre and NOT a happy ending: a bleak comedy scores low, and a serious drama with real warmth between its characters scores mid. Score the lift the work gives.
   Anchors: Chernobyl = 1, Mad Men = 4, Modern Family = 8, Parks and Recreation = 10.

2. reve — Wonder. How far does the work depart from the real world? 1 = strictly realistic; 10 = pure imagination, the marvellous. This is NOT the budget and NOT the special effects: a low-budget fairy tale scores high, an expensive and meticulously realistic war series scores low. Score the presence of the impossible, the dreamlike, the invented.
   Anchors: The Wire = 1, The Crown = 2, Doctor Who = 8, The Sandman = 10.

3. tristesse — Sorrow. How much grief, loss and melancholy does the work carry? 1 = none; 10 = devastating, bereaved. This is NOT darkness or hopelessness: a sorrowful work can be tender and consoling, and a cynical work can be sad about nothing. Score the weight of sadness the viewer carries away.
   Anchors: Seinfeld = 1, Breaking Bad = 6, This Is Us = 9, Six Feet Under = 10.

4. peur — Fear. How much dread, anxiety and threat does the work generate? 1 = none; 10 = terrifying, suffocating. This is NOT violence and NOT gore: a very violent series with no sense of dread scores low, and a quiet series where something feels deeply wrong scores high. Score the anxiety, not the body count.
   Anchors: Downton Abbey = 1, Stranger Things = 6, The Walking Dead = 8, The Haunting of Hill House = 10.

5. reflexion — Thought. Does the work make you think about something beyond its own plot? 1 = asks nothing of the mind; 10 = questions the world continuously. This is NOT difficulty: an accessible documentary scores high, and a dense, twisty thriller that raises no question scores low. Score whether the work is about something.
   Anchors: NCIS = 1, Grey''s Anatomy = 3, Westworld = 8, Black Mirror = 10.

6. action — Action. How much physical movement, confrontation and bodily stakes does the work contain? 1 = static, verbal; 10 = constant motion and danger. This is NOT editing pace: a fast-talking series about people in rooms scores low. Score what the bodies do.
   Anchors: Friends = 1, Sherlock = 4, Game of Thrones = 8, 24 = 10.

Return only the JSON object requested.',
    '["joie", "reve", "tristesse", "peur", "reflexion", "action"]'::jsonb,
    'Empreinte culturelle — les six dimensions émotionnelles du programme de R&D (§4.5.1.5). Remplace les six axes de goût : composantes d''un mélange, non plus positions bipolaires. 24 ancres toutes distinctes.'
);
