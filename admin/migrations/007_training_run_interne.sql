-- Le vecteur généré par la régression rejoint le journal des essais.
--
-- `training_run` gardait les deux verdicts des juges (openai, claude) mais pas
-- ce que le modèle interne, lui, avait prédit pour la même œuvre. C'était le
-- chaînon manquant : la phase 2 compare l'interne au LLM, et cette comparaison
-- ne survivait qu'à l'écran. Elle s'écrit maintenant à côté des verdicts
-- qu'elle conteste — même ligne, même œuvre, même barème.
--
-- Colonne à part plutôt que ligne nouvelle : une génération n'est pas un
-- essai de notation, c'est une lecture des poids sur un essai qui existe déjà.

alter table notation.training_run
    add column interne    jsonb,
    add column interne_at timestamptz;

comment on column notation.training_run.interne is
    'Le vecteur prédit par la régression interne : {axe: {score, trainedOn, maeFit}}. Généré depuis la phase 2, jamais par un juge.';
comment on column notation.training_run.interne_at is
    'Quand la génération a eu lieu — les poids ayant pu changer depuis l''essai, la date compte autant que les valeurs.';
