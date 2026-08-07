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
  SegmentedControl,
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
  IconId,
  IconPhoto,
  IconScale,
  IconSchool,
  IconStar,
  IconUsers,
} from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api, tmdbImage } from '../api'
import { POSTER_FALLBACK, formatDate, formatNumber } from '../display'
import type { Language, ModalTab, Work } from '../types'
import { SeasonPanel } from './SeasonPanel'
import { TrainingTab } from './TrainingTab'
import { WatchPanel } from './WatchPanel'

/**
 * La fiche complète d'une série, telle qu'elle est en base.
 *
 * Contrairement à la grille, elle relit le brut : ce qu'on ouvre n'est jamais
 * périmé, même si la projection des vignettes l'est.
 */
/**
 * Le décalage de la croix de fermeture.
 *
 * Les deux fenêtres sont en `padding={0}` — c'est ce qui permet au décor et aux
 * visuels d'aller d'un bord à l'autre — mais l'en-tête hérite du même zéro, et
 * la croix se retrouve collée au bord droit, par-dessus la barre de défilement.
 * On la remet où on l'attend : en haut à droite, mais à distance du bord.
 */
const CROIX = { close: { marginRight: 'var(--mantine-spacing-md)' } }

export function SeriesModal({
  id,
  tab,
  lang,
  languages,
  onLang,
  onTab,
  onClose,
}: {
  id: number | null
  /** L'onglet affiché — présentation ou l'un des deux ateliers. L'état vit
   *  chez le parent parce qu'il vit dans l'URL : `?id=1399&onglet=training1`
   *  rouvre la fiche directement sur l'atelier. */
  tab: ModalTab
  lang: string
  languages: Language[]
  /** Changer de langue depuis la fiche change la langue de toute
   *  l'application : c'est la même donnée, et deux langues courantes
   *  différentes selon l'écran seraient impossibles à tenir dans l'URL. */
  onLang: (code: string) => void
  onTab: (tab: ModalTab) => void
  onClose: () => void
}) {
  const [openSeason, setOpenSeason] = useState<string | null>(null)
  // Le visuel agrandi, s'il y en a un. Un seul état pour toute la fiche : les
  // affiches, la galerie, la distribution et les images d'épisode passent par
  // le même agrandissement.
  const [zoom, setZoom] = useState<string | null>(null)

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
      styles={CROIX}
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

      {/* Trois onglets de premier niveau : la présentation (la fiche telle
          qu'elle était), puis les deux ateliers d'entraînement de la notation.
          `keepMounted={false}` : ouvrir la fiche ne déclenche pas la
          construction du dossier de notation tant qu'on ne va pas l'y chercher. */}
      {data && (
        <Tabs
          value={tab}
          onChange={(next) => next && onTab(next as ModalTab)}
          keepMounted={false}
        >
          <Tabs.List px="lg" pt="xs">
            <Tabs.Tab value="presentation" leftSection={<IconId size={16} />}>
              {data.name ?? `Série ${data.id}`}
            </Tabs.Tab>
            <Tabs.Tab value="training1" leftSection={<IconSchool size={16} />}>
              Training 1
            </Tabs.Tab>
            <Tabs.Tab value="training2" leftSection={<IconScale size={16} />}>
              Training 2
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="presentation">
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
                onClick={() => data.posterPath && setZoom(data.posterPath)}
                style={{
                  flexShrink: 0,
                  boxShadow: 'var(--mantine-shadow-md)',
                  cursor: data.posterPath ? 'zoom-in' : undefined,
                }}
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

                {/* La fiche n'est téléchargée qu'en français ; seules ses
                    traductions varient. Quand celle de la langue choisie
                    manque, le texte affiché est le français — le dire vaut
                    mieux que de laisser croire à une collecte complète, ce que
                    ce tableau de bord a précisément pour rôle de mesurer. */}
                {data.translated &&
                  data.translated.lang !== 'fr-FR' &&
                  (!data.translated.name || !data.translated.overview) && (
                    <Text size="xs" c="dimmed">
                      {data.translated.name || data.translated.overview
                        ? `Traduction partielle en ${langLabel} — ${
                            data.translated.name ? 'le synopsis' : 'le titre'
                          } est affiché en français.`
                        : `Aucune traduction en ${langLabel} : titre et synopsis sont affichés en français.`}
                    </Text>
                  )}

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

                {/* Le même sélecteur qu'en en-tête, à portée de main là où la
                    langue compte le plus : c'est ici que le texte change
                    vraiment, pas seulement un compteur. Des drapeaux plutôt
                    qu'une liste déroulante — cinq choix, et l'on bascule
                    souvent de l'un à l'autre pour comparer. */}
                {languages.length > 1 && (
                  <Group gap="xs" align="center">
                    <Text size="xs" c="dimmed">
                      Afficher en
                    </Text>
                    <SegmentedControl
                      size="xs"
                      value={lang}
                      onChange={onLang}
                      data={languages.map((entry) => ({
                        value: entry.code,
                        label: `${entry.flag} ${entry.code.slice(0, 2).toUpperCase()}`,
                      }))}
                    />
                  </Group>
                )}
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
                          <Image
                            src={poster}
                            fallbackSrc={POSTER_FALLBACK}
                            w={40}
                            radius="sm"
                            alt=""
                            onClick={(event) => {
                              // Sans ça, agrandir l'affiche d'une saison
                              // déplierait aussi son volet.
                              event.stopPropagation()
                              if (season.posterPath) setZoom(season.posterPath)
                            }}
                            style={{ cursor: season.posterPath ? 'zoom-in' : undefined }}
                          />
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
                            onZoom={setZoom}
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
                        onClick={() => member.profilePath && setZoom(member.profilePath)}
                        style={{ cursor: member.profilePath ? 'zoom-in' : undefined }}
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
                <Gallery
                  title="Visuels larges"
                  paths={data.gallery.backdrops}
                  size="w300"
                  onZoom={setZoom}
                />
                <Gallery
                  title="Affiches"
                  paths={data.gallery.posters}
                  size="w185"
                  onZoom={setZoom}
                />
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
          </Tabs.Panel>

          <Tabs.Panel value="training1" p="lg">
            <TrainingTab id={data.id} phase={1} />
          </Tabs.Panel>
          <Tabs.Panel value="training2" p="lg">
            <TrainingTab id={data.id} phase={2} />
          </Tabs.Panel>
        </Tabs>
      )}

      {/* L'agrandissement. Une fenêtre dans la fenêtre : Mantine les empile
          correctement, et refermer celle-ci ne referme pas la fiche — on
          enchaîne donc les visuels sans perdre sa place.

          800 × 600 est un cadre, pas un redimensionnement : les visuels de TMDB
          n'ont pas tous le même rapport (16/9 pour les décors, 2/3 pour les
          affiches). L'image est contenue dedans, jamais déformée. */}
      <Modal
        opened={zoom !== null}
        onClose={() => setZoom(null)}
        size={800}
        padding={0}
        withCloseButton
        title={null}
        zIndex={300}
        styles={CROIX}
      >
        {zoom && (
          <Image
            src={tmdbImage(zoom, 'w780')}
            fallbackSrc={POSTER_FALLBACK}
            alt=""
            h={600}
            fit="contain"
            bg="black"
          />
        )}
      </Modal>
    </Modal>
  )
}

function Gallery({
  title,
  paths,
  size,
  onZoom,
}: {
  title: string
  paths: string[]
  size: string
  onZoom: (path: string) => void
}) {
  if (paths.length === 0) return null
  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        {title}
      </Text>
      <SimpleGrid cols={{ base: 2, sm: 3, md: 4 }} spacing="sm">
        {paths.map((path) => (
          <Image
            key={path}
            src={tmdbImage(path, size)}
            radius="sm"
            alt=""
            loading="lazy"
            onClick={() => onZoom(path)}
            style={{ cursor: 'zoom-in' }}
          />
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
