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
import { useTextes } from './textes'
import { Videos } from './Videos'
import type { CleTexte } from '../../i18n/textes'
import type { Fiche, Statut, UniversSlug } from './types'

// Les types d'offre arrivent en code (`flatrate`, `free`…) : le libellé
// français que l'API joint sert de repli, pas de texte affiché.
const OFFRES: Record<string, CleTexte> = {
  flatrate: 'offre.flatrate',
  free: 'offre.free',
  ads: 'offre.ads',
  rent: 'offre.rent',
  buy: 'offre.buy',
}

export function FicheModale({
  univers,
  langue,
  identifiant,
  statutActuel,
  onFermer,
  onClasser,
  onDeclasser,
  onAgrandir,
  onOuvrirPersonne,
}: {
  univers: UniversSlug
  /** La langue : elle décide du titre, du synopsis et du pays dont on lit la
   *  disponibilité. « Sur Netflix » n'a de sens que quelque part. */
  langue: string
  /** La clé de la vignette — `null` quand rien n'est ouvert. */
  identifiant: number | null
  statutActuel: Statut | null
  onFermer: () => void
  onClasser: (oeuvreId: number, statut: Statut) => void
  onDeclasser: (oeuvreId: number) => void
  /** Ouvre une image en grand. */
  onAgrandir: (image: string, legende: string) => void
  /** Ouvre la filmographie de quelqu'un. */
  onOuvrirPersonne: (cle: string, nom: string, photo: string | null) => void
}) {
  const t = useTextes()
  const [fiche, setFiche] = useState<Fiche | null>(null)
  const [etat, setEtat] = useState<'en-cours' | 'servi' | 'erreur'>('en-cours')

  useEffect(() => {
    if (identifiant === null) return
    let abandonne = false
    setFiche(null)
    setEtat('en-cours')
    chargerFiche(univers, identifiant, langue)
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
  }, [univers, identifiant, langue])

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
      {etat === 'en-cours' && <p className="fivo-message">{t.dit('commun.chargement')}</p>}
      {etat === 'erreur' && <p className="fivo-message fivo-erreur">{t.dit('fiche.erreur')}</p>}

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
              {/* L'affiche s'agrandit au clic : à 118 pixels on la reconnaît,
                  on ne la regarde pas. */}
              {affiche ? (
                <button
                  type="button"
                  className="fiche-affiche-bouton"
                  onClick={() => onAgrandir(fiche.affiche ?? '', fiche.titre ?? '')}
                  title={t.dit('fiche.agrandir_affiche')}
                >
                  <img className="fiche-affiche" src={affiche} alt="" loading="lazy" />
                </button>
              ) : (
                <div className="fiche-affiche fiche-affiche-vide" aria-hidden="true" />
              )}
              <div className="fiche-entete-texte">
                <h2 dir="auto">{fiche.titre ?? t.dit('carte.sans_titre')}</h2>
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
                      ? t.compte(fiche.saisonsTotal, 'fiche.compte_saison', 'fiche.compte_saisons')
                      : null,
                    fiche.episodesTotal
                      ? t.dit('fiche.compte_episodes', { nombre: t.nombre(fiche.episodesTotal) })
                      : null,
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
                <h3>{t.dit(fiche.univers === 'livres' ? 'fiche.ecrit_par' : 'fiche.realise_par')}</h3>
                <p className="fiche-noms">
                  {fiche.realisation.map((personne, rang) => (
                    <span key={`${personne.nom}-${rang}`}>
                      {rang > 0 && ', '}
                      {personne.cle ? (
                        <button
                          type="button"
                          className="fiche-nom-lien"
                          onClick={() =>
                            onOuvrirPersonne(personne.cle!, personne.nom, personne.photo)
                          }
                          title={t.dit('fiche.filmographie', { nom: personne.nom })}
                        >
                          {personne.nom}
                        </button>
                      ) : (
                        personne.nom
                      )}
                    </span>
                  ))}
                </p>
              </section>
            )}

            {fiche.distribution.length > 0 && (
              <section className="fiche-section">
                <h3>{t.dit('fiche.distribution')}</h3>
                <ul className="fiche-gens">
                  {fiche.distribution.map((personne) => {
                    const visage = urlAffiche(personne.photo, 'w185')
                    return (
                      <li key={`${personne.nom}-${personne.role ?? ''}`}>
                        {/* Cliquer quelqu'un ouvre sa filmographie. Sans clé
                            — la source ne l'a pas donnée — on se contente
                            d'agrandir son portrait : ouvrir la filmographie
                            d'un homonyme serait pire que ne rien faire. */}
                        <button
                          type="button"
                          className="fiche-gens-bouton"
                          onClick={() =>
                            personne.cle
                              ? onOuvrirPersonne(personne.cle, personne.nom, personne.photo)
                              : personne.photo && onAgrandir(personne.photo, personne.nom)
                          }
                          title={
                            personne.cle
                              ? t.dit('fiche.filmographie', { nom: personne.nom })
                              : personne.nom
                          }
                        >
                          {visage ? (
                            <img src={visage} alt="" loading="lazy" />
                          ) : (
                            <span className="fiche-visage-vide" aria-hidden="true" />
                          )}
                          <strong>{personne.nom}</strong>
                          {personne.role && <span>{personne.role}</span>}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </section>
            )}

            {/* Où regarder — la donnée vient de JustWatch via TMDB, qui impose
                de citer la source : c'est ce que fait le lien. */}
            {fiche.offres.length > 0 && (
              <section className="fiche-section">
                <h3>{t.dit('fiche.ou_regarder')}</h3>
                {fiche.offres.map((offre) => (
                  <div key={offre.genre} className="fiche-offre">
                    <span className="fiche-offre-libelle">
                      {OFFRES[offre.genre] ? t.dit(OFFRES[offre.genre]) : offre.libelle}
                    </span>
                    <ul className="fiche-plateformes">
                      {offre.plateformes.map((plateforme) => (
                        <li key={plateforme.nom} title={plateforme.nom}>
                          {plateforme.logo ? (
                            <img
                              src={urlAffiche(plateforme.logo, 'w92') ?? ''}
                              alt={plateforme.nom}
                              loading="lazy"
                            />
                          ) : (
                            <span>{plateforme.nom}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                {fiche.lienOffres && (
                  <p className="fiche-source">
                    <a href={fiche.lienOffres} target="_blank" rel="noreferrer noopener">
                      {t.dit('fiche.source_offres')}
                    </a>
                  </p>
                )}
              </section>
            )}

            {/* Aucune offre ici, mais ailleurs : le dire vaut mieux qu'un
                silence qu'on prendrait pour une donnée manquante. */}
            {fiche.offres.length === 0 && fiche.paysOffres.length > 0 && (
              <section className="fiche-section">
                <h3>{t.dit('fiche.ou_regarder')}</h3>
                <p className="fiche-noms">
                  {t.compte(fiche.paysOffres.length, 'fiche.ailleurs_un', 'fiche.ailleurs')}
                </p>
              </section>
            )}

            {/* Les bandes-annonces : lecteur intégré, ouvert au clic
                seulement (voir `Videos`). Un lien sortant emportait le
                visiteur — et sa recherche, ses filtres, sa pile. */}
            {fiche.videos.length > 0 && (
              <section className="fiche-section">
                <h3>{t.dit('fiche.videos')}</h3>
                <Videos videos={fiche.videos} />
              </section>
            )}

            {fiche.saisons.length > 0 && identifiant !== null && (
              <section className="fiche-section">
                <h3>{t.dit('fiche.saisons')}</h3>
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
