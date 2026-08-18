import { Button, Group, NumberInput, Paper, Select, TextInput } from '@mantine/core'
import { IconSearch, IconX } from '@tabler/icons-react'

import { SORT_LABELS, STATUS_FILTERS } from '../display'

export interface FilterState {
  status: string
  search: string
  minPopularity: number | null
  sort: string
  order: 'asc' | 'desc'
  pageSize: number
}

export function Filters({
  value,
  onChange,
  langLabel,
  loading,
}: {
  value: FilterState
  onChange: (next: FilterState) => void
  langLabel: string
  loading: boolean
}) {
  const set = <K extends keyof FilterState>(key: K, next: FilterState[K]) =>
    onChange({ ...value, [key]: next })

  const dirty =
    value.status !== 'all' ||
    value.search !== '' ||
    value.minPopularity !== null ||
    value.sort !== 'popularity' ||
    value.order !== 'desc'

  return (
    <Paper withBorder radius="md" p="sm">
      <Group gap="sm" align="flex-end" wrap="wrap">
        <TextInput
          label="Recherche"
          placeholder="titre (toutes langues) ou id TMDB"
          leftSection={<IconSearch size={16} />}
          value={value.search}
          onChange={(event) => set('search', event.currentTarget.value)}
          w={260}
        />

        <Select
          label="État"
          description={`dans la langue : ${langLabel}`}
          data={STATUS_FILTERS}
          value={value.status}
          onChange={(next) => next && set('status', next)}
          allowDeselect={false}
          w={220}
        />

        <NumberInput
          label="Popularité minimale"
          placeholder="aucune"
          value={value.minPopularity ?? ''}
          onChange={(next) => set('minPopularity', next === '' ? null : Number(next))}
          min={0}
          step={0.5}
          decimalScale={2}
          w={170}
        />

        <Select
          label="Tri"
          data={Object.entries(SORT_LABELS).map(([key, label]) => ({ value: key, label }))}
          value={value.sort}
          onChange={(next) => next && set('sort', next)}
          allowDeselect={false}
          w={180}
        />

        <Select
          label="Sens"
          data={[
            { value: 'desc', label: 'décroissant' },
            { value: 'asc', label: 'croissant' },
          ]}
          value={value.order}
          onChange={(next) => next && set('order', next as 'asc' | 'desc')}
          allowDeselect={false}
          w={140}
        />

        <Select
          label="Par page"
          data={['25', '50', '100', '200']}
          value={String(value.pageSize)}
          onChange={(next) => next && set('pageSize', Number(next))}
          allowDeselect={false}
          w={100}
        />

        <Button
          variant="subtle"
          leftSection={<IconX size={16} />}
          onClick={() =>
            onChange({
              status: 'all',
              search: '',
              minPopularity: null,
              sort: 'popularity',
              order: 'desc',
              pageSize: value.pageSize,
            })
          }
          disabled={!dirty || loading}
        >
          Réinitialiser
        </Button>
      </Group>
    </Paper>
  )
}
