-- La provenance d'une note interne : quel encodeur a produit le vecteur.
--
-- Sans cette colonne, deux notes de qualités très différentes se ressemblent
-- trait pour trait. La régression appliquée aux vecteurs de l'API rend 0,83 de
-- MAE ; la même régression, entraînée dans l'espace de l'élève distillé, rend
-- 0,94. Les deux s'écrivent sous `interne-ridge`, avec la même forme et la même
-- échelle, et rien ne les distinguerait.
--
-- Ce que ça permet, et qui est la raison d'être de la colonne : **la
-- promotion**. Le catalogue compte 1,2 million de films ; les encoder tous avec
-- le gros modèle coûterait quelques centaines de dollars pour des œuvres que
-- personne n'ouvrira. On note donc la traîne avec l'élève — pour que TOUTE
-- œuvre soit consultable — et on repasse au bon encodeur celles qui deviennent
-- réellement consultées.
--
-- La sélection de `notation generer` compare cette colonne à l'encodeur
-- demandé : une œuvre notée par l'élève redevient éligible dès qu'on lance la
-- génération avec l'encodeur de production. La promotion n'est donc pas un
-- mécanisme séparé, c'est la même commande avec un autre encodeur.
--
-- Nullable, et il faut qu'elle le reste : les notes du juge n'ont pas
-- d'encodeur — GPT lit le dossier, il ne lit pas un vecteur — et les notes
-- internes écrites avant cette migration l'ignorent. `null` se lit donc
-- « inconnu », et la sélection traite l'inconnu comme à regénérer, ce qui est
-- le comportement prudent.
--
-- Écrite AVANT la première génération de masse, exprès : ajouter une colonne à
-- une table de sept millions de lignes se paie, sur une table vide non.

alter table notation.score add column encodeur text;

comment on column notation.score.encodeur is
    'L''encodeur qui a produit le vecteur, pour les notes internes seulement. null pour les notes de juge (elles ne passent pas par un vecteur) et pour l''historique d''avant la migration 014. Sert à la promotion : une note produite par l''élève distillé se repère et se refait avec le gros modèle quand l''œuvre devient consultée.';

-- L'index sert exactement la requête de sélection de `notation generer` :
-- « les œuvres de ce barème dont la note interne n'a pas été produite par
-- l'encodeur demandé, ou l'a été avant le dernier entraînement ». Partiel,
-- parce que les notes de juge n'ont rien à y faire et qu'elles sont
-- minoritaires — l'index reste petit là où la table sera énorme.
create index score_interne_encodeur_idx
    on notation.score (rubric_version, oeuvre_id, encodeur, scored_at desc)
    where modele = 'interne-ridge';
