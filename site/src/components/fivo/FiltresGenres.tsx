// Les filtres de l'onglet Recherche — des pastilles à cocher.
//
// La dimension n'est PAS la même d'un univers à l'autre, et ce composant n'en
// sait rien : il affiche le libellé et les valeurs que l'API lui répond. Les
// séries et les films se filtrent par genre (TMDB) ; les livres n'ont aucun
// genre en base — l'enrichissement Wikidata ne rend que des auteurs, des
// langues, des pays et une année — et se filtrent donc par langue. Un
// composant qui aurait sa liste de genres en dur afficherait des cases qui ne
// rendent rien.

import { UnstyledButton } from '@mantine/core'

import type { Facette } from './types'

// Ce qu'on montre sans déplier. TMDB a une vingtaine de genres, mais les
// livres ont des dizaines de langues : au-delà, la barre mangerait le panneau.
const VISIBLES = 8

export function FiltresGenres({
  libelle,
  valeurs,
  choisis,
  deplie,
  onBasculer,
  onDeplier,
  onEffacer,
}: {
  libelle: string
  valeurs: Facette[]
  choisis: string[]
  deplie: boolean
  onBasculer: (valeur: string) => void
  onDeplier: () => void
  onEffacer: () => void
}) {
  if (valeurs.length === 0) return null

  // Les valeurs cochées restent visibles même replié : décocher ne doit pas
  // demander de déplier d'abord.
  const montrees = deplie
    ? valeurs
    : valeurs.filter((f, rang) => rang < VISIBLES || choisis.includes(f.valeur))
  const restantes = valeurs.length - montrees.length

  return (
    <div className="fivo-filtres" role="group" aria-label={`Filtrer par ${libelle.toLowerCase()}`}>
      <span className="fivo-filtres-titre">{libelle}</span>
      {montrees.map((facette) => {
        const actif = choisis.includes(facette.valeur)
        return (
          <UnstyledButton
            key={facette.valeur}
            className={`fivo-filtre${actif ? ' actif' : ''}`}
            aria-pressed={actif}
            onClick={() => onBasculer(facette.valeur)}
            title={`${facette.nombre.toLocaleString('fr-FR')} œuvre${facette.nombre > 1 ? 's' : ''}`}
          >
            {facette.valeur}
          </UnstyledButton>
        )
      })}
      {restantes > 0 && (
        <UnstyledButton className="fivo-filtre fivo-filtre-plus" onClick={onDeplier}>
          + {restantes}
        </UnstyledButton>
      )}
      {choisis.length > 0 && (
        <UnstyledButton className="fivo-filtre fivo-filtre-effacer" onClick={onEffacer}>
          ✕ tout
        </UnstyledButton>
      )}
    </div>
  )
}
