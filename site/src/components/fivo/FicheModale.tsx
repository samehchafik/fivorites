// L'œuvre en grand : ce qui s'ouvre au clic sur une carte.
//
// La carte sert à reconnaître et à classer ; celle-ci sert à décider — le
// synopsis entier, l'image de fond, les saisons, ceux qui la font avec leur
// visage. Et **les trois gestes y sont**, en pied comme sur la carte : c'est
// souvent ici qu'on se décide, ce serait absurde d'avoir à refermer pour
// classer.
//
// Mantine porte la modale (piège à focus, Échap, clic dehors, défilement du
// corps) ; le style reste celui de la V1, dans fivo.css.

import { Modal } from '@mantine/core'
import { useEffect, useState } from 'react'

import { chargerFiche, urlAffiche } from './api'
import { BoutonsClassement } from './BoutonsClassement'
import { SaisonsAccordeon } from './SaisonsAccordeon'
import type { Fiche, Statut, UniversSlug } from './types'

export function FicheModale({
  univers,
  identifiant,
  statutActuel,
  onFermer,
  onClasser,
  onDeclasser,
}: {
  univers: UniversSlug
  /** La clé de la vignette — `null` quand rien n'est ouvert. */
  identifiant: number | null
  statutActuel: Statut | null
  onFermer: () => void
  onClasser: (oeuvreId: number, statut: Statut) => void
  onDeclasser: (oeuvreId: number) => void
}) {
  const [fiche, setFiche] = useState<Fiche | null>(null)
  const [etat, setEtat] = useState<'en-cours' | 'servi' | 'erreur'>('en-cours')

  useEffect(() => {
    if (identifiant === null) return
    let abandonne = false
    setFiche(null)
    setEtat('en-cours')
    chargerFiche(univers, identifiant)
      .then((chargee) => {
        if (abandonne) return
        setFiche(chargee)
        setEtat('servi')
      })
      .catch(() => {
        if (!abandonne) setEtat('erreur')
      })
    return () => {
      abandonne = true
    }
  }, [univers, identifiant])

  const fond = urlAffiche(fiche?.fond ?? null, 'w780')
  const affiche = urlAffiche(fiche?.affiche ?? null, 'w342')

  return (
    <Modal
      opened={identifiant !== null}
      onClose={onFermer}
      size="lg"
      centered
      radius={6}
      padding={0}
      title={null}
      overlayProps={{ backgroundOpacity: 0.75, blur: 2 }}
      classNames={{
        content: 'fiche-modale',
        body: 'fiche-corps',
        // L'en-tête de Mantine ne porte que la croix : posée par-dessus
        // l'image plutôt qu'en bandeau blanc au-dessus d'elle.
        header: 'fiche-tete',
        close: 'fiche-fermer',
      }}
    >
      {etat === 'en-cours' && <p className="fivo-message">Chargement…</p>}
      {etat === 'erreur' && (
        <p className="fivo-message fivo-erreur">
          Cette fiche ne répond pas — réessayez dans un instant.
        </p>
      )}

      {fiche && (
        <article>
          {/* L'en-tête : l'image de fond en bandeau, l'affiche posée dessus.
              Sans image de fond (les livres n'en ont pas), le dégradé carmin
              tient le rôle — la modale garde sa silhouette. */}
          <header
            className={`fiche-entete${fond ? '' : ' fiche-entete-nue'}`}
            style={fond ? { backgroundImage: `url(${fond})` } : undefined}
          >
            <div className="fiche-entete-voile">
              {affiche ? (
                <img className="fiche-affiche" src={affiche} alt="" loading="lazy" />
              ) : (
                <div className="fiche-affiche fiche-affiche-vide" aria-hidden="true" />
              )}
              <div className="fiche-entete-texte">
                <h2 dir="auto">{fiche.titre ?? 'Sans titre'}</h2>
                {fiche.titreOriginal && fiche.titreOriginal !== fiche.titre && (
                  <p className="fiche-original" dir="auto">
                    {fiche.titreOriginal}
                  </p>
                )}
                {fiche.accroche && <p className="fiche-accroche">« {fiche.accroche} »</p>}
                <p className="fiche-faits">
                  {[
                    fiche.annee?.toString(),
                    fiche.saisonsTotal
                      ? `${fiche.saisonsTotal} saison${fiche.saisonsTotal > 1 ? 's' : ''}`
                      : null,
                    fiche.episodesTotal ? `${fiche.episodesTotal} épisodes` : null,
                    fiche.note ? `★ ${fiche.note.toFixed(1)}` : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
                {fiche.genres.length > 0 && (
                  <ul className="fiche-genres">
                    {fiche.genres.map((genre) => (
                      <li key={genre}>{genre}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </header>

          <div className="fiche-contenu">
            {fiche.synopsis && (
              <p className="fiche-synopsis" dir="auto">
                {fiche.synopsis}
              </p>
            )}

            {fiche.realisation.length > 0 && (
              <section className="fiche-section">
                <h3>{fiche.univers === 'livres' ? 'Écrit par' : 'Réalisé et créé par'}</h3>
                <p className="fiche-noms">
                  {fiche.realisation.map((personne) => personne.nom).join(', ')}
                </p>
              </section>
            )}

            {fiche.distribution.length > 0 && (
              <section className="fiche-section">
                <h3>À l'affiche</h3>
                <ul className="fiche-gens">
                  {fiche.distribution.map((personne) => {
                    const visage = urlAffiche(personne.photo, 'w185')
                    return (
                      <li key={`${personne.nom}-${personne.role ?? ''}`}>
                        {visage ? (
                          <img src={visage} alt="" loading="lazy" />
                        ) : (
                          <span className="fiche-visage-vide" aria-hidden="true" />
                        )}
                        <strong>{personne.nom}</strong>
                        {personne.role && <span>{personne.role}</span>}
                      </li>
                    )
                  })}
                </ul>
              </section>
            )}

            {fiche.saisons.length > 0 && identifiant !== null && (
              <section className="fiche-section">
                <h3>Les saisons</h3>
                {/* Déplier une saison charge ses épisodes — pas avant : une
                    série de huit saisons en porte deux cents. */}
                <SaisonsAccordeon
                  univers={univers}
                  identifiant={identifiant}
                  saisons={fiche.saisons}
                />
              </section>
            )}
          </div>

          {/* Les gestes, au pied et toujours visibles : c'est ici qu'on se
              décide. Sans pivot, l'œuvre n'est pas classable — les boutons le
              disent plutôt que de disparaître. */}
          <footer className="fiche-pied">
            <BoutonsClassement
              statutActuel={statutActuel}
              desactive={fiche.oeuvreId === null}
              onClasser={(statut) => fiche.oeuvreId !== null && onClasser(fiche.oeuvreId, statut)}
              onDeclasser={() => fiche.oeuvreId !== null && onDeclasser(fiche.oeuvreId)}
            />
          </footer>
        </article>
      )}
    </Modal>
  )
}
