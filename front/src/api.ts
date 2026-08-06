import type {
  Account,
  CardsResponse,
  Detail,
  ItemsResponse,
  Meta,
  Projection,
  SeasonDetail,
  Summary,
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

type QueryValue = string | number | boolean | null | undefined

function query(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
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

  work: (id: number, lang: string) => request<Work>(`/api/catalog/works/${id}?${query({ lang })}`),

  season: (id: number, seasonNumber: number, lang: string) =>
    request<SeasonDetail>(
      `/api/catalog/works/${id}/seasons/${seasonNumber}?${query({ lang })}`,
    ),

  refreshCatalog: () => request<Projection>('/api/catalog/refresh', { method: 'POST' }),
}

export interface CardsParams extends Record<string, QueryValue> {
  lang: string
  search?: string
  minPopularity?: number | null
  sort: string
  order: 'asc' | 'desc'
  /** Critère de départage, facultatif. Vide = un seul critère. */
  sort2?: string
  order2?: 'asc' | 'desc'
  /** Ne garder que les séries ayant une affiche. */
  withPoster?: boolean
  page: number
  pageSize: number
}

/** Les visuels sont servis par TMDB, pas par nous : on ne recopie pas une
 *  bibliothèque d'affiches pour l'afficher dans une page d'administration. */
const TMDB_IMAGES = 'https://image.tmdb.org/t/p'

export function tmdbImage(path: string | null | undefined, size: string): string | null {
  return path ? `${TMDB_IMAGES}/${size}${path}` : null
}
