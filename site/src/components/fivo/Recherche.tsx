// L'onglet Recherche : la frappe débouncée, les cartes en temps réel.
//
// Le débounce est court (150 ms) et chaque frappe ANNULE la requête
// précédente (AbortController) : c'est ce qui garantit que la liste affichée
// correspond toujours au texte du champ, jamais à une réponse en retard.

import { TextInput } from '@mantine/core'
import { useEffect, useState } from 'react'

import { rechercher } from './api'
import { CarteOeuvre } from './CarteOeuvre'
import type { Carte, Statut, UniversSlug } from './types'

const DEBOUNCE_MS = 150
const FRAPPE_MIN = 2

export function Recherche({
  univers,
  statuts,
  onOuvrir,
  onClasser,
  onDeclasser,
}: {
  univers: UniversSlug
  /** Les classements de la session, par pivot — pour rallumer les boutons. */
  statuts: Record<number, Statut>
  /** Ouvre la fiche : la clé de vignette, et le pivot pour les boutons. */
  onOuvrir: (identifiant: number, oeuvreId: number | null) => void
  onClasser: (oeuvreId: number, univers: UniversSlug, statut: Statut) => void
  onDeclasser: (oeuvreId: number) => void
}) {
  const [texte, setTexte] = useState('')
  const [cartes, setCartes] = useState<Carte[]>([])
  const [etat, setEtat] = useState<'repos' | 'en-cours' | 'servi' | 'erreur'>('repos')

  useEffect(() => {
    const propre = texte.trim()
    if (propre.length < FRAPPE_MIN) {
      setCartes([])
      setEtat('repos')
      return
    }
    setEtat('en-cours')
    const controleur = new AbortController()
    const minuterie = setTimeout(async () => {
      try {
        const { items } = await rechercher(univers, propre, controleur.signal)
        setCartes(items)
        setEtat('servi')
      } catch {
        if (!controleur.signal.aborted) {
          setEtat('erreur')
        }
      }
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(minuterie)
      controleur.abort()
    }
  }, [texte, univers])

  return (
    <div>
      <TextInput
        className="fivo-champ"
        type="search"
        size="md"
        radius="xl"
        value={texte}
        onChange={(evenement) => setTexte(evenement.currentTarget.value)}
        placeholder="Un titre, un genre, un acteur, un auteur… (« Dune », « policier », « Spielberg »)"
        aria-label="Rechercher une œuvre"
        autoComplete="off"
      />

      {etat === 'repos' && (
        <p className="fivo-message">
          Cherchez les œuvres qui vous ont marqué, puis classez-les : c'est comme ça que FIVO
          apprend vos goûts.
        </p>
      )}
      {etat === 'erreur' && (
        <p className="fivo-message fivo-erreur">
          La recherche ne répond pas — réessayez dans un instant.
        </p>
      )}
      {etat === 'servi' && cartes.length === 0 && (
        <p className="fivo-message">Rien trouvé pour « {texte.trim()} ». Essayez un autre titre ?</p>
      )}

      <div className="fivo-liste" aria-busy={etat === 'en-cours'}>
        {cartes.map((carte) => (
          <CarteOeuvre
            key={carte.id}
            titre={carte.titre ?? carte.titreOriginal}
            annee={carte.annee}
            affiche={carte.affiche}
            genres={carte.genres}
            synopsis={carte.synopsis}
            note={carte.note}
            statutActuel={carte.oeuvreId != null ? (statuts[carte.oeuvreId] ?? null) : null}
            classable={carte.oeuvreId != null}
            onOuvrir={() => onOuvrir(carte.id, carte.oeuvreId)}
            onClasser={(statut) => {
              if (carte.oeuvreId != null) onClasser(carte.oeuvreId, univers, statut)
            }}
            onDeclasser={() => {
              if (carte.oeuvreId != null) onDeclasser(carte.oeuvreId)
            }}
          />
        ))}
      </div>
    </div>
  )
}
