import { Alert, Group, Image, Loader, Stack, Text } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'

import { ApiError, api, tmdbImage } from '../api'
import { formatDate } from '../display'
import type { Language, SeasonDetail } from '../types'

/**
 * Les épisodes d'une saison, dans la langue choisie.
 *
 * Monté seulement quand le volet s'ouvre : une série de huit saisons porte deux
 * cents épisodes avec leurs synopsis, et personne ne les lit tous.
 *
 * C'est le seul endroit du front où changer de langue change vraiment le
 * contenu affiché, et pas seulement un compteur — parce que c'est le seul
 * endroit qui montre de la matière traduite.
 */
export function SeasonPanel({
  workId,
  seasonNumber,
  lang,
  languages,
}: {
  workId: number
  seasonNumber: number
  lang: string
  languages: Language[]
}) {
  const season = useQuery<SeasonDetail>({
    queryKey: ['season', workId, seasonNumber, lang],
    queryFn: () => api.season(workId, seasonNumber, lang),
  })

  const label = languages.find((entry) => entry.code === lang)?.label ?? lang

  if (season.isLoading) return <Loader size="sm" />

  if (season.error) {
    const missing = season.error instanceof ApiError && season.error.status === 404
    return (
      <Alert
        color={missing ? 'yellow' : 'red'}
        variant="light"
        icon={<IconAlertTriangle size={18} />}
      >
        {missing
          ? `Cette saison n'a pas été collectée en ${label}. Les synopsis d'épisode n'existent que dans les langues effectivement demandées à TMDB.`
          : (season.error as Error).message}
      </Alert>
    )
  }

  const data = season.data!

  return (
    <Stack gap="sm">
      {data.overview && (
        <Text size="sm" dir="auto">
          {data.overview}
        </Text>
      )}
      <Text size="xs" c="dimmed">
        {data.episodes.length} épisode(s) · collectée le {formatDate(data.fetchedAt)} en {label}
      </Text>

      {data.episodes.map((episode) => {
        const still = tmdbImage(episode.stillPath, 'w185')
        return (
          <Group key={episode.episodeNumber ?? episode.name} align="flex-start" wrap="nowrap" gap="sm">
            {still ? (
              <Image src={still} w={120} radius="sm" alt="" loading="lazy" style={{ flexShrink: 0 }} />
            ) : null}
            <Stack gap={2} style={{ minWidth: 0 }}>
              <Text size="sm" fw={600} dir="auto">
                {episode.episodeNumber ? `${episode.episodeNumber}. ` : ''}
                {episode.name ?? 'sans titre'}
              </Text>
              <Text size="xs" c="dimmed">
                {episode.airDate ?? 'date inconnue'}
                {episode.runtime ? ` · ${episode.runtime} min` : ''}
              </Text>
              <Text size="xs" dir="auto" lineClamp={4}>
                {episode.overview || <Text span c="dimmed">pas de synopsis dans cette langue</Text>}
              </Text>
            </Stack>
          </Group>
        )
      })}
    </Stack>
  )
}
