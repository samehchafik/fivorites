// Le contrat avec l'API. Une seule source par forme de réponse : si le back
// change, c'est ici que la compilation le dit.

/** Les six états qu'une œuvre peut avoir **dans une langue donnée**. */
export type WorkState =
  | 'absent' // jamais regardée
  | 'error' // regardée, jamais aboutie
  | 'series_only' // fiche récupérée, aucune partie énumérée
  | 'lang_missing' // parties connues, aucune dans cette langue
  | 'partial' // couverture incomplète dans cette langue
  | 'complete'

export interface Coverage {
  ok: number
  failed: number
  lastAt: string | null
}

export interface FetchState {
  lastFetchedAt: string | null
  lastSuccessAt: string | null
  lastChangedAt: string | null
  lastStatus: number | null
  lastError: string | null
  attempts: number
  partsLastAt?: string | null
  priority?: number | null
}

export interface Item {
  id: number
  title: string | null
  popularity: number
  adult: boolean
  exportedOn: string
  /** Parties énumérées par la collecte — le dénominateur de la couverture. */
  expectedParts: number
  /** Une entrée par langue présente en base, toutes langues confondues. */
  coverage: Record<string, Coverage>
  selected: {
    lang: string
    ok: number
    failed: number
    lastAt: string | null
    /** null quand rien n'a encore été énuméré : « aucune donnée », pas « 0 % ». */
    ratio: number | null
  }
  fetch: FetchState
  state: WorkState
}

export interface ItemsResponse {
  items: Item[]
  total: number
  page: number
  pageSize: number
  lang: string
  languages: string[]
  truncatedToFetched: boolean
}

export interface Summary {
  catalog: { total: number; popular: number; exportedOn: string | null }
  works: {
    seen: number
    ok: number
    failed: number
    /** Ce qui n'a jamais été regardé — la réponse à « combien reste-t-il ». */
    remaining: number
    /** Fiches traitées dans la dernière heure : de quoi estimer la fin. */
    lastHour: number
    lastAt: string | null
  }
  parts: { expected: number; lastAt: string | null }
  byLang: Record<
    string,
    { rows: number; partsOk: number; worksOk: number; failed: number; lastAt: string | null }
  >
  errors: { kind: string; sourceId: string; status: number | null; error: string; at: string }[]
}

export interface Language {
  code: string
  label: string
  flag: string
}

export interface MediaInfo {
  key: string
  label: string
  partLabel: string
  available: boolean
  reason: string
}

export interface Meta {
  media: MediaInfo[]
  defaultMedia: string
  languages: Language[]
  sorts: string[]
  statuses: string[]
}

export interface Detail {
  id: number
  title: string | null
  popularity: number
  adult: boolean
  exportedOn: string
  firstSeenAt: string
  lastSeenAt: string
  fetch: FetchState
  payload: {
    fetchedAt: string
    httpStatus: number
    name: string | null
    firstAirDate: string | null
    tmdbStatus: string | null
    originalLanguage: string | null
    originCountry: string[]
    seasonsDeclared: number
    translations: string[]
  } | null
  parts: { id: string; langs: Record<string, { status: number; fetchedAt: string }> }[]
}

export interface Account {
  username: string
  displayName: string | null
}

// --- Navigation dans le catalogue collecté ---------------------------------

export interface Card {
  id: number
  name: string | null
  originalName: string | null
  overview: string | null
  posterPath: string | null
  backdropPath: string | null
  status: string | null
  originalLanguage: string | null
  firstAirDate: string | null
  lastAirDate: string | null
  /** Année de sortie, déjà extraite : la carte n'a pas à parser de date. */
  year: number | null
  seasons: number | null
  episodes: number | null
  voteAverage: number | null
  voteCount: number | null
  genres: string[]
  originCountry: string[]
  popularity: number | null
  fetchedAt: string
  expectedParts: number
  coverage: Record<string, { ok: number; failed: number }>
  selected: { lang: string; ok: number; failed: number; ratio: number | null }
}

/** L'état de la projection d'affichage — vide, en retard, ou à jour. */
export interface Projection {
  projected: number
  /** Ce que `fetch_state` dit avoir réussi — pas ce qui est stocké. */
  collected: number
  /** Ce que la projection retiendrait si on la recalculait maintenant. */
  projectable: number
  /** Ce qu'un rafraîchissement ajouterait. C'est ce chiffre qu'affiche le
   *  bandeau : `collected - projected` mêlait les incohérences amont. */
  pending: number
  stale: boolean
  lastAt: string | null
}

export interface CardsResponse {
  items: Card[]
  total: number
  page: number
  pageSize: number
  lang: string
  projection: Projection
}

export interface SeasonSummary {
  seasonNumber: number | null
  name: string | null
  overview: string | null
  airDate: string | null
  episodeCount: number | null
  posterPath: string | null
  collected: Record<string, { status: number; fetchedAt: string }>
  hasSelectedLang: boolean
}

export interface CastMember {
  id: number | null
  name: string | null
  character: string | null
  profilePath: string | null
  episodeCount: number | null
}

export interface WatchProvider {
  id: number | null
  name: string | null
  logoPath: string | null
}

/** Où regarder la série, dans le pays de la langue choisie. TMDB indexe cette
 *  donnée par pays — une série est sur Netflix en France et sur Shahid en
 *  Arabie saoudite — et la tient de JustWatch, qu'il faut citer. */
export interface Watch {
  country: string | null
  link: string | null
  offers: { kind: string; label: string; providers: WatchProvider[] }[]
  /** Les pays où la série est disponible : distingue « rien chez vous » de
   *  « aucune donnée de disponibilité ». */
  countries: string[]
}

export interface Work {
  id: number
  name: string | null
  originalName: string | null
  tagline: string | null
  overview: string | null
  posterPath: string | null
  backdropPath: string | null
  homepage: string | null
  status: string | null
  type: string | null
  originalLanguage: string | null
  firstAirDate: string | null
  lastAirDate: string | null
  numberOfSeasons: number | null
  numberOfEpisodes: number | null
  voteAverage: number | null
  voteCount: number | null
  genres: string[]
  networks: { name: string | null; logoPath: string | null }[]
  createdBy: string[]
  originCountry: string[]
  externalIds: Record<string, string | null>
  translations: string[]
  gallery: { backdrops: string[]; posters: string[] }
  cast: CastMember[]
  /** Ce que la langue choisie a réellement apporté : la fiche n'est
   *  téléchargée qu'en `fr-FR`, seules ses traductions varient. */
  translated: { lang: string; name: boolean; overview: boolean }
  watch: Watch
  seasons: SeasonSummary[]
  raw: { fetchedAt: string; httpStatus: number }
  catalog: { popularity: number; adult: boolean; exportedOn: string } | null
}

export interface Episode {
  episodeNumber: number | null
  name: string | null
  overview: string | null
  airDate: string | null
  runtime: number | null
  stillPath: string | null
  voteAverage: number | null
}

export interface SeasonDetail {
  lang: string
  fetchedAt: string
  name: string | null
  overview: string | null
  airDate: string | null
  posterPath: string | null
  episodes: Episode[]
}
