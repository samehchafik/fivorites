// L'onglet Recherche : la frappe débouncée, les cartes en temps réel.
//
// Le débounce est court (150 ms) et chaque frappe ANNULE la requête
// précédente (AbortController) : c'est ce qui garantit que la liste affichée
// correspond toujours au texte du champ, jamais à une réponse en retard.
//
// Le panneau **reste monté** quand on regarde les suggestions (voir
// `FivoSuggest`) : la frappe, les cartes et la position de défilement
// survivent à la bascule — on retrouve sa recherche là où on l'a laissée.
// Caché, il ne cherche pas : un univers changé pendant qu'on lit les
// suggestions n'est rattrapé qu'au retour, et une seule fois.

import { TextInput } from '@mantine/core'
import { useEffect, useRef, useState } from 'react'

import { rechercher } from './api'
import { CarteOeuvre } from './CarteOeuvre'
import type { Carte, Statut, UniversSlug } from './types'

const DEBOUNCE_MS = 150
const FRAPPE_MIN = 2

export function Recherche({
  univers,
  statuts,
  actif,
  onOuvrir,
  onClasser,
  onDeclasser,
}: {
  univers: UniversSlug
  /** Les classements de la session, par pivot — pour rallumer les boutons. */
  statuts: Record<number, Statut>
  /** L'onglet est-il celui qu'on regarde ? Caché, le panneau garde tout et
   *  ne cherche rien. */
  actif: boolean
  /** Ouvre la fiche : la clé de vignette, et le pivot pour les boutons. */
  onOuvrir: (identifiant: number, oeuvreId: number | null) => void
  onClasser: (oeuvreId: number, univers: UniversSlug, statut: Statut) => void
  onDeclasser: (oeuvreId: number) => void
}) {
  const [texte, setTexte] = useState('')
  const [cartes, setCartes] = useState<Carte[]>([])
  const [etat, setEtat] = useState<'repos' | 'en-cours' | 'servi' | 'erreur'>('repos')
  // Ce que les cartes affichées reflètent déjà — même rôle que dans
  // `Suggestions` : revenir sur l'onglet ne doit pas rejouer la requête qui
  // rendrait exactement la liste qui est là.
  const charge = useRef<{ texte: string; univers: UniversSlug } | null>(null)

  useEffect(() => {
    const propre = texte.trim()
    if (propre.length < FRAPPE_MIN) {
      setCartes([])
      setEtat('repos')
      charge.current = null
      return
    }
    if (!actif) return
    if (charge.current?.texte === propre && charge.current.univers === univers) return

    setEtat('en-cours')
    const controleur = new AbortController()
    const minuterie = setTimeout(async () => {
      try {
        const { items } = await rechercher(univers, propre, controleur.signal)
        setCartes(items)
        setEtat('servi')
        charge.current = { texte: propre, univers }
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
  }, [texte, univers, actif])

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
