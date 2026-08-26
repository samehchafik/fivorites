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
import { FicheModale } from './FicheModale'
import { Recherche } from './Recherche'
import { Suggestions } from './Suggestions'
import { LANGUES, LANGUE_LABELS, langueInitiale, retenirLangue, type Langue } from './langue'
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
  // La langue de recherche : celle du navigateur au premier passage, puis
  // celle qu'on a choisie. Elle décide des titres cherchés ET affichés —
  // sans elle, une frappe courte ramenait des titres de langues qu'on ne lit
  // pas, présentés dans une autre encore.
  const [langue, setLangue] = useState<Langue>('fr')

  const [onglet, setOnglet] = useState<Onglet>('recherche')
  const [statuts, setStatuts] = useState<Record<number, Statut>>({})
  // Incrémentée à chaque geste : le signal de rechargement des suggestions.
  const [versionSignaux, setVersionSignaux] = useState(0)
  // La fiche ouverte : sa clé de vignette (ce que l'API demande) et son
  // pivot (ce que les boutons manipulent). `null` = rien d'ouvert.
  const [ouverte, setOuverte] = useState<{ id: number; oeuvreId: number | null } | null>(null)

  // La langue est lue après le montage, jamais pendant : la page est rendue à
  // l'avance (HTML statique) et le navigateur de qui la reçoit n'est pas
  // connu à ce moment-là. La poser dans l'état initial ferait diverger le
  // premier rendu du navigateur de celui construit au build.
  useEffect(() => {
    setLangue(langueInitiale())
  }, [])

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

  const ouvrir = (id: number, oeuvreId: number | null) => setOuverte({ id, oeuvreId })

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
            {/* La langue de recherche. Un `select` natif : quatre valeurs,
                aucun comportement à inventer, et il se manipule au clavier
                comme les gens s'y attendent. */}
            <label className="fivo-langue">
              <span className="accessibilite">Langue de recherche</span>
              <select
                value={langue}
                onChange={(evenement) => {
                  const choisie = evenement.currentTarget.value as Langue
                  setLangue(choisie)
                  retenirLangue(choisie)
                }}
              >
                {LANGUES.map((code) => (
                  <option key={code} value={code}>
                    {LANGUE_LABELS[code]}
                  </option>
                ))}
              </select>
            </label>

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

          {/* Les DEUX panneaux restent montés, celui qu'on ne regarde pas
              étant seulement caché : démonter la recherche perdrait la frappe
              et ses résultats, et revenir dessus rejouerait une requête pour
              réafficher ce qu'on venait de lire. Les suggestions, elles,
              savent ne se rafraîchir qu'en redevenant visibles (voir
              `Suggestions`). */}
          <div className="fivo-contenu">
            <div
              role="tabpanel"
              aria-label="Recherche"
              hidden={onglet !== 'recherche'}
              className={onglet === 'recherche' ? undefined : 'fivo-panneau-cache'}
            >
              <Recherche
                univers={univers}
                langue={langue}
                statuts={statuts}
                actif={onglet === 'recherche'}
                onOuvrir={ouvrir}
                onClasser={classer}
                onDeclasser={declasser}
              />
            </div>
            <div
              role="tabpanel"
              aria-label="Mes suggestions"
              hidden={onglet !== 'suggestions'}
              className={onglet === 'suggestions' ? undefined : 'fivo-panneau-cache'}
            >
              <Suggestions
                univers={univers}
                statuts={statuts}
                versionSignaux={versionSignaux}
                actif={onglet === 'suggestions'}
                onOuvrir={ouvrir}
                onClasser={classer}
                onDeclasser={declasser}
              />
            </div>
          </div>
        </div>

        <FicheModale
          univers={univers}
          langue={langue}
          identifiant={ouverte?.id ?? null}
          statutActuel={ouverte?.oeuvreId != null ? (statuts[ouverte.oeuvreId] ?? null) : null}
          onFermer={() => setOuverte(null)}
          onClasser={(oeuvreId, statut) => classer(oeuvreId, univers, statut)}
          onDeclasser={declasser}
        />
      </section>
    </MantineProvider>
  )
}
