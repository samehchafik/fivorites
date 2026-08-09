import { Badge, Group, Tooltip } from '@mantine/core'

/**
 * L'ordre et le libellé français des six axes du barème v1
 * (doc/v2-notation-axes.md). Un axe inconnu — un futur barème qui en ajoute
 * un septième — s'affiche quand même, avec son nom brut : l'ordre n'est ici
 * qu'un confort de lecture, jamais une liste fermée.
 */
const KNOWN_AXES = [
  { key: 'luminosite', label: 'Luminosité' },
  { key: 'intensite', label: 'Intensité' },
  { key: 'humour', label: 'Humour' },
  { key: 'exigence', label: 'Exigence' },
  { key: 'etrangete', label: 'Étrangeté' },
  { key: 'sensoriel', label: 'Sensoriel' },
]

function orderedAxes(scores: Record<string, number>): { key: string; label: string }[] {
  const known = KNOWN_AXES.filter((axe) => axe.key in scores)
  const rest = Object.keys(scores)
    .filter((key) => !KNOWN_AXES.some((axe) => axe.key === key))
    .sort()
    .map((key) => ({ key, label: key }))
  return [...known, ...rest]
}

/**
 * Le vecteur de goût, tel qu'affiché quand il existe : une barre verticale
 * par axe, hauteur proportionnelle à la note (1 à 10). Rien ne s'affiche pour
 * une série jamais jugée — ni barres vides, ni tirets : le silence dit « pas
 * encore notée » mieux qu'un rang de zéros, qui n'existe pas dans le barème.
 *
 * Volontairement une seule teinte : les six axes ne partagent pas d'échelle
 * de qualité — humour élevé n'est ni mieux ni moins bien qu'humour faible —
 * une couleur par axe suggérerait un classement qui n'existe pas. Seule la
 * hauteur porte l'information.
 */
export function AxisVector({
  scores,
  internal,
  size = 'sm',
}: {
  scores: Record<string, number> | null | undefined
  /** La prédiction de la régression, quand elle existe. Elle ne s'affiche pas
   *  en barres — deux séries de barres côte à côte se comparent mal à cette
   *  taille — mais en un seul écart moyen, la mesure qui dit si le modèle
   *  interne a rattrapé le juge sur cette œuvre. */
  internal?: Record<string, number> | null
  size?: 'sm' | 'md'
}) {
  if (!scores || Object.keys(scores).length === 0) return null

  const ecarts = internal
    ? orderedAxes(scores)
        .filter(({ key }) => typeof internal[key] === 'number')
        .map(({ key, label }) => ({ label, gap: Math.abs(scores[key] - internal[key]) }))
    : []
  const moyen = ecarts.length
    ? ecarts.reduce((somme, e) => somme + e.gap, 0) / ecarts.length
    : null

  const height = size === 'sm' ? 20 : 36
  const width = size === 'sm' ? 5 : 9

  return (
    <Group gap={size === 'sm' ? 3 : 5} align="flex-end" wrap="nowrap">
      {orderedAxes(scores).map(({ key, label }) => {
        const value = scores[key]
        return (
          <Tooltip key={key} label={`${label} : ${value}/10`} withinPortal>
            <div
              style={{
                width,
                height,
                borderRadius: 2,
                background: 'var(--mantine-color-default-border)',
                display: 'flex',
                alignItems: 'flex-end',
                overflow: 'hidden',
                flexShrink: 0,
              }}
            >
              <div
                style={{
                  width: '100%',
                  height: `${(value / 10) * 100}%`,
                  background: 'var(--mantine-color-indigo-5)',
                  borderRadius: 2,
                }}
              />
            </div>
          </Tooltip>
        )
      })}
      {moyen !== null && (
        <Tooltip
          withinPortal
          multiline
          w={220}
          label={
            'Écart entre le juge et la régression interne, axe par axe : ' +
            ecarts.map((e) => `${e.label} ${e.gap.toFixed(1)}`).join(', ') +
            '. Au niveau du bruit (≤ 1), le modèle interne a rattrapé le juge.'
          }
        >
          <Badge
            size={size === 'sm' ? 'xs' : 'sm'}
            variant="light"
            color={moyen <= 1 ? 'teal' : moyen <= 2 ? 'yellow' : 'red'}
            ml={4}
          >
            Δ {moyen.toFixed(1)}
          </Badge>
        </Tooltip>
      )}
    </Group>
  )
}
