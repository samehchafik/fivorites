import type { WorkState } from './types'

/** Vocabulaire des états. Une seule définition, pour que la légende du tableau,
 *  les pastilles et le filtre disent exactement la même chose. */
export const STATE_LABELS: Record<WorkState, { label: string; color: string; help: string }> = {
  absent: {
    label: 'jamais collectée',
    color: 'gray',
    help: "Au catalogue, mais la collecte ne l'a pas encore regardée.",
  },
  error: {
    label: 'en échec',
    color: 'red',
    help: "Regardée, jamais aboutie — voir le code HTTP du dernier passage.",
  },
  series_only: {
    label: 'fiche seule',
    color: 'yellow',
    help: 'Fiche récupérée, mais aucune partie énumérée à collecter.',
  },
  lang_missing: {
    label: 'langue absente',
    color: 'orange',
    help: 'Des parties existent, mais aucune dans la langue choisie.',
  },
  partial: {
    label: 'partielle',
    color: 'blue',
    help: 'Couverture incomplète dans la langue choisie.',
  },
  complete: {
    label: 'complète',
    color: 'teal',
    help: 'Toutes les parties énumérées sont collectées dans cette langue.',
  },
}

export const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: 'all', label: 'Tout le catalogue' },
  { value: 'absent', label: 'Jamais collectées' },
  { value: 'collected', label: 'Fiche collectée' },
  { value: 'error', label: 'En échec' },
  { value: 'lang_ok', label: 'Présentes dans la langue' },
  { value: 'lang_missing', label: 'Absentes de la langue' },
]

export const SORT_LABELS: Record<string, string> = {
  popularity: 'Popularité',
  id: 'Id TMDB',
  name: 'Titre original',
  fetched: 'Dernière collecte',
}

const numberFormat = new Intl.NumberFormat('fr-FR')
const dateFormat = new Intl.DateTimeFormat('fr-FR', {
  dateStyle: 'short',
  timeStyle: 'short',
})

export const formatNumber = (value: number): string => numberFormat.format(value)

export const formatDate = (value: string | null | undefined): string =>
  value ? dateFormat.format(new Date(value)) : '—'

export const formatPercent = (ratio: number | null | undefined): string =>
  ratio === null || ratio === undefined ? '—' : `${Math.round(ratio * 100)} %`

/** Un titre en écriture arabe doit s'afficher de droite à gauche, même dans une
 *  interface en français. `dir="auto"` laisse le navigateur trancher sur le
 *  premier caractère fort — c'est exactement ce qu'on veut pour une colonne qui
 *  mélange les alphabets. */
export const titleDirection = 'auto' as const

/** Placeholder d'affiche : un visuel manquant ne doit pas laisser un trou.
 *  Une image TMDB peut être absente du payload (`poster_path` nul) ou avoir
 *  disparu depuis la collecte — le brut garde le chemin, pas le fichier. */
export const POSTER_FALLBACK =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 3">' +
      '<rect width="2" height="3" fill="#e9ecef"/>' +
      '<path d="M0.55 1.9l0.35-0.45 0.3 0.35 0.35-0.5 0.45 0.6z" fill="#adb5bd"/>' +
      '<circle cx="0.72" cy="1.2" r="0.12" fill="#adb5bd"/>' +
      '</svg>',
  )
