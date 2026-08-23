// « FIVO, suggère-moi… » — l'îlot React du site public, dans la peau du
// composant swipe de la V1 : la barre d'univers au-dessus, le panneau au
// dégradé carmin (#700031 → #FA0036) avec l'étoile en filigrane, le bandeau
// « FIVO VA TROUVER DES … POUR VOUS ! », et deux vues — Recherche et Mes
// suggestions — en pilules, comme les « Suggestions pour vous / Vos
// fivorites » de la home V1.
//
// Mantine porte les comportements (onglets clavier, champs, boutons) ; la
// feuille fivo.css porte les pixels de la V1. L'état partagé est le
// dictionnaire des classements de la session (pivot → statut), chargé au
// montage et tenu à jour de façon optimiste — le bouton s'allume au clic et
// se rétablit si le serveur refuse.

import { MantineProvider, Tabs, UnstyledButton } from '@mantine/core'
import { useEffect, useState } from 'react'

import { listerSignaux, poserSignal, retirerSignal } from './api'
import { Recherche } from './Recherche'
import { Suggestions } from './Suggestions'
import { UNIVERS_LABELS, type Statut, type UniversSlug } from './types'
import { theme_fivo } from './theme'
import '@mantine/core/styles.css'
import './fivo.css'

type Onglet = 'recherche' | 'suggestions'

// « FIVO VA TROUVER DES SÉRIES POUR VOUS ! » — le complément varie avec
// l'univers, comme dans le bandeau V1.
const COMPLEMENTS: Record<UniversSlug, string> = {
  series: 'des séries',
  films: 'des films',
  livres: 'des livres',
}

export default function FivoSuggest({
  universInitial = 'series',
}: {
  /** L'univers présélectionné — la page Films ouvre sur les films. */
  universInitial?: UniversSlug
}) {
  const [univers, setUnivers] = useState<UniversSlug>(universInitial)
  const [onglet, setOnglet] = useState<Onglet>('recherche')
  const [statuts, setStatuts] = useState<Record<number, Statut>>({})
  // Incrémentée à chaque geste : le signal de rechargement des suggestions.
  const [versionSignaux, setVersionSignaux] = useState(0)

  useEffect(() => {
    listerSignaux()
      .then(({ items }) => {
        const initiaux: Record<number, Statut> = {}
        for (const signal of items) {
          initiaux[signal.oeuvreId] = signal.statut
        }
        setStatuts(initiaux)
      })
      .catch(() => {
        // Pas de session ou API muette : le composant démarre vide, le
        // premier geste retentera de toute façon.
      })
  }, [])

  const classer = async (oeuvreId: number, universOeuvre: UniversSlug, statut: Statut) => {
    const precedent = statuts[oeuvreId] ?? null
    setStatuts((courants) => ({ ...courants, [oeuvreId]: statut }))
    try {
      await poserSignal(oeuvreId, universOeuvre, statut)
      setVersionSignaux((version) => version + 1)
    } catch {
      setStatuts((courants) => {
        const retablis = { ...courants }
        if (precedent === null) delete retablis[oeuvreId]
        else retablis[oeuvreId] = precedent
        return retablis
      })
    }
  }

  const declasser = async (oeuvreId: number) => {
    const precedent = statuts[oeuvreId] ?? null
    if (precedent === null) return
    setStatuts((courants) => {
      const suivants = { ...courants }
      delete suivants[oeuvreId]
      return suivants
    })
    try {
      await retirerSignal(oeuvreId)
      setVersionSignaux((version) => version + 1)
    } catch {
      setStatuts((courants) => ({ ...courants, [oeuvreId]: precedent }))
    }
  }

  const nombre_aimes = Object.values(statuts).filter((statut) => statut === 'aime').length

  return (
    <MantineProvider theme={theme_fivo} forceColorScheme="light">
      <section className="fivo" aria-label="FIVO, suggère-moi">
        {/* La barre d'univers de la V1 (.tinder-selector) : cellules égales,
            capitales, l'active en aplat carmin sombre. */}
        <Tabs
          value={univers}
          onChange={(valeur) => valeur && setUnivers(valeur as UniversSlug)}
          variant="unstyled"
          classNames={{ list: 'fivo-selecteur', tab: 'fivo-selecteur-onglet' }}
        >
          <Tabs.List aria-label="Choisir un univers">
            {(Object.keys(UNIVERS_LABELS) as UniversSlug[]).map((slug) => (
              <Tabs.Tab key={slug} value={slug}>
                {UNIVERS_LABELS[slug]}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>

        <div className="fivo-panneau">
          <header className="fivo-bandeau">
            <h3>
              Fivo va trouver <span className="fivo-bandeau-univers">{COMPLEMENTS[univers]}</span>{' '}
              pour vous !
            </h3>
            <p>
              Fivo, notre moteur d'inspiration culturelle, apprend de chaque geste : cherchez,
              classez — et regardez vos suggestions se préciser.
            </p>
            <div className="fivo-pilules" role="tablist" aria-label="Recherche ou suggestions">
              <UnstyledButton
                role="tab"
                aria-selected={onglet === 'recherche'}
                className={`fivo-pilule${onglet === 'recherche' ? ' actif' : ''}`}
                onClick={() => setOnglet('recherche')}
              >
                Recherche
              </UnstyledButton>
              <UnstyledButton
                role="tab"
                aria-selected={onglet === 'suggestions'}
                className={`fivo-pilule${onglet === 'suggestions' ? ' actif' : ''}`}
                onClick={() => setOnglet('suggestions')}
              >
                Mes suggestions
                {nombre_aimes > 0 && <span className="fivo-pastille">{nombre_aimes} ♥</span>}
              </UnstyledButton>
            </div>
          </header>

          <div className="fivo-contenu">
            {onglet === 'recherche' ? (
              <Recherche
                univers={univers}
                statuts={statuts}
                onClasser={classer}
                onDeclasser={declasser}
              />
            ) : (
              <Suggestions
                univers={univers}
                statuts={statuts}
                versionSignaux={versionSignaux}
                onClasser={classer}
                onDeclasser={declasser}
              />
            )}
          </div>
        </div>
      </section>
    </MantineProvider>
  )
}
