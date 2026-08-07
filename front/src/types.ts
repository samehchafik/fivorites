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
  /** Le vecteur de goût courant, axe → note (1-10) — le dernier verdict du
   *  juge, jamais la contre-note manuelle ni la prédiction interne. `null`
   *  tant que la série n'a jamais été jugée : pas un objet vide, une absence.
   *  Facultatif : une API plus ancienne que le front ne le renvoie pas. */
  axisScores?: Record<string, number> | null
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
   *  téléchargée qu'en `fr-FR`, seules ses traductions varient.
   *
   *  **Facultatif à dessein** : une API plus ancienne que le front ne le
   *  renvoie pas, et le typage oblige alors à traiter l'absence plutôt qu'à
   *  blanchir la page sur un `undefined.name`. */
  translated?: { lang: string; name: boolean; overview: boolean }
  watch: Watch
  seasons: SeasonSummary[]
  raw: { fetchedAt: string; httpStatus: number }
  /** Le vecteur de goût courant, axe → note (1-10). Même règle que sur la
   *  vignette : `null` tant que la série n'a jamais été jugée, et facultatif
   *  parce qu'une API plus ancienne que le front ne le renvoie pas. */
  axisScores?: Record<string, number> | null
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

// ------------------------------------------------------------- entraînement

/** Le barème : la consigne envoyée aux juges, versionnée. Une note sans
 *  version de barème est ininterprétable — la version EST la provenance. */
export interface Rubric {
  version: string
  prompt: string
  axes: string[]
  note: string | null
  created_at: string
}

/** Les onglets de la fiche série — portés par l'URL (`?onglet=training1`)
 *  pour qu'un lien partagé rouvre la fiche au bon endroit. */
export type ModalTab = 'presentation' | 'training1' | 'training2'

/** Le dossier de notation : le texte anglais réellement soumis aux juges. */
export interface Dossier {
  idTmdb: number
  title: string
  text: string
  sha256: string
  chars: number
  /** Faux quand le dossier est trop maigre pour produire des notes fiables. */
  enough: boolean
  sections: {
    overviewChars: number
    seasonOverviews: number
    episodeCount: number
    episodeChars: number
    /** Lignes de la section MEDIA — 0 tant que les visuels ne sont pas légendés. */
    mediaLines: number
    wikipediaChars: number
    keywords: number
  }
}

/** Le bilan du bouton « Légender les visuels » : combien d'images sont passées
 *  devant le modèle de vision, combien étaient déjà figées en base. */
export interface CaptionResult {
  id: number
  captioned: number
  already: number
  total: number
  model: string
}

/** Un essai du journal `notation.training_run` : le prompt en clair, la
 *  fiche brute référencée, et les deux verdicts côte à côte. `claude` reste
 *  null tant que la contre-note (Haiku ou claude.ai recopié) n'est pas là. */
export interface TrainingRun {
  id: number
  rubricVersion: string
  prompt: string
  dossierSha256: string
  openai: { model: string; scores: Record<string, AxisScore> } | null
  claude: { model: string; scores: Record<string, AxisScore> } | null
  /** Le vecteur prédit par la régression, écrit par « Générer » ou par
   *  l'entraînement. C'est lui qui permet à Training 2 de s'afficher sans
   *  qu'on ait rien à recliquer. */
  interne?: Record<
    string,
    { score: number; trainedOn: number; maeFit: number | null; maeCv?: number | null }
  > | null
  createdAt: string
  claudeAt: string | null
  interneAt?: string | null
}

/** La note d'un juge sur un axe. `score` null = « pas assez de matière ». */
export interface AxisScore {
  score: number | null
  confidence: number | null
}

/** Les écarts entre deux jeux de notes — la mesure de toute la boucle. */
export interface Gaps {
  perAxis: Record<string, number | null>
  mean: number | null
  scored: number
}

export interface Phase1Result {
  id: number
  /** L'essai dans le journal `notation.training_run` — à renvoyer avec la
   *  contre-note manuelle pour qu'elle rejoigne la bonne ligne. Facultatif :
   *  une API plus ancienne que le front ne le renvoie pas. */
  runId?: number
  dossier: { sha256: string; chars: number; title: string; sections: Dossier['sections'] }
  openai: { model: string; scores: Record<string, AxisScore> }
  /** Null sans clé Anthropic : le contre-jugement se fait alors à la main,
   *  en collant consigne + dossier dans claude.ai. */
  haiku: { model: string; scores: Record<string, AxisScore> } | null
  gaps: Gaps | null
}

export interface TrainResult {
  rubricVersion: string
  works: number
  axes: {
    axe: string
    trainedOn: number
    maeFit?: number
    /** L'erreur de validation croisée (leave-one-out) — la métrique
     *  honnête : maeFit baisse toujours avec plus de paramètres, maeCv dit
     *  ce que le modèle ferait sur une œuvre qu'il n'a pas vue. C'est elle
     *  qu'il faut regarder lot après lot pour savoir si l'interne a assez
     *  d'œuvres pour cesser de diverger avec le juge. */
    maeCv?: number
    lambda?: number
    skipped?: boolean
  }[]
  /** La ligne du journal notation.training_weights — une par prompt, la plus
   *  récente est la version par défaut de la phase 2. */
  weightsId?: number | null
  trainedAt?: string | null
  /** Combien d'œuvres ont vu leur vecteur interne régénéré dans la foulée —
   *  toutes celles dont le journal porte un verdict OpenAI. */
  generated?: number
}

export interface Phase2Result {
  id: number
  /** L'essai du journal où le vecteur généré a été écrit (colonne `interne`).
   *
   *  **Facultatif à dessein**, comme les deux champs suivants : une API plus
   *  ancienne que le front ne les renvoie pas, et le typage oblige alors à
   *  traiter l'absence plutôt qu'à blanchir la page sur un `undefined.x`. */
  runId?: number
  dossier: { sha256: string; chars: number; title: string }
  /** La version de poids qui a produit la prédiction — la plus récente du journal. */
  weights?: { id: number; trainedAt: string; works: number }
  internal: Record<
    string,
    { score: number; trainedOn: number; maeFit: number | null; maeCv?: number | null }
  >
  llm: {
    scores: Record<string, AxisScore>
    origin: { model: string; fresh: boolean; scoredAt?: string } | null
  }
  /** Le contre-juge, s'il s'est prononcé sur ce barème — affiché à côté
   *  d'OpenAI pour voir si l'interne dérive vers l'une des deux lignées. */
  claude?: {
    scores: Record<string, AxisScore>
    origin: { model: string; scoredAt: string } | null
  }
  gaps: Gaps | null
}

/** Une ligne de l'historique des notes d'une œuvre. */
export interface StoredScore {
  axe: string
  valeur: number | null
  confiance: number | null
  rubric_version: string
  modele: string
  scored_at: string
}
