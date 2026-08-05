import {
  Badge,
  Center,
  Group,
  Pagination,
  Paper,
  Progress,
  ScrollArea,
  Skeleton,
  Stack,
  Table,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import { IconArrowDown, IconArrowUp, IconArrowsSort } from '@tabler/icons-react'

import { STATE_LABELS, formatDate, formatNumber, titleDirection } from '../display'
import type { Item, ItemsResponse, Language } from '../types'

/** Le tableau d'acquisition. Chaque ligne dit deux choses : où en est l'œuvre
 *  dans la langue choisie (colonne « couverture »), et comment les autres
 *  langues se comparent (colonne « langues »). */
export function AcquisitionTable({
  data,
  loading,
  lang,
  languages,
  page,
  onPage,
  onOpen,
  sort,
  order,
  onSort,
}: {
  data: ItemsResponse | undefined
  loading: boolean
  lang: string
  languages: Language[]
  page: number
  onPage: (page: number) => void
  onOpen: (id: number) => void
  sort: string
  order: 'asc' | 'desc'
  onSort: (sort: string, order: 'asc' | 'desc') => void
}) {
  const toggle = (key: string) => {
    if (sort === key) onSort(key, order === 'desc' ? 'asc' : 'desc')
    else onSort(key, key === 'name' ? 'asc' : 'desc')
  }

  // Les langues affichées en colonne « langues » : celles de la configuration,
  // dans leur ordre, complétées par toute langue qu'on rencontre sur une ligne.
  const columns = languages.filter(
    (language) => data?.languages.includes(language.code) || language.code === lang,
  )

  const pages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1

  return (
    <Paper withBorder radius="md">
      <ScrollArea>
        <Table striped highlightOnHover verticalSpacing="xs" miw={980}>
          <Table.Thead>
            <Table.Tr>
              <SortableHead label="Id" column="id" sort={sort} order={order} onClick={toggle} w={90} />
              <SortableHead label="Titre original" column="name" sort={sort} order={order} onClick={toggle} />
              <SortableHead
                label="Popularité"
                column="popularity"
                sort={sort}
                order={order}
                onClick={toggle}
                w={120}
                align="right"
              />
              <Table.Th w={150}>État</Table.Th>
              <Table.Th w={190}>Couverture</Table.Th>
              <Table.Th w={40 + columns.length * 62}>Langues</Table.Th>
              <SortableHead
                label="Dernière collecte"
                column="fetched"
                sort={sort}
                order={order}
                onClick={toggle}
                w={160}
              />
            </Table.Tr>
          </Table.Thead>

          <Table.Tbody>
            {loading && !data
              ? Array.from({ length: 8 }, (_, index) => (
                  <Table.Tr key={index}>
                    <Table.Td colSpan={7}>
                      <Skeleton h={24} />
                    </Table.Td>
                  </Table.Tr>
                ))
              : data?.items.map((item) => (
                  <Row
                    key={item.id}
                    item={item}
                    lang={lang}
                    columns={columns}
                    onOpen={() => onOpen(item.id)}
                  />
                ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>

      {data && data.items.length === 0 && (
        <Center p="xl">
          <Stack gap={4} align="center">
            <Text fw={600}>Aucune œuvre ne correspond</Text>
            <Text size="sm" c="dimmed">
              Élargir la recherche, ou revenir à « Tout le catalogue ».
            </Text>
          </Stack>
        </Center>
      )}

      <Group justify="space-between" p="sm">
        <Text size="sm" c="dimmed">
          {data ? `${formatNumber(data.total)} œuvre(s)` : '—'}
        </Text>
        <Pagination
          value={page}
          onChange={onPage}
          total={pages}
          siblings={1}
          withEdges
          size="sm"
          disabled={!data}
        />
      </Group>
    </Paper>
  )
}

function Row({
  item,
  lang,
  columns,
  onOpen,
}: {
  item: Item
  lang: string
  columns: Language[]
  onOpen: () => void
}) {
  const state = STATE_LABELS[item.state]
  const { ok, failed, ratio } = item.selected

  return (
    <Table.Tr style={{ cursor: 'pointer' }} onClick={onOpen}>
      <Table.Td>
        <Text size="sm" c="dimmed" ff="monospace">
          {item.id}
        </Text>
      </Table.Td>

      <Table.Td>
        {/* `dir="auto"` : un titre arabe s'affiche de droite à gauche dans une
            colonne qui contient aussi du latin. */}
        <Text size="sm" dir={titleDirection} lineClamp={1}>
          {item.title ?? <Text span c="dimmed">sans titre</Text>}
        </Text>
      </Table.Td>

      <Table.Td ta="right">
        <Text size="sm" ff="monospace">
          {item.popularity.toFixed(2)}
        </Text>
      </Table.Td>

      <Table.Td>
        <Tooltip label={state.help} multiline w={260}>
          <Badge color={state.color} variant="light" size="sm">
            {state.label}
          </Badge>
        </Tooltip>
      </Table.Td>

      <Table.Td>
        {item.expectedParts === 0 ? (
          <Text size="xs" c="dimmed">
            aucune partie énumérée
          </Text>
        ) : (
          <Stack gap={2}>
            <Group gap={6} justify="space-between">
              <Text size="xs" ff="monospace">
                {ok} / {item.expectedParts}
              </Text>
              {failed > 0 && (
                <Text size="xs" c="red">
                  {failed} échec(s)
                </Text>
              )}
            </Group>
            <Progress
              value={(ratio ?? 0) * 100}
              size="sm"
              radius="xl"
              color={ratio === 1 ? 'teal' : ratio ? 'indigo' : 'gray'}
            />
          </Stack>
        )}
      </Table.Td>

      <Table.Td>
        <Group gap={4} wrap="nowrap">
          {columns.map((language) => {
            const coverage = item.coverage[language.code]
            const selected = language.code === lang
            const count = coverage?.ok ?? 0
            const broken = (coverage?.failed ?? 0) > 0

            return (
              <Tooltip
                key={language.code}
                label={`${language.label} — ${count} collectée(s)${broken ? `, ${coverage?.failed} en échec` : ''}`}
              >
                <Badge
                  size="sm"
                  variant={selected ? 'filled' : count ? 'light' : 'outline'}
                  color={count ? (broken ? 'orange' : 'teal') : 'gray'}
                  style={{ minWidth: 58 }}
                >
                  {language.flag} {count || '—'}
                </Badge>
              </Tooltip>
            )
          })}
        </Group>
      </Table.Td>

      <Table.Td>
        <Text size="xs" c={item.fetch.lastFetchedAt ? undefined : 'dimmed'}>
          {formatDate(item.fetch.lastFetchedAt)}
        </Text>
        {item.fetch.lastStatus !== null && item.fetch.lastStatus >= 400 && (
          <Text size="xs" c="red">
            HTTP {item.fetch.lastStatus}
          </Text>
        )}
      </Table.Td>
    </Table.Tr>
  )
}

function SortableHead({
  label,
  column,
  sort,
  order,
  onClick,
  w,
  align = 'left',
}: {
  label: string
  column: string
  sort: string
  order: 'asc' | 'desc'
  onClick: (column: string) => void
  w?: number
  align?: 'left' | 'right'
}) {
  const active = sort === column
  const Icon = !active ? IconArrowsSort : order === 'desc' ? IconArrowDown : IconArrowUp

  return (
    <Table.Th w={w}>
      <UnstyledButton onClick={() => onClick(column)} w="100%">
        <Group gap={4} wrap="nowrap" justify={align === 'right' ? 'flex-end' : 'flex-start'}>
          <Text size="sm" fw={active ? 700 : 600}>
            {label}
          </Text>
          <Icon size={14} opacity={active ? 1 : 0.35} />
        </Group>
      </UnstyledButton>
    </Table.Th>
  )
}
