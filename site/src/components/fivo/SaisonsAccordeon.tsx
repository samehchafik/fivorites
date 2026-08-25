// Les saisons d'une série, en accordéon : on déplie, les épisodes arrivent.
//
// Le chargement est **paresseux, et une seule fois par saison** : une série
// de huit saisons porte deux cents épisodes, que personne ne lit toutes. Ce
// qui a été déplié reste en mémoire — refermer puis rouvrir ne redemande
// rien au serveur.

import { Accordion } from '@mantine/core'
import { useState } from 'react'

import { chargerEpisodes, urlAffiche } from './api'
import type { Episode, Saison, UniversSlug } from './types'

/** L'état de chargement d'UNE saison. Absent de la carte = jamais dépliée. */
type EtatSaison = { etat: 'en-cours' } | { etat: 'servi'; episodes: Episode[] } | { etat: 'erreur' }

export function SaisonsAccordeon({
  univers,
  identifiant,
  saisons,
}: {
  univers: UniversSlug
  /** La clé de vignette de la série — celle que l'API attend. */
  identifiant: number
  saisons: Saison[]
}) {
  const [parSaison, setParSaison] = useState<Record<number, EtatSaison>>({})

  const deplier = async (valeur: string | null) => {
    if (valeur === null) return
    const numero = Number(valeur)
    // Déjà chargée (ou en cours) : on ne redemande pas.
    if (parSaison[numero]) return

    setParSaison((courant) => ({ ...courant, [numero]: { etat: 'en-cours' } }))
    try {
      const { episodes } = await chargerEpisodes(univers, identifiant, numero)
      setParSaison((courant) => ({ ...courant, [numero]: { etat: 'servi', episodes } }))
    } catch {
      setParSaison((courant) => ({ ...courant, [numero]: { etat: 'erreur' } }))
    }
  }

  return (
    <Accordion
      chevronPosition="right"
      variant="separated"
      radius="sm"
      onChange={deplier}
      classNames={{
        root: 'saisons',
        item: 'saison-item',
        control: 'saison-tete',
        // Mantine enveloppe le contenu du bouton dans son propre libellé :
        // c'est LUI qui doit porter la mise en ligne, sinon les deux textes
        // se collent (« Saison 12011 · 10 épisodes » — vu à l'écran).
        label: 'saison-label',
        content: 'saison-contenu',
        chevron: 'saison-chevron',
      }}
    >
      {saisons.map((saison) => {
        const charge = parSaison[saison.numero]
        return (
          <Accordion.Item key={saison.numero} value={String(saison.numero)}>
            <Accordion.Control>
              <span className="saison-titre">{saison.nom ?? `Saison ${saison.numero}`}</span>
              <span className="saison-faits">
                {[
                  saison.annee?.toString(),
                  saison.episodes ? `${saison.episodes} épisodes` : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </Accordion.Control>
            <Accordion.Panel>
              {saison.synopsis && <p className="saison-synopsis">{saison.synopsis}</p>}

              {charge?.etat === 'en-cours' && <p className="saison-note">Chargement des épisodes…</p>}
              {charge?.etat === 'erreur' && (
                <p className="saison-note fivo-erreur">
                  Les épisodes ne répondent pas — refermez et réessayez.
                </p>
              )}
              {charge?.etat === 'servi' && charge.episodes.length === 0 && (
                <p className="saison-note">Les épisodes de cette saison ne sont pas encore collectés.</p>
              )}

              {charge?.etat === 'servi' && charge.episodes.length > 0 && (
                <ol className="episodes">
                  {charge.episodes.map((episode) => {
                    const image = urlAffiche(episode.image, 'w185')
                    return (
                      <li key={episode.numero}>
                        {image ? (
                          <img src={image} alt="" loading="lazy" />
                        ) : (
                          <span className="episode-image-vide" aria-hidden="true" />
                        )}
                        <div className="episode-texte">
                          <strong>
                            {episode.numero}. {episode.titre ?? 'Épisode sans titre'}
                          </strong>
                          <span className="episode-faits">
                            {[
                              episode.diffusion,
                              episode.duree ? `${episode.duree} min` : null,
                              episode.note ? `★ ${episode.note.toFixed(1)}` : null,
                            ]
                              .filter(Boolean)
                              .join(' · ')}
                          </span>
                          {episode.synopsis && <p dir="auto">{episode.synopsis}</p>}
                        </div>
                      </li>
                    )
                  })}
                </ol>
              )}
            </Accordion.Panel>
          </Accordion.Item>
        )
      })}
    </Accordion>
  )
}
