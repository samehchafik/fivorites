// La carte de présentation : l'affiche à gauche, l'essentiel à droite, les
// trois gestes en pied. La même carte sert la recherche et les suggestions —
// seule la ligne de raison (`explication`) les distingue.

import { urlAffiche } from './api'
import { BoutonsClassement } from './BoutonsClassement'
import type { Statut } from './types'

export function CarteOeuvre({
  titre,
  annee,
  affiche,
  genres,
  synopsis,
  note,
  explication,
  statutActuel,
  classable,
  onClasser,
  onDeclasser,
}: {
  titre: string | null
  annee: number | null
  affiche: string | null
  genres?: string[]
  synopsis?: string | null
  note?: number | null
  /** Pourquoi cette carte est là — affichée sur les suggestions seulement. */
  explication?: string
  statutActuel: Statut | null
  classable: boolean
  onClasser: (statut: Statut) => void
  onDeclasser: () => void
}) {
  const image = urlAffiche(affiche)
  return (
    <article className={`fivo-carte${statutActuel ? ` fivo-carte-${statutActuel}` : ''}`}>
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
            {titre ?? 'Sans titre'}
          </h3>
          {note != null && (
            <span className="fivo-note" title={`Note des votants : ${note.toFixed(1)} sur 10`}>
              ★ {note.toFixed(1)}
            </span>
          )}
        </header>
        <p className="fivo-meta">
          {annee ?? 'année inconnue'}
          {genres && genres.length > 0 && <> · {genres.slice(0, 3).join(', ')}</>}
        </p>
        {explication && <p className="fivo-explication">{explication}</p>}
        {synopsis && (
          <p className="fivo-synopsis" dir="auto">
            {synopsis}
          </p>
        )}
        <BoutonsClassement
          statutActuel={statutActuel}
          desactive={!classable}
          onClasser={onClasser}
          onDeclasser={onDeclasser}
        />
      </div>
    </article>
  )
}
