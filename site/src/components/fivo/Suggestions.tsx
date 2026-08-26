// L'onglet Mes suggestions : ce que le moteur propose, et toujours pourquoi.
//
// Le panneau **reste monté** quand on regarde la recherche (voir
// `FivoSuggest`) : revenir ici ne doit pas rejouer un chargement pour
// réafficher ce qu'on venait de lire. D'où la règle de rafraîchissement,
// tenue par `charge` : on ne recharge que si quelque chose a bougé depuis le
// dernier affichage — un univers changé, ou un classement posé entre-temps —
// et **seulement quand l'onglet est visible**. Classer trois œuvres dans la
// recherche déclenche donc UNE requête à la bascule, pas trois en arrière-plan.
//
// C'est ce qui donne le comportement attendu : on cherche, on classe, on
// bascule — et les suggestions arrivent enrichies de ce qu'on vient de faire.

import { useEffect, useRef, useState } from 'react'

import { chargerSuggestions } from './api'
import { CarteOeuvre } from './CarteOeuvre'
import { TYPE_LABELS, type Statut, type Suggestion, type UniversSlug } from './types'

// Les sources du moteur ne disent pas la même chose, et le visiteur doit
// pouvoir les distinguer : « des gens comme vous ont aimé » n'est pas « ça
// ressemble ». Une suggestion inexpliquée ressemble à de la publicité.
//
// La CORROBORATION passe devant tout : quand le contenu et la communauté
// désignent la même œuvre, c'est la meilleure raison qu'on sache donner, et
// c'est aussi ce que le moteur a le plus fortement classé.
function expliquer(suggestion: Suggestion): string {
  if (suggestion.corrobore) {
    const nombre = suggestion.voisins ?? 0
    const porte =
      nombre > 1 ? `${nombre} membres qui partagent vos goûts` : 'un membre qui partage vos goûts'
    return `Proche de vos coups de cœur ET dans le top de ${porte}`
  }
  if (suggestion.source === 'voisins') {
    const nombre = suggestion.voisins ?? 0
    return nombre > 1
      ? `Dans le top de ${nombre} membres qui partagent vos goûts`
      : 'Dans le top d’un membre qui partage vos goûts'
  }
  if (suggestion.source === 'proche') {
    return suggestion.distance != null
      ? `Empreinte très proche de vos coups de cœur (à ${suggestion.distance.toFixed(2)} points)`
      : 'Empreinte très proche de vos coups de cœur'
  }
  // Les affinités : on nomme les genres partagés quand il y en a. Sinon la
  // correspondance s'est faite sur un nom (acteur, réalisateur, auteur) et on
  // reste neutre plutôt que d'affirmer lequel — l'index ne le dit pas.
  if (suggestion.communs.length > 0) {
    return `Comme vos coups de cœur : ${suggestion.communs.slice(0, 3).join(', ')}`
  }
  return 'Proche de ce que vous avez aimé'
}

export function Suggestions({
  univers,
  statuts,
  versionSignaux,
  actif,
  onOuvrir,
  onClasser,
  onDeclasser,
}: {
  univers: UniversSlug
  statuts: Record<number, Statut>
  /** Incrémentée à chaque geste de classement — le déclencheur du rechargement. */
  versionSignaux: number
  /** L'onglet est-il celui qu'on regarde ? Le panneau reste monté quand il ne
   *  l'est pas : il garde sa liste, et ne va pas la rafraîchir pour personne. */
  actif: boolean
  onOuvrir: (identifiant: number, oeuvreId: number | null) => void
  onClasser: (oeuvreId: number, univers: UniversSlug, statut: Statut) => void
  onDeclasser: (oeuvreId: number) => void
}) {
  const [items, setItems] = useState<Suggestion[]>([])
  const [raison, setRaison] = useState<string | null>(null)
  const [etat, setEtat] = useState<'en-cours' | 'servi' | 'erreur'>('en-cours')
  // Ce que la liste affichée reflète déjà. Une référence plutôt qu'un état :
  // elle ne décide d'aucun rendu, elle évite seulement de recharger ce qui
  // est à jour — la mettre en `useState` relancerait l'effet pour rien.
  const charge = useRef<{ univers: UniversSlug; version: number } | null>(null)

  useEffect(() => {
    if (!actif) return
    const dejaVu =
      charge.current !== null &&
      charge.current.univers === univers &&
      charge.current.version === versionSignaux
    if (dejaVu) return

    let abandonne = false
    setEtat('en-cours')
    chargerSuggestions(univers)
      .then((reponse) => {
        if (abandonne) return
        setItems(reponse.items)
        setRaison(reponse.raison)
        setEtat('servi')
        charge.current = { univers, version: versionSignaux }
      })
      .catch(() => {
        if (!abandonne) setEtat('erreur')
      })
    return () => {
      abandonne = true
    }
  }, [univers, versionSignaux, actif])

  // Les suggestions déjà classées pendant la consultation restent affichées
  // (avec leur bouton allumé) jusqu'au prochain rechargement : les faire
  // disparaître sous le doigt serait déroutant.
  return (
    <div>
      {etat === 'erreur' && (
        <p className="fivo-message fivo-erreur">
          Les suggestions ne répondent pas — réessayez dans un instant.
        </p>
      )}
      {etat === 'servi' && (raison === 'aucune_session' || raison === 'aucun_aime') && (
        <p className="fivo-message">
          Commencez par l'onglet <strong>Recherche</strong> : classez quelques œuvres que vous avez
          vues et aimées — c'est la graine de vos suggestions.
        </p>
      )}
      {etat === 'servi' && raison === 'aucun_resultat' && (
        <p className="fivo-message">
          Rien à proposer dans cet univers pour l'instant — vos coups de cœur y sont d'un autre
          univers, ou leur fiche n'est pas encore indexée. Classez une œuvre d'ici, et la liste
          se remplit.
        </p>
      )}

      <div className="fivo-liste" aria-busy={etat === 'en-cours'}>
        {items.map((suggestion) => (
          <CarteOeuvre
            key={suggestion.oeuvreId}
            titre={suggestion.titre}
            annee={suggestion.annee}
            type={TYPE_LABELS[univers]}
            affiche={suggestion.affiche}
            explication={expliquer(suggestion)}
            fort={suggestion.corrobore}
            statutActuel={statuts[suggestion.oeuvreId] ?? null}
            classable
            onOuvrir={() => onOuvrir(suggestion.id, suggestion.oeuvreId)}
            onClasser={(statut) => onClasser(suggestion.oeuvreId, univers, statut)}
            onDeclasser={() => onDeclasser(suggestion.oeuvreId)}
          />
        ))}
      </div>
    </div>
  )
}
