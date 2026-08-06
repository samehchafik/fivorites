import {
  ActionIcon,
  Alert,
  AppShell,
  Badge,
  Button,
  Group,
  Menu,
  SegmentedControl,
  Stack,
  Tabs,
  Text,
  Title,
  Tooltip,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle, IconLogout, IconRefresh, IconUser } from '@tabler/icons-react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import { ApiError, api } from '../api'
import { formatNumber } from '../display'
import type { Account, CardsResponse, ItemsResponse, Meta, Summary } from '../types'
import { readUrl, writeUrl } from '../urlState'
import { AcquisitionTable } from './AcquisitionTable'
import { DetailDrawer } from './DetailDrawer'
import { Filters, type FilterState } from './Filters'
import { LanguageCoverage } from './LanguageCoverage'
import { LanguagePicker } from './LanguagePicker'
import { SeriesGrid, type GridState } from './SeriesGrid'
import { SeriesModal } from './SeriesModal'
import { SummaryCards } from './SummaryCards'

const DEFAULT_FILTERS: FilterState = {
  status: 'all',
  search: '',
  minPopularity: null,
  sort: 'popularity',
  order: 'desc',
  pageSize: 50,
}

const DEFAULT_GRID: GridState = {
  search: '',
  // « De la plus récente à la plus ancienne », mais à l'**année** et non au
  // jour. Au jour près, deux séries n'ont presque jamais la même date : le
  // critère de départage ci-dessous n'aurait alors rien à départager, et
  // paraîtrait ne pas fonctionner. À l'année, il classe pour de bon.
  sort: 'air_year',
  order: 'desc',
  // Le départage, par défaut sur la popularité : à date de diffusion égale —
  // et elles le sont souvent, tout un lot sortant le même jour — l'ordre serait
  // sinon arbitraire et pourrait changer d'une page à l'autre.
  sort2: 'popularity',
  order2: 'desc',
  withPoster: false,
  withOverview: false,
  pageSize: 24,
}

/**
 * Deux vues, deux questions différentes.
 *
 * **Catalogue** montre ce qui a été collecté — une carte par série, affiche,
 * année, saisons. C'est la vue de consultation.
 *
 * **Avancement** montre le catalogue entier, collecté ou non, avec l'état par
 * langue. C'est la vue de pilotage : elle répond à « que reste-t-il à faire »,
 * ce que la grille ne peut pas dire puisqu'une série non collectée n'a pas de
 * vignette.
 *
 * Le sélecteur de langue est commun aux deux, dans l'en-tête : c'est la même
 * question posée à deux échelles.
 */
export function Dashboard({ account, onSignedOut }: { account: Account; onSignedOut: () => void }) {
  const client = useQueryClient()

  // L'URL est la source au chargement : `?id=1399&lang=ar-SA&filtre=image`
  // ouvre la fiche, choisit la langue et coche la case. Lu une seule fois —
  // ensuite c'est l'état qui réécrit l'URL, et l'inverse bouclerait.
  const [depuisUrl] = useState(readUrl)

  const [view, setView] = useState<'cards' | 'table'>('cards')
  const [media, setMedia] = useState('tv')
  const [lang, setLang] = useState(depuisUrl.lang ?? 'fr-FR')

  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS)
  const [tablePage, setTablePage] = useState(1)
  const [drawerId, setDrawerId] = useState<number | null>(null)

  const [grid, setGrid] = useState<GridState>({
    ...DEFAULT_GRID,
    withPoster: depuisUrl.withPoster,
    withOverview: depuisUrl.withOverview,
  })
  const [gridPage, setGridPage] = useState(1)
  const [modalId, setModalId] = useState<number | null>(depuisUrl.id)

  // Une frappe ne doit pas lancer une requête par caractère sur 228 000 lignes.
  const [tableSearch] = useDebouncedValue(filters.search, 350)
  const [gridSearch] = useDebouncedValue(grid.search, 350)

  // … et l'état la réécrit, pour que la barre d'adresse soit toujours
  // copiable-collable telle quelle.
  useEffect(() => {
    writeUrl({
      id: modalId,
      lang,
      withPoster: grid.withPoster,
      withOverview: grid.withOverview,
    })
  }, [modalId, lang, grid.withPoster, grid.withOverview])

  const meta = useQuery<Meta>({ queryKey: ['meta'], queryFn: api.meta, staleTime: 5 * 60_000 })
  const available = meta.data?.media.find((entry) => entry.key === media)
  const enabled = available?.available ?? false

  const summary = useQuery<Summary>({
    queryKey: ['summary', media],
    queryFn: () => api.summary(media),
    enabled,
  })

  const cards = useQuery<CardsResponse>({
    queryKey: [
      'cards',
      lang,
      gridSearch,
      grid.sort,
      grid.order,
      grid.sort2,
      grid.order2,
      grid.withPoster,
      grid.withOverview,
      gridPage,
      grid.pageSize,
    ],
    queryFn: () =>
      api.cards({
        lang,
        search: gridSearch,
        sort: grid.sort,
        order: grid.order,
        sort2: grid.sort2 || undefined,
        order2: grid.order2,
        withPoster: grid.withPoster || undefined,
        withOverview: grid.withOverview || undefined,
        page: gridPage,
        pageSize: grid.pageSize,
      }),
    enabled: enabled && view === 'cards' && media === 'tv',
    placeholderData: keepPreviousData,
  })

  const items = useQuery<ItemsResponse>({
    queryKey: [
      'items',
      media,
      lang,
      filters.status,
      tableSearch,
      filters.minPopularity,
      filters.sort,
      filters.order,
      tablePage,
      filters.pageSize,
    ],
    queryFn: () =>
      api.items({
        media,
        lang,
        status: filters.status,
        search: tableSearch,
        minPopularity: filters.minPopularity,
        sort: filters.sort,
        order: filters.order,
        page: tablePage,
        pageSize: filters.pageSize,
      }),
    enabled: enabled && view === 'table',
    // La page précédente reste affichée pendant le chargement de la suivante :
    // sans ça, changer de langue fait clignoter tout le tableau.
    placeholderData: keepPreviousData,
  })

  // Toute expiration de session pendant la consultation ramène à la connexion.
  const errors = [meta.error, summary.error, cards.error, items.error]
  useEffect(() => {
    if (errors.some((error) => error instanceof ApiError && error.status === 401)) onSignedOut()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta.error, summary.error, cards.error, items.error])

  // Tout changement de cadrage renvoie en page 1 : rester en page 40 après
  // avoir filtré sur douze résultats afficherait une vue vide.
  useEffect(() => setTablePage(1), [
    media,
    lang,
    filters.status,
    tableSearch,
    filters.minPopularity,
    filters.sort,
    filters.order,
    filters.pageSize,
  ])
  useEffect(() => setGridPage(1), [
    lang,
    gridSearch,
    grid.sort,
    grid.order,
    grid.sort2,
    grid.order2,
    grid.withPoster,
    grid.withOverview,
    grid.pageSize,
  ])

  const languages = meta.data?.languages ?? []
  const langLabel = useMemo(
    () => languages.find((entry) => entry.code === lang)?.label ?? lang,
    [languages, lang],
  )

  const signOut = useMutation({ mutationFn: api.logout, onSuccess: onSignedOut })

  /**
   * Le rafraîchissement, en un seul geste.
   *
   * Il recalcule d'abord `admin.tv_card` côté serveur — le même
   * `refresh materialized view` que `fiv-admin catalog refresh`, appelé par la
   * même fonction — puis relit tout l'affichage. Il y avait auparavant deux
   * boutons d'aspect voisin, l'un qui relisait, l'autre qui recalculait :
   * personne ne pouvait deviner lequel faisait quoi, et cliquer sur le mauvais
   * ne produisait aucun effet visible.
   *
   * Le front n'exécute évidemment pas `docker compose` : il n'a pas à savoir
   * qu'il tourne dans un conteneur, et lui donner la main sur le démon Docker
   * reviendrait à lui donner la machine. Les deux chemins — bouton et ligne de
   * commande — arrivent au même SQL par des portes différentes.
   */
  const refresh = useMutation({
    mutationFn: api.refreshCatalog,
    onSuccess: (projection) => {
      void client.invalidateQueries({ queryKey: ['summary'] })
      void client.invalidateQueries({ queryKey: ['items'] })
      void client.invalidateQueries({ queryKey: ['cards'] })
      notifications.show({
        color: 'teal',
        title: 'Projection recalculée',
        message: `${formatNumber(projection.projected)} vignette(s) disponibles.`,
      })
    },
    onError: (error: Error) =>
      notifications.show({
        color: 'red',
        title: 'Échec du rafraîchissement',
        message: error.message,
      }),
  })

  return (
    <AppShell header={{ height: 64 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Title order={4} visibleFrom="sm">
              Fivorites
            </Title>
            {meta.data && (
              <SegmentedControl
                size="xs"
                value={media}
                onChange={setMedia}
                data={meta.data.media.map((entry) => ({ value: entry.key, label: entry.label }))}
              />
            )}
          </Group>

          <Group gap="xs" wrap="nowrap">
            <LanguagePicker
              languages={languages}
              value={lang}
              onChange={setLang}
              summary={summary.data}
            />
            <Tooltip label="Recalculer les vignettes et tout relire" multiline w={220}>
              <ActionIcon
                variant="default"
                size="lg"
                onClick={() => refresh.mutate()}
                loading={
                  refresh.isPending || items.isFetching || summary.isFetching || cards.isFetching
                }
                aria-label="Rafraîchir"
              >
                <IconRefresh size={18} />
              </ActionIcon>
            </Tooltip>
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <Button variant="default" size="xs" leftSection={<IconUser size={16} />}>
                  {account.displayName ?? account.username}
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{account.username}</Menu.Label>
                <Menu.Item
                  color="red"
                  leftSection={<IconLogout size={16} />}
                  onClick={() => signOut.mutate()}
                >
                  Se déconnecter
                </Menu.Item>
                <Menu.Divider />
                {/* La version du bundle qui s'exécute, pas celle que le serveur
                    croit avoir déployé. Quand les deux diffèrent, c'est
                    justement ce qu'on cherche à savoir. */}
                <Menu.Label>front {__APP_VERSION__}</Menu.Label>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        {available && !available.available ? (
          <Alert
            color="yellow"
            variant="light"
            icon={<IconAlertTriangle size={18} />}
            title={`${available.label} : rien à afficher`}
          >
            {available.reason}
          </Alert>
        ) : (
          <Tabs value={view} onChange={(next) => next && setView(next as 'cards' | 'table')}>
            <Tabs.List mb="md">
              <Tabs.Tab value="cards">Catalogue collecté</Tabs.Tab>
              <Tabs.Tab value="table">Avancement</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="cards">
              <SeriesGrid
                data={cards.data}
                loading={cards.isLoading}
                state={grid}
                onState={setGrid}
                languages={languages}
                lang={lang}
                page={gridPage}
                onPage={setGridPage}
                onOpen={setModalId}
                onRefreshProjection={() => refresh.mutate()}
                refreshing={refresh.isPending}
              />
            </Tabs.Panel>

            <Tabs.Panel value="table">
              <Stack gap="lg">
                <SummaryCards summary={summary.data} lang={lang} langLabel={langLabel} />

                <LanguageCoverage
                  languages={languages}
                  summary={summary.data}
                  selected={lang}
                  onSelect={setLang}
                />

                <Filters
                  value={filters}
                  onChange={setFilters}
                  langLabel={langLabel}
                  loading={items.isFetching}
                />

                {items.error && !(items.error instanceof ApiError && items.error.status === 401) && (
                  <Alert color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
                    {(items.error as Error).message}
                  </Alert>
                )}

                {items.data?.truncatedToFetched && (
                  <Alert color="blue" variant="light">
                    Le tri par dernière collecte ne porte que sur ce qui a déjà été regardé :{' '}
                    <Badge variant="light">{formatNumber(items.data.total)}</Badge> œuvre(s) sur les{' '}
                    {formatNumber(summary.data?.catalog.total ?? 0)} du catalogue.
                  </Alert>
                )}

                <AcquisitionTable
                  data={items.data}
                  loading={items.isLoading}
                  lang={lang}
                  languages={languages}
                  page={tablePage}
                  onPage={setTablePage}
                  onOpen={setDrawerId}
                  sort={filters.sort}
                  order={filters.order}
                  onSort={(sort, order) => setFilters((current) => ({ ...current, sort, order }))}
                />

                <Text size="xs" c="dimmed">
                  Les chiffres d'en-tête sont mis en cache une minute côté serveur : ils balaient
                  tout le brut. Le tableau, lui, est toujours à jour.
                </Text>
              </Stack>
            </Tabs.Panel>
          </Tabs>
        )}
      </AppShell.Main>

      <SeriesModal
        id={modalId}
        lang={lang}
        languages={languages}
        onClose={() => setModalId(null)}
      />

      <DetailDrawer
        media={media}
        id={drawerId}
        lang={lang}
        languages={languages}
        onClose={() => setDrawerId(null)}
      />
    </AppShell>
  )
}
