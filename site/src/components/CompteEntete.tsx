// Le compte dans l'en-tête — la petite icône du carnet du designer.
//
// Déconnecté : une silhouette qui mène à la connexion (le module ouvre sa
// modale, la page défile jusqu'à lui). Connecté : la pastille du membre —
// son avatar, ou l'initiale de son pseudo — et un menu : ses infos (avatar,
// pseudo), la déconnexion.
//
// PAS de Mantine ici : l'îlot vit hors du module et de son thème, il reste
// du HTML nu stylé par global.css — l'en-tête doit peser trois fois rien.

import { useEffect, useRef, useState } from 'react'

import { deconnecter, modifierCompte, obtenirCompte } from './fivo/api'
import { annoncerCompte, demanderConnexion, surCompte } from './fivo/compteBus'
import type { Compte } from './fivo/types'
import { LANGUE_SENS, type Langue } from '../i18n/langues'
import { traduire } from '../i18n/textes'

// Les pastilles proposées — un choix fermé : pas d'image à héberger, pas de
// contenu à modérer, et toutes se lisent à 24 pixels.
const AVATARS = ['⭐', '🎬', '📚', '🎭', '🎸', '🚀', '🦊', '🐼', '🐉', '🌙', '🔥', '🌈']

export function CompteEntete({ langue }: { langue: Langue }) {
  const dire = (cle: Parameters<typeof traduire>[1]) => traduire(langue, cle)
  const [compte, setCompte] = useState<Compte | null>(null)
  const [ouvert, setOuvert] = useState(false)
  const [panneau, setPanneau] = useState<'menu' | 'infos'>('menu')
  const [pseudo, setPseudo] = useState('')
  const [avatar, setAvatar] = useState<string | null>(null)
  const [etat, setEtat] = useState<'repos' | 'envoi' | 'fait' | 'erreur'>('repos')
  const racine = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    obtenirCompte()
      .then(({ compte: retenu }) => setCompte(retenu))
      .catch(() => {
        // API muette : l'icône reste celle d'un anonyme.
      })
    return surCompte(setCompte)
  }, [])

  // Le menu se referme quand on clique ailleurs — le geste universel.
  useEffect(() => {
    if (!ouvert) return
    const fermer = (evenement: MouseEvent) => {
      if (racine.current && !racine.current.contains(evenement.target as Node)) {
        setOuvert(false)
      }
    }
    document.addEventListener('mousedown', fermer)
    return () => document.removeEventListener('mousedown', fermer)
  }, [ouvert])

  if (compte === null || !compte.verifie) {
    return (
      <button
        type="button"
        className="entete-compte-bouton"
        aria-label={dire('compte.titre_connexion')}
        title={dire('compte.titre_connexion')}
        onClick={() => {
          demanderConnexion()
          document.getElementById('suggere-moi')?.scrollIntoView({ behavior: 'smooth' })
        }}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" width="22" height="22">
          <circle cx="12" cy="8" r="4" fill="currentColor" />
          <path d="M4 20c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5z" fill="currentColor" />
        </svg>
      </button>
    )
  }

  const pastille = compte.avatar ?? compte.pseudo.trim().charAt(0).toUpperCase()

  const ouvrirInfos = () => {
    setPseudo(compte.pseudo)
    setAvatar(compte.avatar)
    setEtat('repos')
    setPanneau('infos')
  }

  const enregistrer = async () => {
    setEtat('envoi')
    try {
      const { compte: aJour } = await modifierCompte({
        pseudo: pseudo.trim() || undefined,
        // '' efface la pastille (retour à l'initiale) ; undefined n'y touche pas.
        avatar: avatar === compte.avatar ? undefined : (avatar ?? ''),
      })
      setCompte(aJour)
      annoncerCompte(aJour)
      setEtat('fait')
      setPanneau('menu')
    } catch {
      setEtat('erreur')
    }
  }

  const partir = async () => {
    setOuvert(false)
    try {
      await deconnecter()
    } finally {
      setCompte(null)
      annoncerCompte(null)
    }
  }

  return (
    <div className="entete-compte" ref={racine} lang={langue} dir={LANGUE_SENS[langue]}>
      <button
        type="button"
        className="entete-compte-bouton entete-compte-pastille"
        aria-label={dire('compte.menu_aria')}
        aria-expanded={ouvert}
        title={compte.pseudo}
        onClick={() => {
          setPanneau('menu')
          setOuvert(!ouvert)
        }}
      >
        {pastille}
      </button>
      {ouvert && (
        <div className="entete-compte-menu">
          {panneau === 'menu' ? (
            <>
              <p className="entete-compte-qui">
                <strong>{compte.pseudo}</strong>
                <span>{compte.email}</span>
              </p>
              <button type="button" onClick={ouvrirInfos}>
                {dire('compte.mes_infos')}
              </button>
              <button type="button" onClick={partir}>
                {dire('compte.deconnexion')}
              </button>
            </>
          ) : (
            <div className="entete-compte-infos">
              <p className="entete-compte-legende">{dire('compte.avatar_titre')}</p>
              <div className="entete-compte-avatars" role="listbox">
                <button
                  type="button"
                  className={avatar === null ? 'choisi' : undefined}
                  onClick={() => setAvatar(null)}
                  title={compte.pseudo}
                >
                  {compte.pseudo.trim().charAt(0).toUpperCase()}
                </button>
                {AVATARS.map((emoji) => (
                  <button
                    key={emoji}
                    type="button"
                    className={avatar === emoji ? 'choisi' : undefined}
                    onClick={() => setAvatar(emoji)}
                  >
                    {emoji}
                  </button>
                ))}
              </div>
              <p className="entete-compte-legende">{dire('compte.pseudo')}</p>
              <input
                type="text"
                value={pseudo}
                maxLength={40}
                onChange={(evenement) => setPseudo(evenement.currentTarget.value)}
              />
              {etat === 'erreur' && (
                <p className="entete-compte-erreur">{dire('compte.erreur_profil')}</p>
              )}
              <button type="button" disabled={etat === 'envoi'} onClick={enregistrer}>
                {dire('compte.enregistrer')}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default CompteEntete
