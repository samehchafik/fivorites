import { Badge, Card, Group, Image, Progress, Stack, Text, Tooltip } from '@mantine/core'
import { IconStar } from '@tabler/icons-react'

import { tmdbImage } from '../api'
import { POSTER_FALLBACK, formatPercent } from '../display'
import type { Card as CardData, Language } from '../types'

const POSTER_WIDTH = 104

/**
 * Une série, en une vignette : l'affiche à gauche, l'essentiel à droite.
 *
 * L'essentiel, ici, c'est ce qui permet de reconnaître la série et de juger sa
 * collecte d'un coup d'œil — année, nombre de saisons, synopsis coupé, et la
 * couverture dans la langue choisie. Le reste attend le clic.
 */
export function SeriesCard({
  card,
  languages,
  lang,
  onOpen,
}: {
  card: CardData
  languages: Language[]
  lang: string
  onOpen: () => void
}) {
  const poster = tmdbImage(card.posterPath, 'w185')
  const covered = languages.filter((language) => (card.coverage[language.code]?.ok ?? 0) > 0)

  return (
    <Card
      withBorder
      radius="md"
      padding={0}
      onClick={onOpen}
      style={{ cursor: 'pointer', overflow: 'hidden' }}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen()
        }
      }}
    >
      <Group align="stretch" gap={0} wrap="nowrap" h="100%">
        {/* `fallbackSrc` couvre les deux cas : chemin absent du payload, et
            chemin présent mais fichier disparu depuis la collecte. */}
        <Image
          src={poster}
          fallbackSrc={POSTER_FALLBACK}
          w={POSTER_WIDTH}
          h="100%"
          fit="cover"
          alt=""
          loading="lazy"
          style={{ flexShrink: 0 }}
        />

        <Stack gap={6} p="sm" style={{ flex: 1, minWidth: 0 }}>
          <Group gap={6} justify="space-between" wrap="nowrap" align="flex-start">
            <Text fw={600} lineClamp={2} dir="auto" style={{ minWidth: 0 }}>
              {card.name ?? `#${card.id}`}
            </Text>
            {card.voteAverage ? (
              <Group gap={2} wrap="nowrap" c="dimmed">
                <IconStar size={13} />
                <Text size="xs">{card.voteAverage.toFixed(1)}</Text>
              </Group>
            ) : null}
          </Group>

          <Group gap={6} wrap="wrap">
            <Badge size="sm" variant="light">
              {card.year ?? 'année inconnue'}
            </Badge>
            <Badge size="sm" variant="light" color="grape">
              {card.seasons ?? '?'} saison{(card.seasons ?? 0) > 1 ? 's' : ''}
            </Badge>
            {card.episodes ? (
              <Badge size="sm" variant="default">
                {card.episodes} épisodes
              </Badge>
            ) : null}
            {card.genres.slice(0, 2).map((genre) => (
              <Badge key={genre} size="sm" variant="outline" color="gray">
                {genre}
              </Badge>
            ))}
          </Group>

          <Text size="xs" c="dimmed" lineClamp={3} dir="auto">
            {card.overview || 'Pas de synopsis dans le brut collecté.'}
          </Text>

          <Stack gap={4} mt="auto">
            <Group gap={4} justify="space-between" wrap="nowrap">
              <Group gap={3} wrap="nowrap">
                {(covered.length ? covered : languages.slice(0, 1)).map((language) => {
                  const count = card.coverage[language.code]?.ok ?? 0
                  return (
                    <Tooltip
                      key={language.code}
                      label={`${language.label} — ${count} saison(s) collectée(s)`}
                    >
                      <Badge
                        size="xs"
                        variant={language.code === lang ? 'filled' : 'light'}
                        color={count ? 'teal' : 'gray'}
                      >
                        {language.flag} {count || '—'}
                      </Badge>
                    </Tooltip>
                  )
                })}
              </Group>
              <Text size="xs" c="dimmed">
                {card.expectedParts
                  ? `${card.selected.ok}/${card.expectedParts} · ${formatPercent(card.selected.ratio)}`
                  : '—'}
              </Text>
            </Group>
            <Progress
              value={(card.selected.ratio ?? 0) * 100}
              size="xs"
              radius="xl"
              color={card.selected.ratio === 1 ? 'teal' : card.selected.ratio ? 'indigo' : 'gray'}
            />
          </Stack>
        </Stack>
      </Group>
    </Card>
  )
}
