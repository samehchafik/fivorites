// Quelqu'un : son portrait en grand, et sa filmographie page par page.
//
// Ce qui s'ouvre au clic sur un acteur, un réalisateur, un auteur. Deux
// choses à savoir sur ce que ce panneau montre :
//
// * **la source est nommée**. Avec le graphe, la filmographie est exacte et
//   tous univers confondus — la personne y est un nœud, ses œuvres sont ses
//   relations. Sans lui, le serveur cherche par le NOM dans l'index d'un seul
//   univers : deux homonymes s'y confondent, et le dire vaut mieux que de
//   laisser croire à une liste complète ;
// * **cliquer une œuvre y va**. La modale de fiche se recharge sur elle, et
//   le panneau se referme : on navigue d'un acteur à ses films, puis d'un film
//   à ses acteurs, sans jamais empiler trois fenêtres.

import { Modal } from '@mantine/core'
import { useEffect, useState } from 'react'

import { chargerPersonne, urlAffiche } from './api'
import { useTextes } from './textes'
import type { CleTexte } from '../../i18n/textes'
import type { FichePersonne, UniversSlug } from './types'

// Le rôle arrive du graphe en code (voir `fiv_webapp.personnes.ROLES`).
const ROLES: Record<string, CleTexte> = {
  interpretation: 'role.interpretation',
  realisation: 'role.realisation',
  creation: 'role.creation',
  auteur: 'role.auteur',
}

export function PersonneModale({
  cle,
  nom,
  photo,
  univers,
  onFermer,
  onOuvrirOeuvre,
  onAgrandir,
}: {
  /** L'identité de la personne — `null` quand rien n'est ouvert. */
  cle: string | null
  /** Le nom et la photo qu'on affichait déjà : ils s'affichent tout de suite,
   *  sans attendre la requête, et servent de repli si le serveur n'a que la
   *  liste (le repli par l'index ne rend pas les portraits). */
  nom: string | null
  photo: string | null
  univers: UniversSlug
  onFermer: () => void
  onOuvrirOeuvre: (identifiant: number, oeuvreId: number, univers: UniversSlug) => void
  onAgrandir: (image: string, legende: string) => void
}) {
  const t = useTextes()
  const [fiche, setFiche] = useState<FichePersonne | null>(null)
  const [page, setPage] = useState(1)
  const [etat, setEtat] = useState<'en-cours' | 'servi' | 'erreur'>('en-cours')

  // La page revient à 1 dès qu'on change de personne : garder la page 3 d'un
  // acteur en ouvrant le suivant afficherait un panneau vide.
  useEffect(() => {
    setPage(1)
  }, [cle])

  useEffect(() => {
    if (cle === null) return
    let abandonne = false
    setEtat('en-cours')
    chargerPersonne(cle, { page, univers, nom: nom ?? undefined })
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
  }, [cle, page, univers, nom])

  const portrait = urlAffiche(fiche?.photo ?? photo, 'w342')
  const total = fiche?.total ?? 0
  const parPage = fiche?.parPage ?? 10
  const pages = Math.max(1, Math.ceil(total / parPage))

  return (
    <Modal
      opened={cle !== null}
      onClose={onFermer}
      size="lg"
      centered
      radius={6}
      padding={0}
      title={null}
      overlayProps={{ backgroundOpacity: 0.8, blur: 2 }}
      classNames={{
        content: 'fiche-modale',
        body: 'fiche-corps',
        header: 'fiche-tete',
        close: 'fiche-fermer',
      }}
    >
      <article className="personne">
        <header className="personne-entete">
          {portrait ? (
            // Le portrait s'agrandit : c'est le geste demandé, et le même que
            // sur l'affiche d'une œuvre.
            <button
              type="button"
              className="personne-portrait"
              onClick={() =>
                onAgrandir(fiche?.photo ?? photo ?? '', fiche?.nom ?? nom ?? '')
              }
              title={t.dit('personne.agrandir')}
            >
              <img src={portrait} alt="" />
            </button>
          ) : (
            <span className="personne-portrait personne-portrait-vide" aria-hidden="true" />
          )}
          <div>
            <h2>{fiche?.nom ?? nom ?? t.dit('personne.inconnue')}</h2>
            {etat === 'servi' && (
              <p className="personne-compte">
                {total > 0
                  ? t.compte(total, 'personne.compte_une', 'personne.compte')
                  : t.dit('personne.aucune')}
                {/* La source change ce qu'on regarde : une liste tirée du nom
                    peut mêler deux homonymes, et se limite à un univers. */}
                {fiche?.source === 'index' && (
                  <span className="personne-source">
                    {t.dit('personne.par_le_nom', { univers: t.dit(`nav.${univers}`).toLowerCase() })}
                  </span>
                )}
              </p>
            )}
          </div>
        </header>

        <div className="fiche-contenu">
          {etat === 'en-cours' && <p className="fivo-message">{t.dit('commun.chargement')}</p>}
          {etat === 'erreur' && (
            <p className="fivo-message fivo-erreur">{t.dit('personne.erreur')}</p>
          )}

          {fiche && fiche.oeuvres.length > 0 && (
            <ul className="personne-oeuvres">
              {fiche.oeuvres.map((oeuvre) => {
                const affiche = urlAffiche(oeuvre.affiche, 'w185')
                return (
                  <li key={`${oeuvre.univers}-${oeuvre.oeuvreId}`}>
                    <button
                      type="button"
                      onClick={() =>
                        onOuvrirOeuvre(oeuvre.id, oeuvre.oeuvreId, oeuvre.univers)
                      }
                      title={t.dit('personne.ouvrir', {
                        titre: oeuvre.titre ?? t.dit('carte.cette_oeuvre'),
                      })}
                    >
                      {affiche ? (
                        <img src={affiche} alt="" loading="lazy" />
                      ) : (
                        <span className="personne-affiche-vide" aria-hidden="true" />
                      )}
                      <span className="personne-oeuvre-texte">
                        <strong dir="auto">{oeuvre.titre ?? t.dit('carte.sans_titre')}</strong>
                        <span>
                          {[
                            oeuvre.annee?.toString(),
                            oeuvre.role && ROLES[oeuvre.role]
                              ? t.dit(ROLES[oeuvre.role])
                              : oeuvre.role,
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}

          {/* La pagination : dix par page, et on ne l'affiche pas quand il n'y
              a qu'une page — un « 1 / 1 » n'informe personne. */}
          {pages > 1 && (
            <nav className="personne-pages" aria-label={t.dit('personne.pages')}>
              <button
                type="button"
                disabled={page <= 1 || etat === 'en-cours'}
                onClick={() => setPage((courante) => Math.max(1, courante - 1))}
              >
                {t.dit('personne.precedentes')}
              </button>
              <span>
                {page} / {pages}
              </span>
              <button
                type="button"
                disabled={page >= pages || etat === 'en-cours'}
                onClick={() => setPage((courante) => Math.min(pages, courante + 1))}
              >
                {t.dit('personne.suivantes')}
              </button>
            </nav>
          )}
        </div>
      </article>
    </Modal>
  )
}
