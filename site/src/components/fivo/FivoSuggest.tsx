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

import { deconnecter, listerSignaux, obtenirCompte, poserSignal, retirerSignal } from './api'
import { CompteModale } from './CompteModale'
import { Fives } from './Fives'
import { FicheModale } from './FicheModale'
import { Loupe } from './Loupe'
import { MaListe } from './MaListe'
import { PersonneModale } from './PersonneModale'
import { Recherche } from './Recherche'
import { Suggestions } from './Suggestions'
import {
  LANGUES,
  LANGUE_DEFAUT,
  LANGUE_DRAPEAUX,
  LANGUE_LABELS,
  adresse_dans,
  type Langue,
} from './langue'
import { FournisseurTextes } from './textes'
import { textes } from '../../i18n/textes'
import { UNIVERS, type Compte, type Statut, type UniversSlug } from './types'
import { theme_fivo } from './theme'
import '@mantine/core/styles.css'
import './fivo.css'

type Onglet = 'recherche' | 'suggestions' | 'fives' | 'liste'

const ONGLETS: Array<{
  cle: Onglet
  titre: 'onglet.recherche' | 'onglet.suggestions' | 'fives.onglet' | 'onglet.liste'
}> = [
  { cle: 'recherche', titre: 'onglet.recherche' },
  { cle: 'fives', titre: 'fives.onglet' },
  { cle: 'suggestions', titre: 'onglet.suggestions' },
  { cle: 'liste', titre: 'onglet.liste' },
]

export default function FivoSuggest({
  universInitial = 'series',
  langue = LANGUE_DEFAUT,
}: {
  /** L'univers présélectionné — la page Films ouvre sur les films. */
  universInitial?: UniversSlug
  /** La langue de la PAGE, et donc de l'îlot : `/ar/series` le monte en
   *  arabe. Voir `langue.ts` — l'URL décide, seule. */
  langue?: Langue
}) {
  const [univers, setUnivers] = useState<UniversSlug>(universInitial)

  const [onglet, setOnglet] = useState<Onglet>('recherche')
  const [statuts, setStatuts] = useState<Record<number, Statut>>({})
  // Incrémentée à chaque geste : le signal de rechargement des suggestions.
  const [versionSignaux, setVersionSignaux] = useState(0)
  // La fiche ouverte : sa clé de vignette (ce que l'API demande) et son
  // pivot (ce que les boutons manipulent). `null` = rien d'ouvert.
  const [ouverte, setOuverte] = useState<{ id: number; oeuvreId: number | null } | null>(null)
  // L'univers de la fiche ouverte. Il peut différer de l'univers courant :
  // depuis la filmographie de quelqu'un, on ouvre un film alors qu'on
  // regardait des séries — et la fiche doit être demandée au bon endroit.
  const [universFiche, setUniversFiche] = useState<UniversSlug>(universInitial)
  // La personne ouverte, et l'image agrandie. Deux fenêtres de plus, chacune
  // avec son propre état : la loupe peut s'ouvrir depuis la fiche comme depuis
  // le panneau d'une personne.
  const [personne, setPersonne] = useState<{
    cle: string
    nom: string
    photo: string | null
  } | null>(null)
  const [loupe, setLoupe] = useState<{ image: string; legende: string } | null>(null)
  // Le compte connecté (null sans), et la modale qui permet de le devenir.
  const [compte, setCompte] = useState<Compte | null>(null)
  const [modaleCompte, setModaleCompte] = useState(false)

  useEffect(() => {
    obtenirCompte()
      .then(({ compte: retenu }) => setCompte(retenu))
      .catch(() => {
        // Pas de session, API muette : on reste anonyme, les fives le diront.
      })
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

  const ouvrir = (id: number, oeuvreId: number | null) => {
    setUniversFiche(univers)
    setOuverte({ id, oeuvreId })
  }

  // La même ouverture, mais depuis une liste qui mélange les univers (« Ma
  // liste », une filmographie) : la fiche doit être demandée au bon endroit.
  const ouvrir_ailleurs = (id: number, oeuvreId: number | null, ailleurs: UniversSlug) => {
    setUniversFiche(ailleurs)
    setOuverte({ id, oeuvreId })
  }

  const agrandir = (image: string, legende: string) =>
    image ? setLoupe({ image, legende }) : undefined

  const nombre_aimes = Object.values(statuts).filter((statut) => statut === 'aime').length
  const nombre_classes = Object.keys(statuts).length
  const t = textes(langue)

  return (
    <MantineProvider theme={theme_fivo} forceColorScheme="light">
      <FournisseurTextes value={t}>
      {/* `dir` ici et pas sur la page : l'îlot change de langue sans
          recharger, et c'est lui qui doit se retourner. `lang` avec, sinon la
          césure et les guillemets resteraient français. */}
      <section className="fivo" lang={langue} dir={t.sens} aria-label="FIVO">
        {/* La barre d'univers de la V1 (.tinder-selector) : cellules égales,
            capitales, l'active en aplat carmin sombre. */}
        <Tabs
          value={univers}
          onChange={(valeur) => valeur && setUnivers(valeur as UniversSlug)}
          variant="unstyled"
          classNames={{ list: 'fivo-selecteur', tab: 'fivo-selecteur-onglet' }}
        >
          <Tabs.List aria-label={t.dit('univers.aria')}>
            {UNIVERS.map((slug) => (
              <Tabs.Tab key={slug} value={slug}>
                {t.dit(`nav.${slug}`)}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>

        <div className="fivo-panneau">
          <header className="fivo-bandeau">
            <h3>{t.dit(`bandeau.${univers}`)}</h3>
            <p>{t.dit('bandeau.phrase')}</p>
            {/* La langue du site. Un `select` natif : quatre valeurs, aucun
                comportement à inventer, et il se manipule au clavier comme
                les gens s'y attendent. Choisir NAVIGUE vers la même page dans
                l'autre langue — la coque, le contenu et le composant suivent
                ensemble, plutôt que de laisser un panneau arabe dans une page
                française. */}
            <label className="fivo-langue">
              <span className="accessibilite">{t.dit('langue.legende')}</span>
              <select
                value={langue}
                onChange={(evenement) => {
                  location.assign(adresse_dans(evenement.currentTarget.value as Langue))
                }}
              >
                {LANGUES.map((code) => (
                  // Le drapeau devant le nom, comme dans l'en-tête. Un
                  // `<option>` ne se met pas en forme : l'emoji est le seul
                  // moyen d'y porter une image, et sans police de drapeaux il
                  // s'affiche « FR », donc lisible partout.
                  <option key={code} value={code}>
                    {LANGUE_DRAPEAUX[code]} {LANGUE_LABELS[code]}
                  </option>
                ))}
              </select>
            </label>

            {/* Trois vues, trois pilules. La pastille compte ce qui nourrit
                la vue : les coups de cœur pour les suggestions, tout ce qui
                est classé pour la liste. */}
            <div className="fivo-pilules" role="tablist" aria-label={t.dit('onglet.aria')}>
              {ONGLETS.map(({ cle, titre }) => {
                const pastille =
                  cle === 'suggestions' ? nombre_aimes : cle === 'liste' ? nombre_classes : 0
                return (
                  <UnstyledButton
                    key={cle}
                    role="tab"
                    aria-selected={onglet === cle}
                    className={`fivo-pilule${onglet === cle ? ' actif' : ''}`}
                    onClick={() => setOnglet(cle)}
                  >
                    {t.dit(titre)}
                    {pastille > 0 && (
                      <span className="fivo-pastille">
                        {t.nombre(pastille)}
                        {cle === 'suggestions' ? ' ♥' : ''}
                      </span>
                    )}
                  </UnstyledButton>
                )
              })}
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
              aria-label={t.dit('onglet.recherche')}
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
              aria-label={t.dit('fives.onglet')}
              hidden={onglet !== 'fives'}
              className={onglet === 'fives' ? undefined : 'fivo-panneau-cache'}
            >
              <Fives
                univers={univers}
                langue={langue}
                compte={compte}
                actif={onglet === 'fives'}
                onConnexionRequise={() => setModaleCompte(true)}
                onOuvrir={ouvrir}
              />
            </div>
            <div
              role="tabpanel"
              aria-label={t.dit('onglet.suggestions')}
              hidden={onglet !== 'suggestions'}
              className={onglet === 'suggestions' ? undefined : 'fivo-panneau-cache'}
            >
              <Suggestions
                univers={univers}
                langue={langue}
                statuts={statuts}
                versionSignaux={versionSignaux}
                actif={onglet === 'suggestions'}
                onOuvrir={ouvrir}
                onClasser={classer}
                onDeclasser={declasser}
              />
            </div>
            <div
              role="tabpanel"
              aria-label={t.dit('onglet.liste')}
              hidden={onglet !== 'liste'}
              className={onglet === 'liste' ? undefined : 'fivo-panneau-cache'}
            >
              <MaListe
                langue={langue}
                univers={univers}
                compte={compte}
                statuts={statuts}
                versionSignaux={versionSignaux}
                actif={onglet === 'liste'}
                onOuvrir={ouvrir_ailleurs}
                onClasser={classer}
                onDeclasser={declasser}
                onVoirFives={() => setOnglet('fives')}
              />
            </div>
          </div>
        </div>

        <FicheModale
          univers={universFiche}
          langue={langue}
          identifiant={ouverte?.id ?? null}
          statutActuel={ouverte?.oeuvreId != null ? (statuts[ouverte.oeuvreId] ?? null) : null}
          onFermer={() => setOuverte(null)}
          onClasser={(oeuvreId, statut) => classer(oeuvreId, universFiche, statut)}
          onDeclasser={declasser}
          onAgrandir={agrandir}
          onOuvrirPersonne={(cle, nom, photo) => setPersonne({ cle, nom, photo })}
        />

        <PersonneModale
          cle={personne?.cle ?? null}
          statuts={statuts}
          nom={personne?.nom ?? null}
          photo={personne?.photo ?? null}
          univers={universFiche}
          onFermer={() => setPersonne(null)}
          onOuvrirOeuvre={(identifiant, oeuvreId, universOeuvre) => {
            // On navigue d'un acteur à l'un de ses films : la fiche se
            // recharge dessus et le panneau se referme, plutôt que d'empiler
            // une troisième fenêtre.
            setPersonne(null)
            ouvrir_ailleurs(identifiant, oeuvreId, universOeuvre)
          }}
          onAgrandir={agrandir}
        />

        <CompteModale
          ouverte={modaleCompte}
          langue={langue}
          onFermer={() => setModaleCompte(false)}
          onConnecte={(retenu) => {
            // Connecté : la modale se ferme, et l'écran est resté où il
            // était — les fives reprennent leur chargement toutes seules
            // (le compte fait partie de leur contexte).
            setCompte(retenu)
            setModaleCompte(false)
          }}
        />

        <Loupe
          image={loupe?.image ?? null}
          legende={loupe?.legende}
          onFermer={() => setLoupe(null)}
        />
      </section>
      </FournisseurTextes>
    </MantineProvider>
  )
}
