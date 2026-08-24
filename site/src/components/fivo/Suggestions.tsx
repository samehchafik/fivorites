// L'onglet Mes suggestions : ce que le moteur propose, et toujours pourquoi.
//
// La liste se recharge quand l'onglet s'ouvre et quand les classements
// bougent (`versionSignaux`) : classer une suggestion la fait sortir de la
// liste — elle est acceptée ou écartée — et la place se remplit au
// rechargement suivant.

import { useEffect, useState } from 'react'

import { chargerSuggestions } from './api'
import { CarteOeuvre } from './CarteOeuvre'
import type { Statut, Suggestion, UniversSlug } from './types'

function expliquer(suggestion: Suggestion): string {
  if (suggestion.source === 'voisins') {
    const nombre = suggestion.voisins ?? 0
    return nombre > 1
      ? `Dans le top de ${nombre} membres qui partagent vos goûts`
      : 'Dans le top d’un membre qui partage vos goûts'
  }
  return suggestion.distance != null
    ? `Empreinte très proche de vos coups de cœur (à ${suggestion.distance.toFixed(2)} points)`
    : 'Empreinte très proche de vos coups de cœur'
}

export function Suggestions({
  univers,
  statuts,
  versionSignaux,
  onOuvrir,
  onClasser,
  onDeclasser,
}: {
  univers: UniversSlug
  statuts: Record<number, Statut>
  /** Incrémentée à chaque geste de classement — le déclencheur du rechargement. */
  versionSignaux: number
  onOuvrir: (identifiant: number, oeuvreId: number | null) => void
  onClasser: (oeuvreId: number, univers: UniversSlug, statut: Statut) => void
  onDeclasser: (oeuvreId: number) => void
}) {
  const [items, setItems] = useState<Suggestion[]>([])
  const [raison, setRaison] = useState<string | null>(null)
  const [etat, setEtat] = useState<'en-cours' | 'servi' | 'erreur'>('en-cours')

  useEffect(() => {
    let abandonne = false
    setEtat('en-cours')
    chargerSuggestions(univers)
      .then((reponse) => {
        if (abandonne) return
        setItems(reponse.items)
        setRaison(reponse.raison)
        setEtat('servi')
      })
      .catch(() => {
        if (!abandonne) setEtat('erreur')
      })
    return () => {
      abandonne = true
    }
  }, [univers, versionSignaux])

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
          Pas encore de suggestion dans cet univers — aimez quelques œuvres de plus, le moteur
          s'affine à chaque geste.
        </p>
      )}

      <div className="fivo-liste" aria-busy={etat === 'en-cours'}>
        {items.map((suggestion) => (
          <CarteOeuvre
            key={suggestion.oeuvreId}
            titre={suggestion.titre}
            annee={suggestion.annee}
            affiche={suggestion.affiche}
            explication={expliquer(suggestion)}
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
