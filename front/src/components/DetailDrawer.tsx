import {
  Alert,
  Anchor,
  Badge,
  Code,
  Divider,
  Drawer,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { IconAlertTriangle, IconExternalLink } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api'
import { formatDate, titleDirection } from '../display'
import type { Detail, Language } from '../types'

/** Le détail d'une œuvre : la matrice partie × langue, telle qu'elle est en
 *  base. C'est le seul endroit où l'on ouvre un payload — et pour une ligne. */
export function DetailDrawer({
  media,
  id,
  lang,
  languages,
  onClose,
}: {
  media: string
  id: number | null
  lang: string
  languages: Language[]
  onClose: () => void
}) {
  const detail = useQuery<Detail>({
    queryKey: ['detail', media, id],
    queryFn: () => api.detail(media, id!),
    enabled: id !== null,
  })

  const columns = languages.filter(
    (language) =>
      language.code === lang ||
      detail.data?.parts.some((part) => part.langs[language.code] !== undefined),
  )

  return (
    <Drawer
      opened={id !== null}
      onClose={onClose}
      position="right"
      size="xl"
      title={
        <Group gap="xs">
          <Text fw={700}>{detail.data?.title ?? `#${id}`}</Text>
          {detail.data && <Badge variant="light">{detail.data.id}</Badge>}
        </Group>
      }
    >
      {detail.isLoading && <Loader />}

      {detail.error && (
        <Alert color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
          {(detail.error as Error).message}
        </Alert>
      )}

      {detail.data && (
        <Stack gap="lg">
          <Stack gap={4}>
            <Text dir={titleDirection} fz="lg" fw={600}>
              {detail.data.payload?.name ?? detail.data.title}
            </Text>
            <Group gap="xs">
              <Badge variant="light">popularité {detail.data.popularity.toFixed(2)}</Badge>
              {detail.data.payload?.firstAirDate && (
                <Badge variant="light">{detail.data.payload.firstAirDate}</Badge>
              )}
              {detail.data.payload?.tmdbStatus && (
                <Badge variant="light">{detail.data.payload.tmdbStatus}</Badge>
              )}
              {detail.data.payload?.originCountry.map((country) => (
                <Badge key={country} variant="outline">
                  {country}
                </Badge>
              ))}
            </Group>
            <Anchor
              href={`https://www.themoviedb.org/tv/${detail.data.id}`}
              target="_blank"
              rel="noreferrer noopener"
              size="sm"
            >
              <Group gap={4}>
                Voir sur TMDB <IconExternalLink size={14} />
              </Group>
            </Anchor>
          </Stack>

          <Divider label="État de la collecte" labelPosition="left" />

          <Table variant="vertical" withTableBorder>
            <Table.Tbody>
              <Field label="Dernier passage" value={formatDate(detail.data.fetch.lastFetchedAt)} />
              <Field label="Dernier succès" value={formatDate(detail.data.fetch.lastSuccessAt)} />
              <Field label="Dernier changement" value={formatDate(detail.data.fetch.lastChangedAt)} />
              <Field
                label="Dernier code HTTP"
                value={detail.data.fetch.lastStatus ? String(detail.data.fetch.lastStatus) : '—'}
              />
              <Field label="Tentatives" value={String(detail.data.fetch.attempts)} />
              <Field label="Vu au catalogue le" value={formatDate(detail.data.lastSeenAt)} />
            </Table.Tbody>
          </Table>

          {detail.data.fetch.lastError && (
            <Alert color="red" variant="light" title="Dernière erreur">
              <Code block>{detail.data.fetch.lastError}</Code>
            </Alert>
          )}

          {detail.data.payload && (
            <>
              <Divider label="Ce que déclare TMDB" labelPosition="left" />
              <Group gap="xs">
                <Text size="sm">
                  {detail.data.payload.seasonsDeclared} saison(s) déclarée(s) · langue originale{' '}
                  <Code>{detail.data.payload.originalLanguage ?? '?'}</Code> · fiche récupérée le{' '}
                  {formatDate(detail.data.payload.fetchedAt)}
                </Text>
              </Group>
              <Group gap={4}>
                <Text size="sm" c="dimmed">
                  Traductions annoncées :
                </Text>
                {detail.data.payload.translations.length ? (
                  detail.data.payload.translations.map((code) => (
                    <Badge key={code} size="sm" variant="outline">
                      {code}
                    </Badge>
                  ))
                ) : (
                  <Text size="sm" c="dimmed">
                    aucune
                  </Text>
                )}
              </Group>
              <Text size="xs" c="dimmed">
                Une traduction annoncée ne dit rien des synopsis d'épisode : ceux-là ne s'obtiennent
                qu'en redemandant la saison dans la langue voulue. C'est la raison d'un appel par
                langue, et de la colonne ci-dessous.
              </Text>
            </>
          )}

          <Divider label="Parties collectées, langue par langue" labelPosition="left" />

          {detail.data.parts.length === 0 ? (
            <Text size="sm" c="dimmed">
              Aucune partie collectée pour l'instant.
            </Text>
          ) : (
            <ScrollArea>
              <Table withTableBorder striped verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Partie</Table.Th>
                    {columns.map((language) => (
                      <Table.Th key={language.code} ta="center">
                        {language.flag} {language.code}
                      </Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {detail.data.parts.map((part) => (
                    <Table.Tr key={part.id}>
                      <Table.Td>
                        <Code>{part.id}</Code>
                      </Table.Td>
                      {columns.map((language) => {
                        const cell = part.langs[language.code]
                        const ok = cell && cell.status >= 200 && cell.status < 300
                        return (
                          <Table.Td key={language.code} ta="center">
                            {cell ? (
                              <Badge
                                size="sm"
                                variant="light"
                                color={ok ? 'teal' : 'red'}
                                title={formatDate(cell.fetchedAt)}
                              >
                                {cell.status}
                              </Badge>
                            ) : (
                              <Text size="xs" c="dimmed">
                                —
                              </Text>
                            )}
                          </Table.Td>
                        )
                      })}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          )}

          <Title order={6} c="dimmed">
            Rappel
          </Title>
          <Text size="xs" c="dimmed">
            Une ligne de brut par réponse HTTP : chaque partie a sa propre fraîcheur, son propre
            statut et sa propre empreinte. Ce tableau est donc l'état réel du stockage, pas un
            résumé calculé.
          </Text>
        </Stack>
      )}
    </Drawer>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <Table.Tr>
      <Table.Th w={180}>{label}</Table.Th>
      <Table.Td>{value}</Table.Td>
    </Table.Tr>
  )
}
