// La porte du compte : se connecter, s'inscrire, donner le code reçu.
//
// Trois écrans dans une seule modale, et le fil le plus court possible —
// « accessible à presque un bébé » est le cahier des charges :
//
// * CONNEXION : email, mot de passe, un bouton. Un lien vers l'inscription.
// * INSCRIPTION : pseudo, email, mot de passe, fille/garçon (facultatif).
// * CODE : six chiffres reçus par email, une case, un bouton — et « renvoyer
//   un code » qui pardonne le mail perdu.
//
// La modale ne NAVIGUE jamais : tout est dans la page, et se fermer (après
// succès) rend l'écran exactement là où on l'avait laissé — c'est la
// promesse « revenir aux fives ».

import { Modal } from '@mantine/core'
import { useState } from 'react'

import { connecter, inscrire, renvoyerCode, verifierCode } from './api'
import { useTextes } from './textes'
import type { Compte } from './types'

type Ecran = 'connexion' | 'inscription' | 'code'

export function CompteModale({
  ouverte,
  langue,
  onFermer,
  onConnecte,
}: {
  ouverte: boolean
  langue: string
  onFermer: () => void
  /** Le compte est là, vérifié : la modale se ferme et l'appelant reprend. */
  onConnecte: (compte: Compte) => void
}) {
  const t = useTextes()
  const [ecran, setEcran] = useState<Ecran>('connexion')
  const [pseudo, setPseudo] = useState('')
  const [email, setEmail] = useState('')
  const [motDePasse, setMotDePasse] = useState('')
  const [genre, setGenre] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  const soumettre = async (action: () => Promise<void>) => {
    setAttente(true)
    setErreur(null)
    setInfo(null)
    try {
      await action()
    } finally {
      setAttente(false)
    }
  }

  const connexion = () =>
    soumettre(async () => {
      try {
        const reponse = await connecter(email, motDePasse, langue)
        if (reponse.verificationRequise) {
          setEcran('code')
          return
        }
        if (reponse.compte) onConnecte(reponse.compte)
      } catch {
        setErreur(t.dit('compte.erreur_connexion'))
      }
    })

  const inscription = () =>
    soumettre(async () => {
      try {
        await inscrire({ pseudo, email, motDePasse, genre, langue })
        setEcran('code')
      } catch (exception) {
        const statut = (exception as { status?: number }).status
        setErreur(t.dit(statut === 409 ? 'compte.erreur_existe' : 'compte.erreur'))
      }
    })

  const verification = () =>
    soumettre(async () => {
      try {
        const { compte } = await verifierCode(email, code)
        onConnecte(compte)
      } catch {
        setErreur(t.dit('compte.erreur_code'))
      }
    })

  const renvoi = () =>
    soumettre(async () => {
      await renvoyerCode(email, langue)
      setInfo(t.dit('compte.code_renvoye'))
    })

  const titres: Record<Ecran, string> = {
    connexion: t.dit('compte.titre_connexion'),
    inscription: t.dit('compte.titre_inscription'),
    code: t.dit('compte.titre_code'),
  }

  return (
    <Modal
      opened={ouverte}
      onClose={onFermer}
      size="sm"
      centered
      radius={8}
      padding={0}
      // Le titre vit dans la barre d'en-tête, à gauche de la croix — pas
      // dans le corps du message (retour du designer).
      title={
        <span lang={t.langue} dir={t.sens}>
          {titres[ecran]}
        </span>
      }
      overlayProps={{ backgroundOpacity: 0.8, blur: 2 }}
      classNames={{
        content: 'compte-modale',
        body: 'compte-corps',
        header: 'compte-tete',
        title: 'compte-titre',
        close: 'fiche-fermer',
      }}
    >
      <div className="compte" lang={t.langue} dir={t.sens}>
        {ecran !== 'code' && <p className="compte-pourquoi">{t.dit('compte.pourquoi')}</p>}

        {ecran === 'inscription' && (
          <input
            className="compte-champ"
            type="text"
            value={pseudo}
            onChange={(e) => setPseudo(e.currentTarget.value)}
            placeholder={t.dit('compte.pseudo')}
            autoComplete="nickname"
            maxLength={40}
          />
        )}

        {ecran !== 'code' && (
          <>
            <input
              className="compte-champ"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.currentTarget.value)}
              placeholder={t.dit('compte.email')}
              autoComplete="email"
              dir="ltr"
            />
            <input
              className="compte-champ"
              type="password"
              value={motDePasse}
              onChange={(e) => setMotDePasse(e.currentTarget.value)}
              placeholder={t.dit('compte.mot_de_passe')}
              autoComplete={ecran === 'inscription' ? 'new-password' : 'current-password'}
            />
          </>
        )}

        {ecran === 'inscription' && (
          <div className="compte-genre" role="group" aria-label={t.dit('compte.genre')}>
            <span>{t.dit('compte.genre')}</span>
            {(['fille', 'garcon'] as const).map((valeur) => (
              <button
                key={valeur}
                type="button"
                className={`compte-genre-choix${genre === valeur ? ' actif' : ''}`}
                aria-pressed={genre === valeur}
                onClick={() => setGenre(genre === valeur ? null : valeur)}
              >
                {t.dit(valeur === 'fille' ? 'compte.fille' : 'compte.garcon')}
              </button>
            ))}
          </div>
        )}

        {ecran === 'code' && (
          <>
            <p className="compte-pourquoi">{t.dit('compte.code_envoye', { email })}</p>
            <input
              className="compte-champ compte-code"
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={code}
              onChange={(e) => setCode(e.currentTarget.value.replace(/\D/g, '').slice(0, 6))}
              placeholder={t.dit('compte.code')}
              autoComplete="one-time-code"
              dir="ltr"
            />
          </>
        )}

        {erreur && <p className="compte-erreur">{erreur}</p>}
        {info && <p className="compte-info">{info}</p>}

        {ecran === 'connexion' && (
          <button
            type="button"
            className="compte-bouton"
            disabled={attente || !email || !motDePasse}
            onClick={connexion}
          >
            {t.dit('compte.bouton_connecter')}
          </button>
        )}
        {ecran === 'inscription' && (
          <button
            type="button"
            className="compte-bouton"
            disabled={attente || pseudo.length < 2 || !email || motDePasse.length < 8}
            onClick={inscription}
          >
            {t.dit('compte.bouton_inscrire')}
          </button>
        )}
        {ecran === 'code' && (
          <>
            <button
              type="button"
              className="compte-bouton"
              disabled={attente || code.length !== 6}
              onClick={verification}
            >
              {t.dit('compte.bouton_verifier')}
            </button>
            <button type="button" className="compte-lien" disabled={attente} onClick={renvoi}>
              {t.dit('compte.renvoyer')}
            </button>
          </>
        )}

        {ecran === 'connexion' && (
          <button type="button" className="compte-lien" onClick={() => setEcran('inscription')}>
            {t.dit('compte.vers_inscription')}
          </button>
        )}
        {ecran === 'inscription' && (
          <button type="button" className="compte-lien" onClick={() => setEcran('connexion')}>
            {t.dit('compte.vers_connexion')}
          </button>
        )}
      </div>
    </Modal>
  )
}
