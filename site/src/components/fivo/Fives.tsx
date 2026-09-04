// Les fives : des TOP 5 en nombre libre — dont UN est « de ma vie ».
//
// On crée autant de TOP 5 qu'on veut, on les nomme (« Mes polars »…), et un
// seul porte la couronne « Le TOP 5 de ma vie » — le premier créé la reçoit
// d'office, les autres peuvent la lui prendre. Chaque TOP 5 est un plateau
// de CINQ RANGÉES numérotées : toucher une rangée vide ouvre une recherche
// sur place ; toucher un résultat la remplit ; le ✕ la vide.
//
// Sans compte, PAS de barrière : « Commence ton premier five » ouvre le
// premier plateau, et tout se compose en silence, en local — le serveur
// n'est pas consulté. La connexion n'arrive qu'à la FIN, au moment de
// garder ; chaque brouillon est alors versé au compte, palmarès par
// palmarès, rang par rang.
//
// Et sous les siens, les fives de la COMMUNAUTÉ : des listes de membres de
// la V1, tirées au sort — anonymes, leur import les a masqués.

import { useEffect, useRef, useState } from 'react'

import {
  chargerPalmares,
  creerPalmares,
  fivesCommunaute,
  poserPosition,
  rechercher,
  retirerPosition,
  retoucherPalmares,
  supprimerPalmares,
  urlAffiche,
  ApiErreur,
} from './api'
import { useTextes } from './textes'
import type { Carte, Compte, Five, FiveCommunaute, Palmares, UniversSlug } from './types'

const RANGS = [1, 2, 3, 4, 5]

// Les brouillons anonymes vivent dans localStorage : ils survivent à
// l'aller-retour vers la boîte mail pour le code de vérification, même si
// l'onglet se ferme. Leurs ids sont locaux (« brouillon-… ») — le versement
// au compte leur en donne de vrais.
const cleBrouillons = (univers: UniversSlug) => `fivo.palmares.${univers}`

export function lirePalmaresLocaux(univers: UniversSlug): Palmares[] {
  try {
    // Les clés d'AVANT ce modèle (un plateau « vie », un plateau « moment »)
    // se relisent une dernière fois et deviennent des palmarès — personne ne
    // perd un brouillon parce que le produit a affiné son idée.
    const anciens: Palmares[] = []
    for (const [cle, vie] of [
      [`fivo.brouillon.${univers}`, true],
      [`fivo.brouillon.${univers}.moment`, false],
    ] as const) {
      const brut = localStorage.getItem(cle)
      if (brut) {
        const lu: unknown = JSON.parse(brut)
        if (Array.isArray(lu) && lu.length > 0) {
          anciens.push({ id: `brouillon-${cle}`, titre: null, vie, oeuvres: lu as Five[] })
        }
        localStorage.removeItem(cle)
      }
    }
    const brut = localStorage.getItem(cleBrouillons(univers))
    const lu: unknown = brut ? JSON.parse(brut) : []
    const palmares = (Array.isArray(lu) ? (lu as Palmares[]) : []).filter(
      (palm) => typeof palm?.id === 'string' && Array.isArray(palm?.oeuvres),
    )
    const tous = [...palmares, ...anciens]
    if (anciens.length > 0) ecrirePalmaresLocaux(univers, tous)
    return tous
  } catch {
    return []
  }
}

export function ecrirePalmaresLocaux(univers: UniversSlug, palmares: Palmares[]) {
  try {
    if (palmares.length === 0) localStorage.removeItem(cleBrouillons(univers))
    else localStorage.setItem(cleBrouillons(univers), JSON.stringify(palmares))
  } catch {
    // Navigation privée : le brouillon ne survivra pas au rechargement — le
    // plateau, lui, continue de fonctionner en mémoire.
  }
}

const idLocal = () => `brouillon-${Date.now()}-${Math.floor(Math.random() * 1e6)}`

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
  const [palmares, setPalmares] = useState<Palmares[]>([])
  const [etat, setEtat] = useState<'en-cours' | 'servi' | 'erreur'>('en-cours')
  // La rangée en cours de remplissage — un plateau à la fois — et sa
  // recherche ; le palmarès en cours de renommage, et son texte.
  const [ouvert, setOuvert] = useState<{ palmaresId: string; rang: number } | null>(null)
  const [frappe, setFrappe] = useState('')
  const [resultats, setResultats] = useState<Carte[]>([])
  const [renomme, setRenomme] = useState<{ palmaresId: string; texte: string } | null>(null)
  const [communaute, setCommunaute] = useState<FiveCommunaute[]>([])
  const charge = useRef<{ univers: UniversSlug; compte: string | null } | null>(null)
  const vitrine = useRef<UniversSlug | null>(null)

  const fermerSaisies = () => {
    setOuvert(null)
    setFrappe('')
    setResultats([])
    setRenomme(null)
  }

  const recharger = async () => {
    setEtat('en-cours')
    try {
      const reponse = await chargerPalmares(univers)
      setPalmares(reponse.items)
      setEtat('servi')
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) {
        // La session a expiré sous nos pieds : retour au parcours anonyme.
        setPalmares(lirePalmaresLocaux(univers))
        setEtat('servi')
        onConnexionRequise()
      } else {
        setEtat('erreur')
      }
    }
  }

  // Un compte vient d'apparaître (ou l'onglet s'ouvre connecté) : les
  // brouillons locaux sont versés au compte AVANT la lecture — c'est la
  // promesse du parcours anonyme. Meilleur effort : un palmarès qui échoue
  // ne fait pas perdre les autres.
  const verserPuisRecharger = async () => {
    const brouillons = lirePalmaresLocaux(univers)
    if (brouillons.length > 0) {
      setEtat('en-cours')
      for (const brouillon of brouillons) {
        try {
          const { palmares: cree } = await creerPalmares(univers, brouillon.titre ?? undefined)
          if (brouillon.vie && !cree.vie) {
            await retoucherPalmares(cree.id, { vie: true })
          }
          for (const oeuvre of brouillon.oeuvres) {
            try {
              await poserPosition(cree.id, oeuvre.rang, oeuvre.oeuvreId)
            } catch {
              // Œuvre disparue : les autres rangs passent quand même.
            }
          }
        } catch {
          // Ce palmarès attendra une prochaine connexion.
        }
      }
      ecrirePalmaresLocaux(univers, [])
    }
    await recharger()
  }

  useEffect(() => {
    if (!actif) return
    const identite = compte?.id ?? null
    if (charge.current?.univers === univers && charge.current.compte === identite) return
    charge.current = { univers, compte: identite }
    fermerSaisies()
    setPalmares([])
    if (identite === null) {
      // Personne de connecté : tout se compose en silence, en local — pas
      // un mot au serveur.
      setPalmares(lirePalmaresLocaux(univers))
      setEtat('servi')
    } else {
      void verserPuisRecharger()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actif, univers, compte?.id])

  // La vitrine de la communauté — publique, indépendante du compte.
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

  // La recherche de la rangée ouverte : la même API que l'onglet Recherche,
  // débouncée pareil.
  useEffect(() => {
    const propre = frappe.trim()
    if (ouvert === null || propre.length < 2) {
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
  }, [frappe, ouvert, univers, langue])

  // --- les gestes — chacun a sa version locale (anonyme) et serveur -------

  const majLocale = (suivants: Palmares[]) => {
    setPalmares(suivants)
    ecrirePalmaresLocaux(univers, suivants)
  }

  const creer = async () => {
    fermerSaisies()
    if (compte === null) {
      const nouveau: Palmares = {
        id: idLocal(),
        titre: null,
        // Le premier TOP 5 est d'office celui de ma vie.
        vie: !palmares.some((palm) => palm.vie),
        oeuvres: [],
      }
      majLocale([...palmares, nouveau])
      return
    }
    try {
      await creerPalmares(univers)
      await recharger()
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) onConnexionRequise()
    }
  }

  const poser = async (palmaresId: string, rang: number, carte: Carte) => {
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
      const suivants = palmares.map((palm) =>
        palm.id === palmaresId
          ? {
              ...palm,
              oeuvres: [...palm.oeuvres.filter((oeuvre) => oeuvre.rang !== rang), pose].sort(
                (a, b) => a.rang - b.rang,
              ),
            }
          : palm,
      )
      majLocale(suivants)
      setOuvert(null)
      setFrappe('')
      setResultats([])
      // La cinquième rangée vient d'être posée : c'est maintenant — et
      // seulement maintenant — qu'on parle de compte, pour garder.
      const rempli = suivants.find((palm) => palm.id === palmaresId)
      if (rempli && rempli.oeuvres.length === RANGS.length) onConnexionRequise()
      return
    }
    try {
      await poserPosition(palmaresId, rang, carte.oeuvreId)
      setOuvert(null)
      setFrappe('')
      setResultats([])
      await recharger()
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) onConnexionRequise()
    }
  }

  const retirer = async (palmaresId: string, rang: number) => {
    if (compte === null) {
      majLocale(
        palmares.map((palm) =>
          palm.id === palmaresId
            ? { ...palm, oeuvres: palm.oeuvres.filter((oeuvre) => oeuvre.rang !== rang) }
            : palm,
        ),
      )
      return
    }
    try {
      await retirerPosition(palmaresId, rang)
      await recharger()
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) onConnexionRequise()
    }
  }

  const promouvoir = async (palmaresId: string) => {
    if (compte === null) {
      majLocale(palmares.map((palm) => ({ ...palm, vie: palm.id === palmaresId })))
      return
    }
    try {
      await retoucherPalmares(palmaresId, { vie: true })
      await recharger()
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) onConnexionRequise()
    }
  }

  const renommer = async (palmaresId: string, texte: string) => {
    const titre = texte.trim()
    setRenomme(null)
    if (compte === null) {
      majLocale(
        palmares.map((palm) =>
          palm.id === palmaresId ? { ...palm, titre: titre || null } : palm,
        ),
      )
      return
    }
    try {
      await retoucherPalmares(palmaresId, { titre })
      await recharger()
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) onConnexionRequise()
    }
  }

  const supprimer = async (palmaresId: string) => {
    if (!window.confirm(t.dit('fives.confirmer_suppression'))) return
    if (compte === null) {
      majLocale(palmares.filter((palm) => palm.id !== palmaresId))
      return
    }
    try {
      await supprimerPalmares(palmaresId)
      await recharger()
    } catch (exception) {
      if (exception instanceof ApiErreur && exception.status === 401) onConnexionRequise()
    }
  }

  // --- le rendu -----------------------------------------------------------

  if (etat === 'erreur') {
    return <p className="fivo-message fivo-erreur">{t.dit('fives.erreur')}</p>
  }
  if (etat === 'en-cours') {
    return <p className="fivo-message">{t.dit('commun.chargement')}</p>
  }

  if (palmares.length === 0) {
    // L'accueil : pas de formulaire, pas de barrière — un seul bouton qui
    // crée le premier TOP 5 (local sans compte, au serveur avec).
    return (
      <div className="fives fives-accueil">
        <p className="fives-pitch">{t.dit(`fives.pitch.${univers}`)}</p>
        <h4 className="fives-titre">{t.dit(`fives.titre.${univers}`)}</h4>
        <button type="button" className="compte-bouton fives-commencer" onClick={creer}>
          {t.dit('fives.commencer')}
        </button>
      </div>
    )
  }

  const brouillonsPoses =
    compte === null && palmares.some((palm) => palm.oeuvres.length > 0)

  return (
    <div className="fives">
      <p className="fives-pitch">{t.dit(`fives.pitch.${univers}`)}</p>
      <p className="fives-consigne">{t.dit('fives.consigne')}</p>

      {palmares.map((palm) => {
        const parRang = new Map(palm.oeuvres.map((oeuvre) => [oeuvre.rang, oeuvre]))
        const titre = palm.titre ?? (palm.vie ? t.dit('liste.top5') : t.dit('fives.sans_titre'))
        return (
          <section key={palm.id} className="fives-palmares">
            <header className="fives-palmares-tete">
              {palm.vie && (
                <span className="fives-couronne" title={t.dit('liste.top5')}>
                  ★
                </span>
              )}
              {renomme?.palmaresId === palm.id ? (
                <input
                  className="compte-champ fives-renommage"
                  type="text"
                  autoFocus
                  maxLength={80}
                  value={renomme.texte}
                  onChange={(e) => setRenomme({ palmaresId: palm.id, texte: e.currentTarget.value })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void renommer(palm.id, renomme.texte)
                    if (e.key === 'Escape') setRenomme(null)
                  }}
                  onBlur={() => void renommer(palm.id, renomme.texte)}
                />
              ) : (
                <h4 className="fives-titre" dir="auto">
                  {titre}
                </h4>
              )}
              <span className="fives-palmares-gestes">
                <button
                  type="button"
                  className="compte-lien"
                  onClick={() => setRenomme({ palmaresId: palm.id, texte: palm.titre ?? '' })}
                >
                  {t.dit('fives.renommer')}
                </button>
                {!palm.vie && (
                  <>
                    <button
                      type="button"
                      className="compte-lien"
                      onClick={() => promouvoir(palm.id)}
                    >
                      ★ {t.dit('fives.promouvoir')}
                    </button>
                    <button
                      type="button"
                      className="compte-lien"
                      onClick={() => supprimer(palm.id)}
                    >
                      {t.dit('fives.supprimer')}
                    </button>
                  </>
                )}
              </span>
            </header>
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
                        onClick={() => retirer(palm.id, rang)}
                      >
                        ✕
                      </button>
                    </li>
                  )
                }
                if (ouvert?.palmaresId === palm.id && ouvert.rang === rang) {
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
                              <button type="button" onClick={() => poser(palm.id, rang, carte)}>
                                {urlAffiche(carte.affiche, 'w92') && (
                                  <img
                                    src={urlAffiche(carte.affiche, 'w92')!}
                                    alt=""
                                    loading="lazy"
                                  />
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
                          setOuvert(null)
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
                        setOuvert({ palmaresId: palm.id, rang })
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
          </section>
        )
      })}

      <p className="fives-nouveau">
        <button type="button" className="compte-lien" onClick={creer}>
          + {t.dit('fives.nouveau')}
        </button>
      </p>

      {brouillonsPoses && (
        <div className="fives-garder">
          <button type="button" className="compte-bouton" onClick={onConnexionRequise}>
            {t.dit('fives.garder')}
          </button>
          <p className="fives-garder-note">{t.dit('fives.garder_note')}</p>
        </div>
      )}

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
