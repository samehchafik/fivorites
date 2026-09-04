// Les fives : vos meilleures œuvres, par univers — LE geste du site.
//
// DEUX palmarès par univers, comme la V1 : « Le TOP 5 de ma vie » et « Le
// TOP du moment ». Chacun est un plateau de CINQ RANGÉES numérotées, façon
// palmarès — vignette + titre quand la rangée est remplie. Toucher une
// rangée vide ouvre une recherche sur place ; toucher un résultat la
// remplit. Toucher le ✕ d'une rangée pleine la vide. Rien à apprendre.
//
// Sans compte, PAS de barrière : « Commence ton premier five » ouvre les
// plateaux, et tout se compose en silence, en local — le serveur n'est pas
// consulté. La connexion n'arrive qu'à la FIN, au moment de garder (bouton
// « Garde ton five », ou automatiquement à la cinquième case) ; une fois
// connecté, chaque brouillon est versé au compte, rang par rang.
//
// Et sous les siens, les fives de la COMMUNAUTÉ : des listes de membres de
// la V1, tirées au sort — anonymes, leur import les a masqués.

import { useEffect, useRef, useState } from 'react'

import {
  chargerFives,
  fivesCommunaute,
  poserFive,
  rechercher,
  retirerFive,
  urlAffiche,
  ApiErreur,
} from './api'
import { useTextes } from './textes'
import type { Carte, Compte, Five, FiveCommunaute, ListeFive, UniversSlug } from './types'

const RANGS = [1, 2, 3, 4, 5]

// Le brouillon anonyme vit dans localStorage : il survit à l'aller-retour
// vers la boîte mail pour le code de vérification, même si l'onglet se
// ferme. La clé sans suffixe est celle d'avant les deux palmarès — elle
// reste celle de la vie, les brouillons déjà posés ne se perdent pas.
const cleBrouillon = (univers: UniversSlug, liste: ListeFive) =>
  liste === 'vie' ? `fivo.brouillon.${univers}` : `fivo.brouillon.${univers}.${liste}`

export function lireBrouillon(univers: UniversSlug, liste: ListeFive = 'vie'): Five[] {
  try {
    const brut = localStorage.getItem(cleBrouillon(univers, liste))
    const lu: unknown = brut ? JSON.parse(brut) : []
    if (!Array.isArray(lu)) return []
    return (lu as Five[]).filter(
      (five) => typeof five?.rang === 'number' && typeof five?.oeuvreId === 'number',
    )
  } catch {
    return []
  }
}

function ecrireBrouillon(univers: UniversSlug, liste: ListeFive, fives: Five[]) {
  try {
    if (fives.length === 0) localStorage.removeItem(cleBrouillon(univers, liste))
    else localStorage.setItem(cleBrouillon(univers, liste), JSON.stringify(fives))
  } catch {
    // Navigation privée : le brouillon ne survivra pas au rechargement — le
    // plateau, lui, continue de fonctionner en mémoire.
  }
}

/** Un plateau : les cinq rangées d'UN palmarès (vie ou moment). */
function Palmares({
  univers,
  langue,
  liste,
  compte,
  actif,
  onConnexionRequise,
  onOuvrir,
}: {
  univers: UniversSlug
  langue: string
  liste: ListeFive
  compte: Compte | null
  actif: boolean
  onConnexionRequise: () => void
  onOuvrir: (identifiant: number, oeuvreId: number | null) => void
}) {
  const t = useTextes()
  const [fives, setFives] = useState<Five[]>([])
  const [etat, setEtat] = useState<'en-cours' | 'servi' | 'erreur' | 'connexion'>('en-cours')
  // La case en cours de remplissage, et sa recherche.
  const [rangOuvert, setRangOuvert] = useState<number | null>(null)
  const [frappe, setFrappe] = useState('')
  const [resultats, setResultats] = useState<Carte[]>([])
  const charge = useRef<{ univers: UniversSlug; compte: string | null } | null>(null)

  const recharger = async () => {
    setEtat('en-cours')
    try {
      const reponse = await chargerFives(univers, liste)
      setFives(reponse.items)
      setEtat('servi')
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) {
        setEtat('connexion')
      } else {
        setEtat('erreur')
      }
    }
  }

  // Un compte vient d'apparaître (ou l'onglet s'ouvre connecté) : le
  // brouillon local, s'il existe, est versé au compte AVANT la lecture —
  // c'est la promesse du parcours anonyme. Meilleur effort : un rang qui
  // échoue ne fait pas perdre les autres.
  const verserPuisRecharger = async () => {
    const brouillon = lireBrouillon(univers, liste)
    if (brouillon.length > 0) {
      setEtat('en-cours')
      for (const five of brouillon) {
        try {
          await poserFive(univers, liste, five.rang, five.oeuvreId)
        } catch {
          // Œuvre disparue ou rang refusé : les autres passent quand même.
        }
      }
      ecrireBrouillon(univers, liste, [])
    }
    await recharger()
  }

  useEffect(() => {
    if (!actif) return
    const identite = compte?.id ?? null
    if (charge.current?.univers === univers && charge.current.compte === identite) return
    charge.current = { univers, compte: identite }
    setRangOuvert(null)
    setFrappe('')
    setFives([])
    if (identite === null) {
      // Personne de connecté : le plateau se compose en silence, en local —
      // pas un mot au serveur.
      setFives(lireBrouillon(univers, liste))
      setEtat('servi')
    } else {
      void verserPuisRecharger()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actif, univers, compte?.id])

  // La recherche de la case ouverte : la même API que l'onglet Recherche,
  // débouncée pareil.
  useEffect(() => {
    const propre = frappe.trim()
    if (rangOuvert === null || propre.length < 2) {
      setResultats([])
      return
    }
    const controleur = new AbortController()
    const minuterie = setTimeout(async () => {
      try {
        const reponse = await rechercher(univers, propre, {
          langue,
          signal: controleur.signal,
        })
        setResultats(reponse.items.slice(0, 5))
      } catch {
        // La frappe suivante retentera : pas d'état d'erreur pour une lettre.
      }
    }, 150)
    return () => {
      clearTimeout(minuterie)
      controleur.abort()
    }
  }, [frappe, rangOuvert, univers, langue])

  const poser = async (rang: number, carte: Carte) => {
    if (carte.oeuvreId == null) return
    if (compte === null) {
      const pose: Five = {
        rang,
        oeuvreId: carte.oeuvreId,
        id: carte.id,
        titre: carte.titre ?? carte.titreOriginal ?? null,
        affiche: carte.affiche,
        annee: carte.annee ?? null,
      }
      const nouveaux = [...fives.filter((five) => five.rang !== rang), pose].sort(
        (a, b) => a.rang - b.rang,
      )
      setFives(nouveaux)
      ecrireBrouillon(univers, liste, nouveaux)
      setRangOuvert(null)
      setFrappe('')
      setResultats([])
      // La cinquième case vient d'être posée : c'est maintenant — et
      // seulement maintenant — qu'on parle de compte, pour le garder.
      if (nouveaux.length === RANGS.length) onConnexionRequise()
      return
    }
    try {
      await poserFive(univers, liste, rang, carte.oeuvreId)
      setRangOuvert(null)
      setFrappe('')
      setResultats([])
      await recharger()
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) onConnexionRequise()
    }
  }

  const retirer = async (rang: number) => {
    if (compte === null) {
      const nouveaux = fives.filter((five) => five.rang !== rang)
      setFives(nouveaux)
      ecrireBrouillon(univers, liste, nouveaux)
      return
    }
    try {
      await retirerFive(univers, liste, rang)
      await recharger()
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) onConnexionRequise()
    }
  }

  if (etat === 'connexion') {
    return (
      <div className="fives-palmares">
        <p className="fivo-message">{t.dit('compte.pourquoi')}</p>
        <button type="button" className="compte-bouton" onClick={onConnexionRequise}>
          {t.dit('compte.titre_connexion')}
        </button>
      </div>
    )
  }
  if (etat === 'erreur') {
    return <p className="fivo-message fivo-erreur">{t.dit('fives.erreur')}</p>
  }

  const parRang = new Map(fives.map((five) => [five.rang, five]))
  const titre = liste === 'vie' ? t.dit(`fives.titre.${univers}`) : t.dit('fives.moment')

  return (
    <div className="fives-palmares">
      <h4 className="fives-titre">{titre}</h4>
      <ol className="fives-cases">
        {RANGS.map((rang) => {
          const five = parRang.get(rang)
          const affiche = urlAffiche(five?.affiche ?? null, 'w92')
          if (five) {
            return (
              <li key={rang} className="fives-case fives-case-pleine">
                <span className="fives-rang" aria-hidden="true">
                  {rang}
                </span>
                <button
                  type="button"
                  className="fives-oeuvre"
                  onClick={() => five.id !== null && onOuvrir(five.id, five.oeuvreId)}
                  title={five.titre ?? undefined}
                >
                  {affiche ? (
                    <img src={affiche} alt="" loading="lazy" />
                  ) : (
                    <span className="fives-affiche-vide" aria-hidden="true" />
                  )}
                  <strong dir="auto">{five.titre ?? t.dit('carte.sans_titre')}</strong>
                </button>
                <button
                  type="button"
                  className="fivo-retirer"
                  aria-label={t.dit('fives.retirer', { rang })}
                  title={t.dit('fives.retirer', { rang })}
                  onClick={() => retirer(rang)}
                >
                  ✕
                </button>
              </li>
            )
          }
          if (rangOuvert === rang) {
            return (
              <li key={rang} className="fives-case fives-case-ouverte">
                <span className="fives-rang" aria-hidden="true">
                  {rang}
                </span>
                <input
                  className="compte-champ"
                  type="search"
                  autoFocus
                  value={frappe}
                  onChange={(e) => setFrappe(e.currentTarget.value)}
                  placeholder={t.dit('fives.chercher', { rang })}
                />
                {resultats.length > 0 && (
                  <ul className="fives-resultats">
                    {resultats.map((carte) => (
                      <li key={carte.id}>
                        <button type="button" onClick={() => poser(rang, carte)}>
                          {urlAffiche(carte.affiche, 'w92') && (
                            <img src={urlAffiche(carte.affiche, 'w92')!} alt="" loading="lazy" />
                          )}
                          <span dir="auto">
                            {carte.titre ?? carte.titreOriginal ?? t.dit('carte.sans_titre')}
                            {carte.annee ? ` (${carte.annee})` : ''}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <button
                  type="button"
                  className="compte-lien"
                  onClick={() => {
                    setRangOuvert(null)
                    setFrappe('')
                  }}
                >
                  {t.dit('fives.annuler')}
                </button>
              </li>
            )
          }
          return (
            <li key={rang} className="fives-case">
              <button
                type="button"
                className="fives-vide"
                onClick={() => {
                  setRangOuvert(rang)
                  setFrappe('')
                  setResultats([])
                }}
              >
                <span className="fives-rang" aria-hidden="true">
                  {rang}
                </span>
                <span className="fives-plus" aria-hidden="true">
                  +
                </span>
                {t.dit('fives.case_vide')}
              </button>
            </li>
          )
        })}
      </ol>
      {compte === null && fives.length > 0 && (
        <div className="fives-garder">
          <button type="button" className="compte-bouton" onClick={onConnexionRequise}>
            {t.dit('fives.garder')}
          </button>
          <p className="fives-garder-note">{t.dit('fives.garder_note')}</p>
        </div>
      )}
    </div>
  )
}

export function Fives({
  univers,
  langue,
  compte,
  actif,
  onConnexionRequise,
  onOuvrir,
}: {
  univers: UniversSlug
  langue: string
  /** Le compte connu de l'îlot — null tant qu'on n'est pas connecté. */
  compte: Compte | null
  actif: boolean
  /** Le serveur exige un compte : l'îlot ouvre la modale. */
  onConnexionRequise: () => void
  /** Ouvre la fiche d'une œuvre posée. */
  onOuvrir: (identifiant: number, oeuvreId: number | null) => void
}) {
  const t = useTextes()
  // Le plateau anonyme reste derrière son bouton d'accueil tant que ce
  // n'est pas cliqué — sauf si un brouillon existe déjà.
  const [commence, setCommence] = useState(false)
  const [communaute, setCommunaute] = useState<FiveCommunaute[]>([])
  const vitrine = useRef<UniversSlug | null>(null)

  useEffect(() => {
    setCommence(false)
  }, [univers])

  useEffect(() => {
    if (!actif || vitrine.current === univers) return
    vitrine.current = univers
    setCommunaute([])
    fivesCommunaute(univers)
      .then(({ items }) => setCommunaute(items))
      .catch(() => {
        // Une vitrine muette ne prive personne de ses propres fives.
      })
  }, [actif, univers])

  const brouillons =
    compte === null
      ? lireBrouillon(univers, 'vie').length + lireBrouillon(univers, 'moment').length
      : 0

  if (compte === null && brouillons === 0 && !commence) {
    // L'accueil anonyme : pas de formulaire, pas de barrière — un seul
    // bouton qui ouvre les plateaux.
    return (
      <div className="fives fives-accueil">
        <p className="fives-pitch">{t.dit(`fives.pitch.${univers}`)}</p>
        <h4 className="fives-titre">{t.dit(`fives.titre.${univers}`)}</h4>
        <button
          type="button"
          className="compte-bouton fives-commencer"
          onClick={() => setCommence(true)}
        >
          {t.dit('fives.commencer')}
        </button>
      </div>
    )
  }

  return (
    <div className="fives">
      <p className="fives-pitch">{t.dit(`fives.pitch.${univers}`)}</p>
      <p className="fives-consigne">{t.dit('fives.consigne')}</p>
      <Palmares
        univers={univers}
        langue={langue}
        liste="vie"
        compte={compte}
        actif={actif}
        onConnexionRequise={onConnexionRequise}
        onOuvrir={onOuvrir}
      />
      <Palmares
        univers={univers}
        langue={langue}
        liste="moment"
        compte={compte}
        actif={actif}
        onConnexionRequise={onConnexionRequise}
        onOuvrir={onOuvrir}
      />
      {communaute.length > 0 && (
        <section className="fives-communaute">
          <h4 className="fives-titre">{t.dit('fives.communaute')}</h4>
          <ul className="fives-communaute-liste">
            {communaute.map((five, indice) => (
              <li key={indice}>
                <p className="fives-communaute-qui">
                  <strong dir="auto">{five.pseudo ?? t.dit('fives.communaute_membre')}</strong>
                  {five.titre && <span dir="auto">« {five.titre} »</span>}
                </p>
                <ul className="fives-communaute-oeuvres">
                  {five.oeuvres.map((oeuvre) => {
                    const affiche = urlAffiche(oeuvre.affiche, 'w92')
                    return (
                      <li key={oeuvre.rang}>
                        <button
                          type="button"
                          onClick={() =>
                            oeuvre.id !== null && onOuvrir(oeuvre.id, oeuvre.oeuvreId)
                          }
                          title={oeuvre.titre ?? undefined}
                        >
                          {affiche ? (
                            <img src={affiche} alt="" loading="lazy" />
                          ) : (
                            <span className="fives-affiche-vide" aria-hidden="true" />
                          )}
                          <span dir="auto">{oeuvre.titre ?? t.dit('carte.sans_titre')}</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
