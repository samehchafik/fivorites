// Les trois gestes de la V1, dans son ordre spatial — J'AIME PAS à gauche,
// J'AI VU & AIMÉ au centre (c'était le haut du swipe), JE VEUX VOIR ! à
// droite — avec ses flèches et ses couleurs (--no, --pink, --yes). Recliquer
// sur le statut actif le retire : le seul « annuler » dont on a besoin.

import { UnstyledButton } from '@mantine/core'

import { useTextes } from './textes'
import type { CleTexte } from '../../i18n/textes'
import type { Statut } from './types'

const GESTES: Array<{ statut: Statut; cle: CleTexte; fleche: string }> = [
  { statut: 'aime_pas', cle: 'geste.aime_pas', fleche: '←' },
  { statut: 'aime', cle: 'geste.aime', fleche: '↑' },
  { statut: 'a_voir', cle: 'geste.a_voir', fleche: '→' },
]

export function BoutonsClassement({
  statutActuel,
  desactive,
  onClasser,
  onDeclasser,
}: {
  statutActuel: Statut | null
  /** Vrai quand l'œuvre n'a pas de pivot : rien à classer, on le dit. */
  desactive: boolean
  onClasser: (statut: Statut) => void
  onDeclasser: () => void
}) {
  const t = useTextes()
  return (
    <div className="fivo-gestes" role="group" aria-label={t.dit('geste.groupe')}>
      {GESTES.map(({ statut, cle, fleche }) => {
        const actif = statutActuel === statut
        const label = t.dit(cle)
        return (
          <UnstyledButton
            key={statut}
            className={`fivo-geste fivo-geste-${statut}${actif ? ' actif' : ''}`}
            disabled={desactive}
            aria-pressed={actif}
            title={desactive ? t.dit('geste.inclassable') : label}
            onClick={() => (actif ? onDeclasser() : onClasser(statut))}
          >
            {/* La flèche ne tourne PAS en arabe : elle désigne un côté du
                plateau (gauche, haut, droite), pas un sens de lecture. */}
            <span className="fivo-geste-fleche" aria-hidden="true">
              {fleche}
            </span>{' '}
            <span className="fivo-geste-mot">{label}</span>
          </UnstyledButton>
        )
      })}
    </div>
  )
}
