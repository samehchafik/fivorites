import {
  Accordion,
  Alert,
  Anchor,
  Avatar,
  Badge,
  Box,
  Center,
  Divider,
  Group,
  Image,
  Loader,
  Modal,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
} from '@mantine/core'
import {
  IconAlertTriangle,
  IconDeviceTv,
  IconExternalLink,
  IconPhoto,
  IconStar,
  IconUsers,
} from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api, tmdbImage } from '../api'
import { POSTER_FALLBACK, formatDate, formatNumber } from '../display'
import type { Language, Work } from '../types'
import { SeasonPanel } from './SeasonPanel'
import { WatchPanel } from './WatchPanel'

/**
 * La fiche complète d'une série, telle qu'elle est en base.
 *
 * Contrairement à la grille, elle relit le brut : ce qu'on ouvre n'est jamais
 * périmé, même si la projection des vignettes l'est.
 */
export function SeriesModal({
  id,
  lang,
  languages,
  onClose,
}: {
  id: number | null
  lang: string
  languages: Language[]
  onClose: () => void
}) {
  const [openSeason, setOpenSeason] = useState<string | null>(null)

  const work = useQuery<Work>({
    queryKey: ['work', id, lang],
    queryFn: () => api.work(id!, lang),
    enabled: id !== null,
  })

  // Chaque série rouvre sur sa première saison repliée : garder l'accordéon
  // ouvert d'une fiche à l'autre chargerait des épisodes que personne n'a
  // demandés.
  useEffect(() => setOpenSeason(null), [id])

  const data = work.data
  const backdrop = tmdbImage(data?.backdropPath, 'w780')
  const poster = tmdbImage(data?.posterPath, 'w342')
  const langLabel = languages.find((entry) => entry.code === lang)?.label ?? lang

  return (
    <Modal
      opened={id !== null}
      onClose={onClose}
      size="72rem"
      padding={0}
      scrollAreaComponent={ScrollArea.Autosize}
      title={null}
      withCloseButton
    >
      {work.isLoading && (
        <Center p="xl">
          <Loader />
        </Center>
      )}

      {work.error && (
        <Box p="lg">
          <Alert color="yellow" variant="light" icon={<IconAlertTriangle size={18} />}>
            {(work.error as Error).message}
          </Alert>
        </Box>
      )}

      {data && (
        <Stack gap={0}>
          {backdrop && (
            <Box
              h={200}
              style={{
                backgroundImage: `linear-gradient(to bottom, rgba(0,0,0,.15), var(--mantine-color-body)), url(${backdrop})`,
                backgroundSize: 'cover',
                backgroundPosition: 'center 20%',
              }}
            />
          )}

          <Box p="lg" mt={backdrop ? -60 : 0} style={{ position: 'relative' }}>
            <Group align="flex-start" wrap="nowrap" gap="lg">
              <Image
                src={poster}
                fallbackSrc={POSTER_FALLBACK}
                w={160}
                radius="md"
                alt=""
                style={{ flexShrink: 0, boxShadow: 'var(--mantine-shadow-md)' }}
              />

              <Stack gap="xs" style={{ minWidth: 0 }}>
                <Title order={3} dir="auto">
                  {data.name ?? `#${data.id}`}
                </Title>
                {data.originalName && data.originalName !== data.name && (
                  <Text size="sm" c="dimmed" dir="auto">
                    {data.originalName}
                  </Text>
                )}
                {data.tagline && (
                  <Text size="sm" fs="italic" dir="auto">
                    {data.tagline}
                  </Text>
                )}

                <Group gap="xs">
                  <Badge variant="light">
                    {data.firstAirDate?.slice(0, 4) ?? 'année inconnue'}
                  </Badge>
                  <Badge variant="light" color="grape">
                    {data.numberOfSeasons ?? '?'} saison(s)
                  </Badge>
                  <Badge variant="default">{data.numberOfEpisodes ?? '?'} épisodes</Badge>
                  {data.status && <Badge variant="outline">{data.status}</Badge>}
                  {data.voteAverage ? (
                    <Badge variant="light" color="yellow" leftSection={<IconStar size={12} />}>
                      {data.voteAverage.toFixed(1)} ({formatNumber(data.voteCount ?? 0)})
                    </Badge>
                  ) : null}
                  {data.genres.map((genre) => (
                    <Badge key={genre} variant="outline" color="gray">
                      {genre}
                    </Badge>
                  ))}
                </Group>

                <Text size="sm" dir="auto">
                  {data.overview || 'Pas de synopsis dans le brut collecté.'}
                </Text>

                <Group gap="lg">
                  <Anchor
                    href={`https://www.themoviedb.org/tv/${data.id}`}
                    target="_blank"
                    rel="noreferrer noopener"
                    size="sm"
                  >
                    <Group gap={4}>
                      TMDB <IconExternalLink size={14} />
                    </Group>
                  </Anchor>
                  {data.externalIds?.imdb_id && (
                    <Anchor
                      href={`https://www.imdb.com/title/${data.externalIds.imdb_id}/`}
                      target="_blank"
                      rel="noreferrer noopener"
                      size="sm"
                    >
                      <Group gap={4}>
                        IMDb <IconExternalLink size={14} />
                      </Group>
                    </Anchor>
                  )}
                  {data.externalIds?.wikidata_id && (
                    <Anchor
                      href={`https://www.wikidata.org/wiki/${data.externalIds.wikidata_id}`}
                      target="_blank"
                      rel="noreferrer noopener"
                      size="sm"
                    >
                      <Group gap={4}>
                        Wikidata <IconExternalLink size={14} />
                      </Group>
                    </Anchor>
                  )}
                </Group>
              </Stack>
            </Group>
          </Box>

          <Divider />

          <Tabs defaultValue="watch" keepMounted={false}>
            <Tabs.List px="lg">
              <Tabs.Tab value="watch" leftSection={<IconDeviceTv size={16} />}>
                Où regarder
                {data.watch.offers.length > 0 &&
                  ` (${data.watch.offers.reduce((n, o) => n + o.providers.length, 0)})`}
              </Tabs.Tab>
              <Tabs.Tab value="seasons">Saisons ({data.seasons.length})</Tabs.Tab>
              <Tabs.Tab value="cast" leftSection={<IconUsers size={16} />}>
                Distribution ({data.cast.length})
              </Tabs.Tab>
              <Tabs.Tab value="gallery" leftSection={<IconPhoto size={16} />}>
                Galerie ({data.gallery.backdrops.length + data.gallery.posters.length})
              </Tabs.Tab>
              <Tabs.Tab value="technical">Technique</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="watch" p="lg">
              <WatchPanel watch={data.watch} languages={languages} />
            </Tabs.Panel>

            <Tabs.Panel value="seasons" p="lg">
              <Text size="xs" c="dimmed" mb="sm">
                Les épisodes s'affichent en {langLabel} — la langue du sélecteur. Une saison non
                collectée dans cette langue le dit plutôt que de tomber sur une autre.
              </Text>

              <Accordion value={openSeason} onChange={setOpenSeason} variant="separated">
                {data.seasons.map((season) => {
                  const number = season.seasonNumber
                  if (number === null) return null
                  const value = String(number)
                  const poster = tmdbImage(season.posterPath, 'w92')

                  return (
                    <Accordion.Item key={value} value={value}>
                      <Accordion.Control>
                        <Group wrap="nowrap" gap="sm">
                          <Image src={poster} fallbackSrc={POSTER_FALLBACK} w={40} radius="sm" alt="" />
                          <Stack gap={2} style={{ minWidth: 0 }}>
                            <Text size="sm" fw={600} dir="auto">
                              {season.name ?? `Saison ${number}`}
                            </Text>
                            <Group gap={6}>
                              <Text size="xs" c="dimmed">
                                {season.airDate ?? 'date inconnue'} ·{' '}
                                {season.episodeCount ?? '?'} épisode(s)
                              </Text>
                              {languages.map((language) => {
                                const cell = season.collected[language.code]
                                if (!cell) return null
                                const ok = cell.status >= 200 && cell.status < 300
                                return (
                                  <Badge
                                    key={language.code}
                                    size="xs"
                                    variant={language.code === lang ? 'filled' : 'light'}
                                    color={ok ? 'teal' : 'red'}
                                  >
                                    {language.flag}
                                  </Badge>
                                )
                              })}
                            </Group>
                          </Stack>
                        </Group>
                      </Accordion.Control>
                      <Accordion.Panel>
                        {openSeason === value && (
                          <SeasonPanel
                            workId={data.id}
                            seasonNumber={number}
                            lang={lang}
                            languages={languages}
                          />
                        )}
                      </Accordion.Panel>
                    </Accordion.Item>
                  )
                })}
              </Accordion>
            </Tabs.Panel>

            <Tabs.Panel value="cast" p="lg">
              {data.cast.length === 0 ? (
                <Text size="sm" c="dimmed">
                  Aucune distribution dans le brut collecté.
                </Text>
              ) : (
                <SimpleGrid cols={{ base: 2, sm: 3, md: 4, lg: 5 }} spacing="md">
                  {data.cast.map((member, index) => (
                    <Group key={member.id ?? index} gap="xs" wrap="nowrap">
                      <Avatar
                        src={tmdbImage(member.profilePath, 'w185')}
                        radius="sm"
                        size="lg"
                        alt=""
                      />
                      <Stack gap={0} style={{ minWidth: 0 }}>
                        <Text size="sm" fw={600} lineClamp={1} dir="auto">
                          {member.name}
                        </Text>
                        <Text size="xs" c="dimmed" lineClamp={2} dir="auto">
                          {member.character ?? '—'}
                        </Text>
                        {member.episodeCount ? (
                          <Text size="xs" c="dimmed">
                            {member.episodeCount} épisode(s)
                          </Text>
                        ) : null}
                      </Stack>
                    </Group>
                  ))}
                </SimpleGrid>
              )}
            </Tabs.Panel>

            <Tabs.Panel value="gallery" p="lg">
              <Stack gap="lg">
                <Gallery title="Visuels larges" paths={data.gallery.backdrops} size="w300" />
                <Gallery title="Affiches" paths={data.gallery.posters} size="w185" />
              </Stack>
            </Tabs.Panel>

            <Tabs.Panel value="technical" p="lg">
              <Table variant="vertical" withTableBorder>
                <Table.Tbody>
                  <Field label="Id TMDB" value={String(data.id)} />
                  <Field label="Type" value={data.type ?? '—'} />
                  <Field label="Langue originale" value={data.originalLanguage ?? '—'} />
                  <Field label="Pays d'origine" value={data.originCountry.join(', ') || '—'} />
                  <Field
                    label="Diffusion"
                    value={`${data.firstAirDate ?? '?'} → ${data.lastAirDate ?? '?'}`}
                  />
                  <Field
                    label="Diffuseurs"
                    value={data.networks.map((network) => network.name).join(', ') || '—'}
                  />
                  <Field label="Créée par" value={data.createdBy.join(', ') || '—'} />
                  <Field
                    label="Traductions annoncées"
                    value={data.translations.join(', ') || 'aucune'}
                  />
                  <Field label="Popularité" value={data.catalog?.popularity.toFixed(2) ?? '—'} />
                  <Field
                    label="Brut lu"
                    value={`${formatDate(data.raw.fetchedAt)} · HTTP ${data.raw.httpStatus}`}
                  />
                </Table.Tbody>
              </Table>
              <Text size="xs" c="dimmed" mt="sm">
                Une traduction annoncée par TMDB ne dit rien des synopsis d'épisode : ceux-là
                n'existent que dans les langues effectivement redemandées à la collecte. C'est
                toute la raison d'un appel par langue et par saison.
              </Text>
            </Tabs.Panel>
          </Tabs>
        </Stack>
      )}
    </Modal>
  )
}

function Gallery({ title, paths, size }: { title: string; paths: string[]; size: string }) {
  if (paths.length === 0) return null
  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        {title}
      </Text>
      <SimpleGrid cols={{ base: 2, sm: 3, md: 4 }} spacing="sm">
        {paths.map((path) => (
          <Anchor
            key={path}
            href={tmdbImage(path, 'original') ?? undefined}
            target="_blank"
            rel="noreferrer noopener"
          >
            <Image src={tmdbImage(path, size)} radius="sm" alt="" loading="lazy" />
          </Anchor>
        ))}
      </SimpleGrid>
    </Stack>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <Table.Tr>
      <Table.Th w={200}>{label}</Table.Th>
      <Table.Td>{value}</Table.Td>
    </Table.Tr>
  )
}
