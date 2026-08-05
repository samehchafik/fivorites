import { Card, Group, Progress, Stack, Text, Tooltip, UnstyledButton } from '@mantine/core'

import { formatDate, formatNumber, formatPercent } from '../display'
import type { Language, Summary } from '../types'

/**
 * La comparaison des langues entre elles, et le second chemin vers le
 * sélecteur : une langue se choisit ici d'un clic.
 *
 * C'est la vue qui répond à la question de fond du projet — « le catalogue
 * arabe et le catalogue turc sont-ils aussi bien servis que le français ? » —
 * en mettant les cinq barres côte à côte plutôt qu'en obligeant à changer de
 * langue quatre fois pour comparer.
 */
export function LanguageCoverage({
  languages,
  summary,
  selected,
  onSelect,
}: {
  languages: Language[]
  summary: Summary | undefined
  selected: string
  onSelect: (code: string) => void
}) {
  const expected = summary?.parts.expected ?? 0

  return (
    <Card withBorder radius="md" padding="md">
      <Stack gap="sm">
        <Group justify="space-between" align="baseline">
          <Text size="sm" fw={600}>
            Couverture par langue
          </Text>
          <Text size="xs" c="dimmed">
            {expected
              ? `sur ${formatNumber(expected)} partie(s) énumérée(s)`
              : "aucune partie énumérée pour l'instant"}
          </Text>
        </Group>

        <Stack gap={8}>
          {languages.map((language) => {
            const stats = summary?.byLang[language.code]
            const ratio = expected ? (stats?.partsOk ?? 0) / expected : null
            const active = language.code === selected

            return (
              <UnstyledButton
                key={language.code}
                onClick={() => onSelect(language.code)}
                aria-pressed={active}
                aria-label={`Afficher le tableau en ${language.label}`}
              >
                <Group gap="sm" wrap="nowrap">
                  <Text size="sm" w={150} fw={active ? 700 : 400} truncate>
                    {language.flag} {language.label}
                  </Text>
                  <Tooltip
                    label={
                      stats
                        ? `${formatNumber(stats.partsOk)} collectée(s) · ${formatNumber(stats.failed)} en échec · dernier passage ${formatDate(stats.lastAt)}`
                        : 'rien de collecté dans cette langue'
                    }
                  >
                    <Progress
                      value={(ratio ?? 0) * 100}
                      color={active ? 'indigo' : 'gray'}
                      size="lg"
                      radius="xl"
                      style={{ flex: 1 }}
                    />
                  </Tooltip>
                  <Text size="sm" w={110} ta="right" c={stats ? undefined : 'dimmed'}>
                    {stats ? formatNumber(stats.partsOk) : '—'}{' '}
                    <Text span size="xs" c="dimmed">
                      {formatPercent(ratio)}
                    </Text>
                  </Text>
                </Group>
              </UnstyledButton>
            )
          })}
        </Stack>
      </Stack>
    </Card>
  )
}
