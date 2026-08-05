import {
  Alert,
  Button,
  Center,
  Group,
  Pagination,
  Paper,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  TextInput,
} from '@mantine/core'
import { IconAlertTriangle, IconRefresh, IconSearch } from '@tabler/icons-react'

import { formatDate, formatNumber } from '../display'
import type { CardsResponse, Language } from '../types'
import { SeriesCard } from './SeriesCard'

export const CARD_SORTS: { value: string; label: string }[] = [
  { value: 'air_date', label: 'Date de diffusion' },
  { value: 'name', label: 'Titre' },
  { value: 'popularity', label: 'Popularité' },
  { value: 'fetched', label: 'Dernière collecte' },
]

export interface GridState {
  search: string
  sort: string
  order: 'asc' | 'desc'
  pageSize: number
}

export function SeriesGrid({
  data,
  loading,
  state,
  onState,
  languages,
  lang,
  page,
  onPage,
  onOpen,
  onRefreshProjection,
  refreshing,
}: {
  data: CardsResponse | undefined
  loading: boolean
  state: GridState
  onState: (next: GridState) => void
  languages: Language[]
  lang: string
  page: number
  onPage: (page: number) => void
  onOpen: (id: number) => void
  onRefreshProjection: () => void
  refreshing: boolean
}) {
  const pages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1
  const projection = data?.projection

  return (
    <Stack gap="md">
      <Paper withBorder radius="md" p="sm">
        <Group gap="sm" align="flex-end" wrap="wrap">
          <TextInput
            label="Recherche"
            placeholder="titre, titre original ou id"
            leftSection={<IconSearch size={16} />}
            value={state.search}
            onChange={(event) => onState({ ...state, search: event.currentTarget.value })}
            w={280}
          />
          <Select
            label="Tri"
            data={CARD_SORTS}
            value={state.sort}
            onChange={(next) => next && onState({ ...state, sort: next })}
            allowDeselect={false}
            w={200}
          />
          <Select
            label="Sens"
            data={[
              { value: 'desc', label: 'du plus récent au plus ancien' },
              { value: 'asc', label: 'du plus ancien au plus récent' },
            ]}
            value={state.order}
            onChange={(next) => next && onState({ ...state, order: next as 'asc' | 'desc' })}
            allowDeselect={false}
            w={260}
          />
          <Select
            label="Par page"
            data={['12', '24', '48', '96']}
            value={String(state.pageSize)}
            onChange={(next) => next && onState({ ...state, pageSize: Number(next) })}
            allowDeselect={false}
            w={100}
          />
          <Button
            variant="default"
            leftSection={<IconRefresh size={16} />}
            onClick={onRefreshProjection}
            loading={refreshing}
          >
            Rafraîchir la projection
          </Button>
        </Group>
      </Paper>

      {projection?.stale && (
        <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
          {formatNumber(projection.collected - projection.projected)} série(s) collectée(s) depuis
          le dernier calcul des vignettes. « Rafraîchir la projection » les fera apparaître.
        </Alert>
      )}

      {loading && !data ? (
        <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="md">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} h={168} radius="md" />
          ))}
        </SimpleGrid>
      ) : data && data.items.length === 0 ? (
        <EmptyGrid projected={projection?.projected ?? 0} searching={state.search.length > 0} />
      ) : (
        <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="md">
          {data?.items.map((card) => (
            <SeriesCard
              key={card.id}
              card={card}
              languages={languages}
              lang={lang}
              onOpen={() => onOpen(card.id)}
            />
          ))}
        </SimpleGrid>
      )}

      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          {data
            ? `${formatNumber(data.total)} série(s) collectée(s)${
                projection?.lastAt ? ` · brut le plus récent ${formatDate(projection.lastAt)}` : ''
              }`
            : '—'}
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
    </Stack>
  )
}

/** Une grille vide a deux causes très différentes, et les confondre coûte une
 *  demi-heure de recherche : rien ne correspond au filtre, ou rien n'a encore
 *  été collecté. */
function EmptyGrid({ projected, searching }: { projected: number; searching: boolean }) {
  if (searching || projected > 0) {
    return (
      <Center p="xl">
        <Stack gap={4} align="center">
          <Text fw={600}>Aucune série ne correspond</Text>
          <Text size="sm" c="dimmed">
            Élargir la recherche, ou vider le champ.
          </Text>
        </Stack>
      </Center>
    )
  }

  return (
    <Alert color="yellow" variant="light" title="Aucune série collectée" icon={<IconAlertTriangle size={18} />}>
      <Stack gap={6}>
        <Text size="sm">
          Les vignettes viennent du brut téléchargé chez TMDB ; le catalogue seul ne porte qu'un id,
          un titre original et une popularité — ni affiche, ni synopsis, ni date.
        </Text>
        <Text size="sm">
          Lancer une collecte, puis rafraîchir la projection :
        </Text>
        <Text size="sm" ff="monospace">
          .venv/bin/fiv-sourcing tmdb backfill --limit 200
          <br />
          .venv/bin/fiv-admin catalog refresh
        </Text>
        <Text size="xs" c="dimmed">
          L'onglet « Avancement » reste utilisable sans collecte : il porte sur tout le catalogue.
        </Text>
      </Stack>
    </Alert>
  )
}
