// Les formes que l'API publique rend — le miroir TypeScript de
// webapp/src/fiv_webapp (cartes.py, signaux.py, suggestions.py).

export type UniversSlug = 'series' | 'films' | 'livres'

export type Statut = 'aime' | 'aime_pas' | 'a_voir'

export interface Carte {
  /** La clé de la vignette : id TMDB pour séries et films, pivot pour les livres. */
  id: number
  /** Le pivot `sourcing.oeuvre.id` — l'identité que le classement manipule.
   *  Null si l'œuvre n'a pas encore de pivot : les boutons sont alors inertes. */
  oeuvreId: number | null
  univers: UniversSlug
  titre: string | null
  titreOriginal: string | null
  annee: number | null
  affiche: string | null
  synopsis: string | null
  genres: string[]
  note: number | null
}

export interface Signal {
  /** La clé de vignette — ce que la fiche demande. `null` quand la
   *  projection n'a pas (encore) de ligne pour ce pivot : l'œuvre se liste,
   *  elle ne s'ouvre pas. */
  id: number | null
  oeuvreId: number
  univers: UniversSlug
  statut: Statut
  titre: string | null
  affiche: string | null
  annee: number | null
}

/** Une valeur de filtre et son nombre d'œuvres. */
export interface Facette {
  valeur: string
  nombre: number
}

/** Une dimension de filtre et ses valeurs. Le front n'en connaît aucune
 *  d'avance : il affiche les groupes qu'on lui répond, libellés compris — les
 *  séries et les films portent genres ET plateformes, un livre ne se regarde
 *  pas sur Netflix. */
export interface GroupeFiltre {
  champ: string
  libelle: string
  valeurs: Facette[]
}

export interface Filtres {
  langue: string
  groupes: GroupeFiltre[]
}

/** Une plateforme de diffusion, telle que JustWatch la rend via TMDB. */
export interface Plateforme {
  nom: string
  logo: string | null
}

/** Une façon de regarder l'œuvre, et qui la propose. */
export interface Offre {
  genre: string
  libelle: string
  plateformes: Plateforme[]
}

/** Une bande-annonce ou un extrait. `url` et `vignette` sont fabriquées par
 *  le serveur : lui seul sait quels sites il sait adresser. */
export interface Video {
  site: string
  cle: string
  type: string
  nom: string | null
  langue: string | null
  officielle: boolean
  saison: number | null
  url: string | null
  /** L'adresse du lecteur intégrable — ce qu'une `iframe` accepte. C'est
   *  elle qui permet de regarder sans quitter la fiche. */
  integration: string | null
  vignette: string | null
}

export interface Personne {
  nom: string
  /** Son identité dans le graphe — `tmdb:1234`, `wd:Q535`. Nulle quand la
   *  source ne l'a pas donnée : la personne s'affiche alors sans être
   *  cliquable, plutôt que d'ouvrir la filmographie d'un homonyme. */
  cle: string | null
  /** Le personnage joué, « Création », « Réalisation » ou « Auteur ». */
  role: string | null
  photo: string | null
  episodes: number | null
}

export interface Episode {
  numero: number
  titre: string | null
  synopsis: string | null
  diffusion: string | null
  duree: number | null
  image: string | null
  note: number | null
}

export interface Saison {
  numero: number
  nom: string | null
  annee: number | null
  episodes: number | null
  affiche: string | null
  synopsis: string | null
}

/** L'œuvre en grand — ce que la modale affiche. Un livre a les mêmes clés,
 *  ses saisons et sa distribution étant simplement vides. */
export interface Fiche {
  id: number
  oeuvreId: number | null
  univers: UniversSlug
  titre: string | null
  titreOriginal: string | null
  accroche: string | null
  annee: number | null
  synopsis: string | null
  /** La langue du synopsis servi. Elle peut différer de celle demandée : la
   *  cascade du serveur retombe sur l'anglais quand rien n'existe dans la
   *  langue (le cas de deux séries sur trois), et la fiche le dit. */
  synopsisLangue: string | null
  affiche: string | null
  fond: string | null
  genres: string[]
  note: number | null
  votes: number | null
  statut: string | null
  pays: string[]
  langue: string | null
  saisonsTotal: number | null
  episodesTotal: number | null
  distribution: Personne[]
  realisation: Personne[]
  saisons: Saison[]
  /** Où regarder, dans le pays de la langue demandée. */
  offres: Offre[]
  /** Le lien JustWatch du pays — TMDB impose de citer la source. */
  lienOffres: string | null
  /** Les pays où l'œuvre est disponible : de quoi distinguer « rien chez
   *  vous » de « aucune donnée ». */
  paysOffres: string[]
  videos: Video[]
}

/** Une œuvre de la filmographie de quelqu'un. */
export interface OeuvreDePersonne {
  id: number
  oeuvreId: number
  univers: UniversSlug
  titre: string | null
  annee: number | null
  affiche: string | null
  role: string | null
}

/** Quelqu'un, sa photo, et une page de ses œuvres. `source` vaut `graphe`
 *  (exact, tous univers) ou `index` (par le nom, un seul univers, homonymes
 *  confondus) — le panneau le dit, parce que ça change ce qu'on regarde. */
export interface FichePersonne {
  cle: string
  nom: string | null
  photo: string | null
  /** L'indice 0-10 : ce que la personne pèse dans le catalogue — DiCaprio
   *  10, un second rôle établi 5, un figurant 0. Nul en repli par l'index. */
  indice: number | null
  oeuvres: OeuvreDePersonne[]
  total: number
  page: number
  parPage: number
  source: 'graphe' | 'index'
}

/** Une plateforme et la façon d'y accéder : incluse dans l'abonnement, via
 *  une chaîne payante du hub (« HBO Max via Prime Video »), ou seulement à
 *  la location. `location` dit si la boutique loue AUSSI. */
export interface AccesPlateforme {
  nom: string
  acces: 'incluse' | 'chaine' | 'location'
  via: string | null
  location: boolean
}

export interface Suggestion {
  /** La clé de vignette — id TMDB, ou pivot pour un livre. Ouvre la fiche. */
  id: number
  oeuvreId: number
  titre: string | null
  annee: number | null
  affiche: string | null
  univers: UniversSlug
  /** D'où elle vient : `voisins` la communauté, `proche` l'empreinte d'une
   *  œuvre, `profil` les axes du visiteur, `gens` les acteurs et
   *  réalisateurs du graphe, `affinite` les genres et les gens de l'index.
   *  Les sources n'ont pas la même force, et l'explication les distingue. */
  source: 'voisins' | 'proche' | 'profil' | 'gens' | 'genre' | 'affinite'
  voisins: number | null
  force: number | null
  distance: number | null
  /** Combien de vos œuvres classées cette suggestion avoisine : au-delà de
   *  une, c'est l'œuvre vers laquelle votre profil converge. */
  convergences: number | null
  /** Combien de MEMBRES ont l'œuvre dans leurs fives — une information de
   *  carte (« 13 777 membres »), jamais un score : la popularité brute ne
   *  classe pas, elle rassure. */
  cites: number | null
  /** Les gens partagés avec vos œuvres — combien, et qui : « Avec Melissa
   *  Fumero » vaut mieux qu'un score. */
  gens: number | null
  avec: string[]
  /** Les genres de l'œuvre — la matière des puces « Moins de : ». */
  genres: string[]
  /** Où et COMMENT l'œuvre se regarde, dans le pays de la langue — la
   *  matière des puces « Sur : » et de l'indication d'accès. Vide pour un
   *  livre. */
  plateformes: AccesPlateforme[]
  /** Les genres partagés avec les coups de cœur — l'explication de l'étage
   *  des affinités. Vide quand la correspondance s'est faite sur un nom. */
  communs: string[]
  /** Le contenu ET la communauté désignent-ils cette œuvre ? C'est la
   *  suggestion la plus solide que le moteur sache produire, et elle se dit. */
  corrobore: boolean
}

/** Les trois univers, dans l'ordre des onglets. Leurs libellés ne sont plus
 *  ici : « Séries » se dit dans quatre langues, et cela vit dans
 *  `src/i18n/textes` avec le reste (clés `nav.series` au pluriel des
 *  onglets, `type.series` au singulier de la carte — les confondre donnerait
 *  « 1954 · Livres »). */
export const UNIVERS: readonly UniversSlug[] = ['series', 'films', 'livres'] as const

/** Le compte du visiteur, tel que `GET /compte` le rend. */
export interface Compte {
  id: string
  pseudo: string
  email: string
  genre: string | null
  verifie: boolean
}

/** Un five : une œuvre à un rang (1-5) d'un univers. */
export interface Five {
  rang: number
  oeuvreId: number
  /** La clé de vignette — nulle si la projection ne connaît pas l'œuvre. */
  id: number | null
  titre: string | null
  affiche: string | null
  annee: number | null
}
