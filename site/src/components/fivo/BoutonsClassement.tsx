// Les trois gestes de la V1, dans son ordre spatial — J'AIME PAS à gauche,
// J'AI VU & AIMÉ au centre (c'était le haut du swipe), JE VEUX VOIR ! à
// droite — avec ses flèches et ses couleurs (--no, --pink, --yes). Recliquer
// sur le statut actif le retire : le seul « annuler » dont on a besoin.

import { UnstyledButton } from '@mantine/core'

import type { Statut } from './types'

const GESTES: Array<{ statut: Statut; label: string; fleche: string }> = [
  { statut: 'aime_pas', label: "J'aime pas", fleche: '←' },
  { statut: 'aime', label: "J'ai vu & aimé", fleche: '↑' },
  { statut: 'a_voir', label: 'Je veux voir !', fleche: '→' },
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
  return (
    <div className="fivo-gestes" role="group" aria-label="Classer cette œuvre">
      {GESTES.map(({ statut, label, fleche }) => {
        const actif = statutActuel === statut
        return (
          <UnstyledButton
            key={statut}
            className={`fivo-geste fivo-geste-${statut}${actif ? ' actif' : ''}`}
            disabled={desactive}
            aria-pressed={actif}
            title={desactive ? 'Œuvre pas encore classable' : label}
            onClick={() => (actif ? onDeclasser() : onClasser(statut))}
          >
            <span className="fivo-geste-fleche" aria-hidden="true">
              {fleche}
            </span>{' '}
            {label}
          </UnstyledButton>
        )
      })}
    </div>
  )
}
