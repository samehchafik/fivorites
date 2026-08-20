import type {
  Account,
  CaptionResult,
  CardsResponse,
  Detail,
  Dossier,
  GenresResponse,
  ItemsResponse,
  MembreFives,
  MembresResponse,
  Meta,
  Phase1Result,
  Phase2Result,
  Projection,
  RichSources,
  Rubric,
  SeasonDetail,
  StoredScore,
  Summary,
  TrainingRun,
  TrainResult,
  Work,
} from './types'

/** Une réponse d'erreur de l'API, avec son code — le 401 déclenche le retour
 *  à l'écran de connexion, le 409 explique un univers non collecté. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    // Le jeton de session est un cookie `HttpOnly` : rien à porter à la main,
    // rien à stocker côté JavaScript, donc rien à exfiltrer.
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })

  if (response.status === 204) return undefined as T
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined)
    throw new ApiError(response.status, detail ?? `HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

type QueryValue = string | number | boolean | null | undefined | string[]

function query(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    // Un tableau devient un paramètre RÉPÉTÉ (`?genres=A&genres=B`), jamais
    // une chaîne jointe : plusieurs genres de TMDB portent des caractères
    // qu'un découpage par virgule finirait par casser — « Action &
    // Adventure », « Sci-Fi & Fantasy ».
    if (Array.isArray(value)) {
      for (const entry of value) if (entry !== '') search.append(key, entry)
      continue
    }
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value))
  }
  return search.toString()
}

export interface ItemsParams extends Record<string, QueryValue> {
  media: string
  lang: string
  status: string
  search?: string
  minPopularity?: number | null
  sort: string
  order: 'asc' | 'desc'
  page: number
  pageSize: number
}

export const api = {
  me: () => request<Account>('/api/auth/me'),

  login: (username: string, password: string) =>
    request<Account>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),

  meta: () => request<Meta>('/api/meta'),

  summary: (media: string) => request<Summary>(`/api/acquisition/summary?${query({ media })}`),

  items: (params: ItemsParams) => request<ItemsResponse>(`/api/acquisition/items?${query(params)}`),

  detail: (media: string, id: number) =>
    request<Detail>(`/api/acquisition/items/${id}?${query({ media })}`),

  cards: (params: CardsParams) => request<CardsResponse>(`/api/catalog/cards?${query(params)}`),

  /** Les genres présents dans l'univers, avec leur nombre d'œuvres. Vient
   *  d'une agrégation Elasticsearch, donc du contenu réel du catalogue — pas
   *  d'une liste figée qui divergerait le jour où TMDB en ajoute un. */
  genres: (media: string) => request<GenresResponse>(`/api/catalog/genres?${query({ media })}`),

  work: (id: number, lang: string, media: string) =>
    request<Work>(`/api/catalog/works/${id}?${query({ lang, media })}`),

  season: (id: number, seasonNumber: number, lang: string) =>
    request<SeasonDetail>(
      `/api/catalog/works/${id}/seasons/${seasonNumber}?${query({ lang })}`,
    ),

  /** ⚠️ `media` n'est pas facultatif au sens du résultat : sans lui, le film
   *  557 rendait les sources de la série 557, *Camp Lazlo*. */
  rich: (id: number, media: string) =>
    request<RichSources>(`/api/catalog/works/${id}/sources?${query({ media })}`),

  refreshCatalog: () => request<Projection>('/api/catalog/refresh', { method: 'POST' }),

  // -------------------------------------------------------------- membres

  membres: (params: {
    q?: string
    tri: string
    ordre: 'asc' | 'desc'
    avecFives?: boolean
    page: number
    pageSize: number
  }) => request<MembresResponse>(`/api/membres?${query(params)}`),

  /** Les tops d'un membre. Appelé seulement à l'ouverture d'une ligne : les
   *  324 000 positions de la base n'ont rien à faire dans une liste. */
  membreFives: (id: number) => request<MembreFives>(`/api/membres/${id}/fives`),

  // --------------------------------------------------------- entraînement

  /** Toutes les routes d'atelier portent `media`. Un identifiant TMDB seul ne
   *  désigne rien : les deux catalogues se chevauchent, et 550 est un film
   *  comme une série. Sans lui, l'atelier cherchait la fiche d'un film sous le
   *  `kind` des séries et affichait un dossier vide. */
  trainingDossier: (id: number, media: string) =>
    request<Dossier>(`/api/training/works/${id}/dossier?media=${media}`),

  trainingScores: (id: number, media: string) =>
    request<StoredScore[]>(`/api/training/works/${id}/scores?media=${media}`),

  /** Les derniers essais du journal — ce qui rend la page rechargeable. */
  trainingRuns: (id: number, media: string) =>
    request<TrainingRun[]>(`/api/training/works/${id}/runs?media=${media}`),

  /** Légende les visuels (backdrops + stills) via le modèle de vision, une
   *  fois pour toutes : les images déjà légendées ne sont jamais repayées. */
  captionWork: (id: number, media: string) =>
    request<CaptionResult>(`/api/training/works/${id}/captions?media=${media}`, { method: 'POST' }),

  rubrics: () => request<Rubric[]>('/api/training/rubrics'),

  saveRubric: (body: { version: string; prompt: string; axes: string[]; note?: string }) =>
    request<{ version: string }>('/api/training/rubrics', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Phase 1 : une œuvre, deux juges (OpenAI note, Haiku contre-note). */
  phase1: (body: {
    id: number
    media: string
    rubricVersion: string
    prompt: string
    axes: string[]
  }) =>
    request<Phase1Result>('/api/training/phase1', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Contre-note saisie à la main — le verdict de claude.ai, recopié. */
  manualScores: (body: {
    id: number
    media: string
    rubricVersion: string
    prompt: string
    scores: Record<string, { score: number | null; confidence?: number | null }>
    runId?: number | null
  }) =>
    request<{ stored: number; modele: string }>('/api/training/manual', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Réentraîne la régression interne sur toutes les notes du barème. */
  trainWeights: (rubricVersion: string) =>
    request<TrainResult>('/api/training/weights/train', {
      method: 'POST',
      body: JSON.stringify({ rubricVersion }),
    }),

  /** Phase 2 : la prédiction interne face aux notes LLM. */
  phase2: (body: { id: number; media: string; rubricVersion: string; runLlm?: boolean }) =>
    request<Phase2Result>('/api/training/phase2', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}

export interface CardsParams extends Record<string, QueryValue> {
  lang: string
  /** L'univers affiché — `tv` ou `movie`. Décide de la projection lue. */
  media: string
  search?: string
  minPopularity?: number | null
  sort: string
  order: 'asc' | 'desc'
  /** Critère de départage, facultatif. Vide = un seul critère. */
  sort2?: string
  order2?: 'asc' | 'desc'
  /** Ne garder que les séries ayant une affiche. */
  withPoster?: boolean
  /** Ne garder que les séries ayant un synopsis. */
  withOverview?: boolean
  /** Genres retenus, en OU : « comédie ou drame ». Vide = tous. */
  genres?: string[]
  page: number
  pageSize: number
}

/** Les visuels sont servis par TMDB, pas par nous : on ne recopie pas une
 *  bibliothèque d'affiches pour l'afficher dans une page d'administration. */
const TMDB_IMAGES = 'https://image.tmdb.org/t/p'

export function tmdbImage(path: string | null | undefined, size: string): string | null {
  return path ? `${TMDB_IMAGES}/${size}${path}` : null
}
