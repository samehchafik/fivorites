// La carte de présentation : l'affiche à gauche, l'essentiel à droite, les
// trois gestes en pied. La même carte sert la recherche et les suggestions —
// seule la ligne de raison (`explication`) les distingue.

import { urlAffiche } from './api'
import { BoutonsClassement } from './BoutonsClassement'
import { useTextes } from './textes'
import type { Statut } from './types'

export function CarteOeuvre({
  titre,
  annee,
  type,
  affiche,
  genres,
  synopsis,
  note,
  explication,
  fort,
  statutActuel,
  classable,
  onOuvrir,
  onClasser,
  onDeclasser,
}: {
  titre: string | null
  annee: number | null
  /** « Série », « Film », « Livre » — le type de l'œuvre, affiché en gras
   *  à côté de l'année. */
  type?: string
  affiche: string | null
  genres?: string[]
  synopsis?: string | null
  note?: number | null
  /** Pourquoi cette carte est là — affichée sur les suggestions seulement. */
  explication?: string
  /** La suggestion est corroborée : le contenu et la communauté tombent
   *  d'accord. C'est la plus solide, et son explication se détache. */
  fort?: boolean
  statutActuel: Statut | null
  classable: boolean
  /** Ouvre la fiche détaillée. Toute la carte y mène sauf les trois gestes,
   *  qui arrêtent la propagation : classer depuis la liste doit rester un
   *  seul clic. */
  onOuvrir: () => void
  onClasser: (statut: Statut) => void
  onDeclasser: () => void
}) {
  const t = useTextes()
  const image = urlAffiche(affiche)
  return (
    <article
      className={`fivo-carte${statutActuel ? ` fivo-carte-${statutActuel}` : ''}`}
      onClick={onOuvrir}
      role="button"
      tabIndex={0}
      aria-label={t.dit('carte.voir_fiche', { titre: titre ?? t.dit('carte.cette_oeuvre') })}
      onKeyDown={(evenement) => {
        if (evenement.key === 'Enter' || evenement.key === ' ') {
          evenement.preventDefault()
          onOuvrir()
        }
      }}
    >
      {image ? (
        <img className="fivo-affiche" src={image} alt="" loading="lazy" />
      ) : (
        <div className="fivo-affiche fivo-affiche-vide" aria-hidden="true">
          ?
        </div>
      )}
      <div className="fivo-corps">
        <header className="fivo-titre-ligne">
          <h3 className="fivo-titre" dir="auto">
            {titre ?? t.dit('carte.sans_titre')}
          </h3>
          {note != null && (
            <span className="fivo-note" title={t.dit('carte.note', { note: note.toFixed(1) })}>
              ★ {note.toFixed(1)}
            </span>
          )}
        </header>
        {/* L'année et le type en gras : ce sont les deux repères qu'on
            cherche d'abord dans une liste, avant les genres. */}
        <p className="fivo-meta">
          <strong>{annee ?? t.dit('carte.annee_inconnue')}</strong>
          {type && (
            <>
              {' · '}
              <strong>{type}</strong>
            </>
          )}
          {genres && genres.length > 0 && <> · {genres.slice(0, 3).join(', ')}</>}
        </p>
        {explication && (
          <p className={`fivo-explication${fort ? ' fivo-explication-forte' : ''}`}>
            {fort && <span aria-hidden="true">✦ </span>}
            {explication}
          </p>
        )}
        {synopsis && (
          <p className="fivo-synopsis" dir="auto">
            {synopsis}
          </p>
        )}
        {/* Les gestes vivent sur une carte entièrement cliquable : sans ce
            `stopPropagation`, classer ouvrirait aussi la fiche par-dessus. */}
        <div onClick={(evenement) => evenement.stopPropagation()}>
          <BoutonsClassement
            statutActuel={statutActuel}
            desactive={!classable}
            onClasser={onClasser}
            onDeclasser={onDeclasser}
          />
        </div>
      </div>
    </article>
  )
}
