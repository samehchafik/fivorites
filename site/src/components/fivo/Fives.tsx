// Les fives : vos cinq meilleures œuvres, par univers — LE geste du site.
//
// Le cahier des charges est « accessible à presque un bébé », et la mise en
// page le prend au mot : CINQ GRANDES CASES numérotées, rien d'autre.
// Toucher une case vide ouvre une recherche dans la case même ; toucher un
// résultat la remplit. Toucher le ✕ d'une case pleine la vide. Il n'y a
// rien à apprendre.
//
// Sans compte, le serveur répond 401 `connexion_requise` : le panneau ouvre
// la modale de compte, et comme tout est dans la même page, la fermeture de
// la modale rend les fives exactement là où on les avait laissées.

import { useEffect, useRef, useState } from 'react'

import { chargerFives, poserFive, rechercher, retirerFive, urlAffiche, ApiErreur } from './api'
import { useTextes } from './textes'
import type { Carte, Compte, Five, UniversSlug } from './types'

const RANGS = [1, 2, 3, 4, 5]

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
      const reponse = await chargerFives(univers)
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

  useEffect(() => {
    if (!actif) return
    const identite = compte?.id ?? null
    if (charge.current?.univers === univers && charge.current.compte === identite) return
    charge.current = { univers, compte: identite }
    setRangOuvert(null)
    setFrappe('')
    setFives([])
    void recharger()
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
    try {
      await poserFive(univers, rang, carte.oeuvreId)
      setRangOuvert(null)
      setFrappe('')
      setResultats([])
      await recharger()
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) onConnexionRequise()
    }
  }

  const retirer = async (rang: number) => {
    try {
      await retirerFive(univers, rang)
      await recharger()
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) onConnexionRequise()
    }
  }

  if (etat === 'connexion') {
    return (
      <div className="fives">
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

  return (
    <div className="fives">
      <h4 className="fives-titre">{t.dit(`fives.titre.${univers}`)}</h4>
      <p className="fives-consigne">{t.dit('fives.consigne')}</p>
      <ol className="fives-cases">
        {RANGS.map((rang) => {
          const five = parRang.get(rang)
          const affiche = urlAffiche(five?.affiche ?? null, 'w342')
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
    </div>
  )
}
