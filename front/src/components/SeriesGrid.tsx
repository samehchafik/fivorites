import {
  Alert,
  Button,
  Center,
  Checkbox,
  Group,
  MultiSelect,
  Pagination,
  Paper,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core'
import { IconAlertTriangle, IconRefresh, IconSearch } from '@tabler/icons-react'

import { formatDate, formatNumber } from '../display'
import type { CardsResponse, GenreFacet, Language } from '../types'
import { SeriesCard } from './SeriesCard'

export const CARD_SORTS: { value: string; label: string }[] = [
  { value: 'air_date', label: 'Date de diffusion' },
  // Distinct du précédent, et c'est le seul qui rende un second critère
  // utile : deux séries partagent rarement le jour exact, très souvent
  // l'année.
  { value: 'air_year', label: 'Année de diffusion' },
  { value: 'name', label: 'Titre' },
  { value: 'popularity', label: 'Popularité' },
  // « Note » et non « note moyenne » : elle est pondérée par le nombre de
  // votants, sans quoi la tête de liste n'est faite que de séries notées 10 par
  // une personne. L'infobulle du sélecteur le dit — le classement n'est pas
  // exactement celui des étoiles affichées, et mieux vaut l'annoncer que le
  // laisser découvrir.
  { value: 'rating', label: 'Note' },
  { value: 'fetched', label: 'Dernière collecte' },
]

/** Le sens de tri se dit autrement selon ce qu'on trie : « du plus récent »
 *  n'a aucun sens pour un titre, ni « de A à Z » pour une date. */
function directionsFor(sort: string): { value: string; label: string }[] {
  if (sort === 'name') {
    return [
      { value: 'asc', label: 'de A à Z' },
      { value: 'desc', label: 'de Z à A' },
    ]
  }
  if (sort === 'air_year') {
    return [
      { value: 'desc', label: 'de la plus récente' },
      { value: 'asc', label: 'de la plus ancienne' },
    ]
  }
  if (sort === 'popularity') {
    return [
      { value: 'desc', label: 'des plus populaires' },
      { value: 'asc', label: 'des moins populaires' },
    ]
  }
  if (sort === 'rating') {
    return [
      { value: 'desc', label: 'des mieux notées' },
      { value: 'asc', label: 'des moins bien notées' },
    ]
  }
  return [
    { value: 'desc', label: 'du plus récent au plus ancien' },
    { value: 'asc', label: 'du plus ancien au plus récent' },
  ]
}

/** Le compte des résultats, rapporté au total dès qu'un filtre est actif.
 *
 *  Le rapport s'affiche même quand le filtre ne retire rien : « 1 240 / 1 240 »
 *  dit qu'il est en place et qu'il ne mord pas, ce qu'un nombre seul ne dit
 *  pas — on ne peut alors pas distinguer « le filtre est sans effet » de « le
 *  filtre n'est pas appliqué ». */
function Filtre({ data, actif }: { data: CardsResponse; actif: boolean }) {
  const total = data.projection.projected
  // Le dénominateur est le nombre de vignettes tous filtres retirés. Il n'a de
  // sens que s'il n'est pas inférieur : une projection rafraîchie entre deux
  // requêtes pourrait le rendre plus petit, et « 12 / 8 » ferait douter des
  // deux nombres plutôt que d'en éclairer un.
  if (!actif || !Number.isFinite(total) || total < data.total) {
    return <>{formatNumber(data.total)} série(s) collectée(s)</>
  }
  return (
    <Tooltip label={`${formatNumber(data.total)} correspondent aux filtres, sur ${formatNumber(total)} collectées`}>
      <span>
        <Text span fw={600}>
          {formatNumber(data.total)}
        </Text>
        {` / ${formatNumber(total)} série(s) collectée(s)`}
      </span>
    </Tooltip>
  )
}

const labelOf = (value: string) =>
  CARD_SORTS.find((entry) => entry.value === value)?.label ?? value

const directionLabel = (sort: string, order: string) =>
  directionsFor(sort).find((entry) => entry.value === order)?.label ?? order

export interface GridState {
  search: string
  sort: string
  order: 'asc' | 'desc'
  /** Chaîne vide = pas de second critère. */
  sort2: string
  order2: 'asc' | 'desc'
  /** Ne lister que ce qui a une affiche. */
  withPoster: boolean
  /** Ne lister que ce qui a un synopsis. */
  withOverview: boolean
  /** Genres retenus, en OU. Vide = tous. */
  genres: string[]
  pageSize: number
}

export function SeriesGrid({
  data,
  genres,
  loading,
  state,
  onState,
  languages,
  lang,
  page,
  onPage,
  onOpen,
  onTraining,
  onRefreshProjection,
  refreshing,
}: {
  data: CardsResponse | undefined
  genres: GenreFacet[]
  loading: boolean
  state: GridState
  onState: (next: GridState) => void
  languages: Language[]
  lang: string
  page: number
  onPage: (page: number) => void
  onOpen: (id: number) => void
  onTraining: (id: number, phase: 1 | 2) => void
  onRefreshProjection: () => void
  refreshing: boolean
}) {
  const pages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1
  const projection = data?.projection

  // Un filtre est « en place » dès qu'il peut retirer des lignes, qu'il en
  // retire ou non.
  const filtreActif =
    state.search.trim() !== '' ||
    state.withPoster ||
    state.withOverview ||
    state.genres.length > 0

  return (
    <Stack gap="md">
      <Paper withBorder radius="md" p="sm">
        <Group gap="sm" align="flex-end" wrap="wrap">
          <TextInput
            label="Recherche"
            placeholder="titre (toutes langues) ou id TMDB"
            leftSection={<IconSearch size={16} />}
            value={state.search}
            onChange={(event) => onState({ ...state, search: event.currentTarget.value })}
            w={280}
          />
          <Select
            label="Tri"
            // Dit à quoi on trie pendant qu'on trie, plutôt que de laisser
            // chercher pourquoi une série notée 9,5 passe derrière une 8,8.
            description={
              state.sort === 'rating' || state.sort2 === 'rating'
                ? 'note pondérée par le nombre de votants'
                : undefined
            }
            data={CARD_SORTS}
            value={state.sort}
            onChange={(next) => next && onState({ ...state, sort: next })}
            allowDeselect={false}
            w={200}
          />
          <Select
            label="Sens"
            data={directionsFor(state.sort)}
            value={state.order}
            onChange={(next) => next && onState({ ...state, order: next as 'asc' | 'desc' })}
            allowDeselect={false}
            w={230}
          />

          {/* Le départage. Sans lui, un lot de séries sorties le même jour
              tombe dans un ordre arbitraire qui peut changer d'une page à
              l'autre — la pagination fait alors réapparaître une série ou en
              saute une. Facultatif : « aucun » est la valeur de départ. */}
          <Select
            label="Puis par"
            description="à valeur égale"
            data={[
              { value: '', label: 'aucun' },
              ...CARD_SORTS.filter((entry) => entry.value !== state.sort),
            ]}
            value={state.sort2}
            onChange={(next) => onState({ ...state, sort2: next ?? '' })}
            allowDeselect={false}
            w={190}
          />

          {state.sort2 && (
            <Select
              label="Sens"
              data={directionsFor(state.sort2)}
              value={state.order2}
              onChange={(next) => next && onState({ ...state, order2: next as 'asc' | 'desc' })}
              allowDeselect={false}
              w={230}
            />
          )}
          <Select
            label="Par page"
            data={['12', '24', '48', '96']}
            value={String(state.pageSize)}
            onChange={(next) => next && onState({ ...state, pageSize: Number(next) })}
            allowDeselect={false}
            w={100}
          />

          {/* Les genres viennent d'une agrégation sur l'index : ce sont ceux
              que le catalogue porte VRAIMENT, avec leur compte, plutôt qu'une
              liste écrite en dur qui mentirait le jour où TMDB en ajoute un.
              Plusieurs genres cochés se lisent en OU — « comédie ou drame » —
              parce qu'un ET viderait la liste dès le deuxième, la plupart des
              œuvres n'en portant que deux ou trois. */}
          <MultiSelect
            label="Genres"
            placeholder={state.genres.length ? undefined : 'tous'}
            description={state.genres.length > 1 ? "l'un OU l'autre" : undefined}
            data={genres.map((genre) => ({
              value: genre.name,
              label: `${genre.name} (${formatNumber(genre.count)})`,
            }))}
            value={state.genres}
            onChange={(next) => onState({ ...state, genres: next })}
            searchable
            clearable
            // Au-delà, la barre de filtres se fait manger par les étiquettes ;
            // le compte prend le relais pour dire ce qui est coché.
            maxValues={6}
            w={260}
          />

          {/* Une vignette sans visuel n'est pas un défaut de la grille : TMDB
              n'a pas d'affiche pour tout le monde, et le fond de catalogue en
              est largement dépourvu. La case sert à regarder la partie
              présentable du catalogue sans changer ce qu'il contient. */}
          <Checkbox
            label="Avec affiche"
            checked={state.withPoster}
            onChange={(event) => onState({ ...state, withPoster: event.currentTarget.checked })}
            mb={6}
          />

          {/* Le synopsis est la matière de la notation : une série sans texte
              ne servira à rien au lot 5, si belle que soit son affiche. Les
              deux cases se combinent. */}
          <Checkbox
            label="Avec descriptif"
            checked={state.withOverview}
            onChange={(event) => onState({ ...state, withOverview: event.currentTarget.checked })}
            mb={6}
          />
        </Group>
      </Paper>

      {projection?.stale && (
        <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
          <Group justify="space-between" wrap="wrap" gap="sm">
            <Text size="sm">
              {formatNumber(projection.pending)} série(s) collectée(s) depuis le dernier calcul
              des vignettes.{' '}
              {/* Sans cette phrase, un compteur qui ne retombe jamais à zéro
                  ressemble à une panne. Il en est l'inverse : c'est la collecte
                  qui avance pendant qu'on regarde. */}
              <Text span c="dimmed">
                Tant qu'une collecte tourne, l'écart se recreuse aussitôt : c'est normal.
              </Text>
            </Text>
            {/* Le bouton est ici plutôt que dans la barre d'outils : c'est
                l'endroit où l'on apprend qu'il y a quelque chose à faire. Le
                même geste est disponible dans l'en-tête, à tout moment. */}
            <Button
              size="xs"
              variant="filled"
              color="orange"
              leftSection={<IconRefresh size={16} />}
              onClick={onRefreshProjection}
              loading={refreshing}
            >
              Les faire apparaître
            </Button>
          </Group>
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
              onTraining={(phase) => onTraining(card.id, phase)}
            />
          ))}
        </SimpleGrid>
      )}

      <Group justify="space-between">
        {/* Le tri appliqué, écrit. Deux sélecteurs plus haut disent déjà ce
            qu'ils valent, mais rien ne montrait le résultat de leur
            combinaison — et un tri qu'on croit avoir choisi sans l'avoir fait
            ressemble en tout point à un tri cassé. */}
        <Text size="sm" c="dimmed">
          {/* « 142 / 1 240 » dès qu'un filtre retire quelque chose. Le total
              seul ne dit pas si le filtre a mordu, ni sur quoi il mord : entre
              « 142 séries » et « 142 sur 1 240 », seul le second permet de
              juger si le catalogue est maigre ou si le filtre est sévère. */}
          {data ? <Filtre data={data} actif={filtreActif} /> : '—'}
          {' · tri : '}
          <Text span fw={600}>
            {labelOf(state.sort)}
          </Text>
          {` (${directionLabel(state.sort, state.order)})`}
          {state.sort2 ? (
            <>
              {', puis '}
              <Text span fw={600}>
                {labelOf(state.sort2)}
              </Text>
              {` (${directionLabel(state.sort2, state.order2)})`}
            </>
          ) : (
            ' · aucun départage'
          )}
          {projection?.lastAt ? ` · brut le plus récent ${formatDate(projection.lastAt)}` : ''}
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
