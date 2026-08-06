import { Card, Group, Progress, SimpleGrid, Skeleton, Stack, Text, Tooltip } from '@mantine/core'

import { formatDate, formatEta, formatNumber, formatPercent } from '../display'
import type { Summary } from '../types'

/** Les quatre chiffres qui disent où en est la collecte. Le quatrième dépend de
 *  la langue choisie — c'est celui qu'on vient regarder. */
export function SummaryCards({
  summary,
  lang,
  langLabel,
}: {
  summary: Summary | undefined
  lang: string
  langLabel: string
}) {
  if (!summary) {
    return (
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3, xl: 5 }}>
        {[0, 1, 2, 3, 4].map((index) => (
          <Skeleton key={index} h={116} radius="md" />
        ))}
      </SimpleGrid>
    )
  }

  const perLang = summary.byLang[lang]
  const catalogue = summary.catalog.total
  const seenRatio = catalogue ? summary.works.seen / catalogue : null
  // Une couverture en séries, pas en saisons : « combien d'œuvres ai-je dans
  // cette langue », rapporté aux œuvres effectivement collectées. Une
  // proportion de saisons ne se compare à rien de ce qui est affiché autour.
  const langRatio = summary.works.ok ? (perLang?.worksOk ?? 0) / summary.works.ok : null

  const eta = formatEta(summary.works.remaining, summary.works.lastHour)

  return (
    <SimpleGrid cols={{ base: 1, sm: 2, lg: 3, xl: 5 }}>
      <Metric
        title="Catalogue"
        value={formatNumber(catalogue)}
        hint={`export du ${summary.catalog.exportedOn ?? '—'}`}
        detail={`dont ${formatNumber(summary.catalog.popular)} de popularité ≥ 1`}
      />

      <Metric
        title="Fiches regardées"
        value={formatNumber(summary.works.seen)}
        hint={formatPercent(seenRatio)}
        detail={`${formatNumber(summary.works.ok)} abouties · ${formatNumber(summary.works.failed)} en échec`}
        progress={seenRatio}
        color={summary.works.failed > 0 ? 'orange' : 'indigo'}
      />

      {/* La question qu'on pose le plus souvent devant ce tableau : combien
          reste-t-il, et pour combien de temps. Le débit est celui de la
          dernière heure — le seul qui décrive la collecte en cours plutôt
          qu'une moyenne depuis le début. */}
      <Metric
        title="Reste à collecter"
        value={formatNumber(summary.works.remaining)}
        hint={eta ?? undefined}
        detail={
          summary.works.lastHour > 0
            ? `${formatNumber(summary.works.lastHour)} fiche(s) sur la dernière heure`
            : 'aucune collecte depuis une heure'
        }
        progress={catalogue ? 1 - summary.works.remaining / catalogue : null}
        color="grape"
      />

      <Metric
        title="Parties énumérées"
        value={formatNumber(summary.parts.expected)}
        hint="toutes langues"
        detail={`dernier passage ${formatDate(summary.parts.lastAt)}`}
      />

      <Metric
        title={`Couverture ${langLabel}`}
        value={formatNumber(perLang?.worksOk ?? 0)}
        hint={formatPercent(langRatio)}
        detail={
          perLang
            ? `série(s) sur ${formatNumber(summary.works.ok)} collectée(s) · ${formatNumber(perLang.failed)} échec(s)`
            : 'aucune ligne dans cette langue'
        }
        progress={langRatio}
        color="teal"
      />
    </SimpleGrid>
  )
}

function Metric({
  title,
  value,
  hint,
  detail,
  progress,
  color = 'indigo',
}: {
  title: string
  value: string
  hint?: string
  detail?: string
  progress?: number | null
  color?: string
}) {
  return (
    <Card withBorder padding="md" radius="md">
      <Stack gap={6}>
        <Text size="xs" tt="uppercase" c="dimmed" fw={600}>
          {title}
        </Text>
        <Group align="baseline" gap="xs">
          <Text fz={28} fw={700} lh={1}>
            {value}
          </Text>
          {hint && (
            <Text size="sm" c="dimmed">
              {hint}
            </Text>
          )}
        </Group>
        {progress !== undefined && progress !== null && (
          <Tooltip label={formatPercent(progress)}>
            <Progress value={progress * 100} color={color} size="sm" radius="xl" />
          </Tooltip>
        )}
        {detail && (
          <Text size="xs" c="dimmed">
            {detail}
          </Text>
        )}
      </Stack>
    </Card>
  )
}
