// Les filtres de l'onglet Recherche — un groupe de pastilles par dimension.
//
// Ce composant ne connaît AUCUNE dimension : il affiche les groupes, les
// libellés et les valeurs que l'API lui répond. C'est ce qui lui permet de
// servir les genres (les trois univers), les plateformes (séries et films
// seulement — un livre ne se regarde pas sur Netflix) et ce qui viendra, sans
// une ligne de plus. Une liste en dur afficherait des cases que le catalogue
// ne remplit pas.

import { UnstyledButton } from '@mantine/core'

import { useTextes } from './textes'
import type { CleTexte } from '../../i18n/textes'
import type { GroupeFiltre } from './types'

// Le libellé d'une dimension se traduit ici, par son CODE : le serveur en
// rend un en français (« Plateformes »), utile en repli, mais qui n'a rien à
// faire dans une page arabe.
const LIBELLES: Record<string, CleTexte> = {
  genres: 'filtres.genres',
  plateformes: 'filtres.plateformes',
}

// Ce qu'on montre d'un groupe sans le déplier. TMDB a une vingtaine de
// genres et JustWatch une centaine de plateformes : au-delà, la barre
// mangerait le panneau.
const VISIBLES = 8

export function BarreFiltres({
  groupes,
  choisis,
  deplies,
  onBasculer,
  onDeplier,
  onEffacer,
}: {
  groupes: GroupeFiltre[]
  /** Les valeurs cochées, par dimension. */
  choisis: Record<string, string[]>
  /** Les dimensions dépliées. */
  deplies: string[]
  onBasculer: (champ: string, valeur: string) => void
  onDeplier: (champ: string) => void
  onEffacer: () => void
}) {
  const t = useTextes()
  const utiles = groupes.filter((groupe) => groupe.valeurs.length > 0)
  if (utiles.length === 0) return null
  const nombreChoisis = Object.values(choisis).reduce((somme, v) => somme + v.length, 0)

  return (
    <div className="fivo-filtres-barre">
      {utiles.map((groupe) => {
        const cochees = choisis[groupe.champ] ?? []
        const deplie = deplies.includes(groupe.champ)
        // Les valeurs cochées restent visibles même replié : décocher ne doit
        // pas demander de déplier d'abord.
        const montrees = deplie
          ? groupe.valeurs
          : groupe.valeurs.filter((f, rang) => rang < VISIBLES || cochees.includes(f.valeur))
        const restantes = groupe.valeurs.length - montrees.length
        const libelle = LIBELLES[groupe.champ] ? t.dit(LIBELLES[groupe.champ]) : groupe.libelle

        return (
          <div
            key={groupe.champ}
            className="fivo-filtres"
            role="group"
            aria-label={t.dit('filtres.filtrer_par', { dimension: libelle.toLowerCase() })}
          >
            <span className="fivo-filtres-titre">{libelle}</span>
            {montrees.map((facette) => {
              const actif = cochees.includes(facette.valeur)
              return (
                <UnstyledButton
                  key={facette.valeur}
                  className={`fivo-filtre${actif ? ' actif' : ''}`}
                  aria-pressed={actif}
                  onClick={() => onBasculer(groupe.champ, facette.valeur)}
                  title={t.compte(facette.nombre, 'filtres.oeuvre_une', 'filtres.oeuvres')}
                >
                  {facette.valeur}
                </UnstyledButton>
              )
            })}
            {restantes > 0 && (
              <UnstyledButton
                className="fivo-filtre fivo-filtre-plus"
                onClick={() => onDeplier(groupe.champ)}
              >
                + {restantes}
              </UnstyledButton>
            )}
          </div>
        )
      })}
      {nombreChoisis > 0 && (
        <UnstyledButton className="fivo-filtre fivo-filtre-effacer" onClick={onEffacer}>
          ✕ {t.dit('filtres.effacer')}
        </UnstyledButton>
      )}
    </div>
  )
}
