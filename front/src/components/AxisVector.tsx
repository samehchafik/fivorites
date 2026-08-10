import { Badge, Group, Tooltip } from '@mantine/core'

/**
 * L'ordre, le libellé français et la teinte des dimensions connues.
 *
 * En tête, les six de l'empreinte culturelle (barème `empreinte-v1`), qui est
 * le référentiel courant. À la suite, les six axes de goût des barèmes v1 et
 * v2 : leurs notes restent en base et l'atelier permet de les relire, donc
 * elles gardent leur libellé. Une dimension inconnue s'affiche quand même,
 * avec son nom brut — l'ordre n'est qu'un confort de lecture, jamais une
 * liste fermée.
 */
const KNOWN_AXES = [
  { key: 'joie', label: 'Joie', color: 'var(--mantine-color-yellow-5)' },
  { key: 'reve', label: 'Rêve', color: 'var(--mantine-color-violet-5)' },
  { key: 'tristesse', label: 'Tristesse', color: 'var(--mantine-color-blue-5)' },
  // La peur veut du noir, et la teinte `dark` de Mantine est un gris moyen —
  // invisible sur la piste, qui est grise elle aussi. `--mantine-color-text`
  // suit le thème : quasi noire en clair, quasi blanche en sombre. C'est le
  // noir demandé, sans disparaître quand l'admin bascule en mode sombre.
  { key: 'peur', label: 'Peur', color: 'var(--mantine-color-text)' },
  { key: 'reflexion', label: 'Réflexion', color: 'var(--mantine-color-teal-5)' },
  { key: 'action', label: 'Action', color: 'var(--mantine-color-red-5)' },

  { key: 'luminosite', label: 'Luminosité', color: 'var(--mantine-color-indigo-5)' },
  { key: 'intensite', label: 'Intensité', color: 'var(--mantine-color-indigo-5)' },
  { key: 'humour', label: 'Humour', color: 'var(--mantine-color-indigo-5)' },
  { key: 'exigence', label: 'Exigence', color: 'var(--mantine-color-indigo-5)' },
  { key: 'etrangete', label: 'Étrangeté', color: 'var(--mantine-color-indigo-5)' },
  { key: 'sensoriel', label: 'Sensoriel', color: 'var(--mantine-color-indigo-5)' },
]

const DEFAULT_COLOR = 'var(--mantine-color-indigo-5)'

type Axe = { key: string; label: string; color: string }

function orderedAxes(scores: Record<string, number>): Axe[] {
  const known = KNOWN_AXES.filter((axe) => axe.key in scores)
  const rest = Object.keys(scores)
    .filter((key) => !KNOWN_AXES.some((axe) => axe.key === key))
    .sort()
    .map((key) => ({ key, label: key, color: DEFAULT_COLOR }))
  return [...known, ...rest]
}

/**
 * Le vecteur de goût, tel qu'affiché quand il existe : une barre verticale
 * par axe, hauteur proportionnelle à la note (1 à 10). Rien ne s'affiche pour
 * une série jamais jugée — ni barres vides, ni tirets : le silence dit « pas
 * encore notée » mieux qu'un rang de zéros, qui n'existe pas dans le barème.
 *
 * Une teinte par dimension, mais seulement pour l'empreinte culturelle. Les
 * axes de goût s'affichaient d'une seule couleur, et pour une bonne raison :
 * ils ne partagent pas d'échelle de qualité — humour élevé n'est ni mieux ni
 * moins bien qu'humour faible — donc une couleur par axe aurait suggéré un
 * classement inexistant. L'argument tombe avec des émotions nommées : Joie et
 * Peur ne se rangent pas non plus l'une devant l'autre, mais elles ont chacune
 * une couleur que tout le monde leur donne déjà, et l'empreinte devient
 * reconnaissable d'un coup d'œil. Les barèmes v1 et v2 gardent donc leur
 * teinte unique.
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
      {orderedAxes(scores).map(({ key, label, color }) => {
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
                  background: color,
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
