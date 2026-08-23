import { Badge, Button, Card, Group, Image, Progress, Stack, Text, Tooltip } from '@mantine/core'
import { IconScale, IconSchool, IconStar } from '@tabler/icons-react'

import { tmdbImage } from '../api'
import { POSTER_FALLBACK, formatPercent } from '../display'
import type { Card as CardData, Language } from '../types'
import { AxisVector } from './AxisVector'

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
  media,
  onOpen,
  onTraining,
}: {
  card: CardData
  languages: Language[]
  lang: string
  /** L'univers affiché — décide du libellé du badge de popularité : la
   *  notoriété Wikipédia d'un livre n'est pas la popularité TMDB. */
  media: string
  onOpen: () => void
  /** Ouvre l'atelier d'entraînement de la notation sur cette série. */
  onTraining: (phase: 1 | 2) => void
}) {
  const poster = tmdbImage(card.posterPath, 'w185')
  // Même règle que la fiche (`SeriesModal`) : seule une série a des saisons.
  const aDesSaisons = media === 'tv'
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

            {/* Deux nombres qu'on confond volontiers, et qui n'ont rien à voir.
                La popularité est un critère de tri : ne pas l'afficher rendait
                ce tri invérifiable, et l'étoile — la note des votants — servait
                de substitut trompeur. Les deux sont là, nommés. */}
            <Group gap={8} wrap="nowrap" c="dimmed">
              <Tooltip
                label={
                  media === 'book'
                    ? 'Notoriété — le nombre de Wikipédias qui portent l’œuvre, le critère de tri'
                    : 'Popularité TMDB — le critère de tri'
                }
              >
                <Text size="xs" ff="monospace">
                  {card.popularity === null ? 'pop. —' : `pop. ${card.popularity.toFixed(1)}`}
                </Text>
              </Tooltip>
              {card.voteAverage ? (
                <Tooltip label={`Note des votants : ${card.voteAverage.toFixed(1)} sur 10`}>
                  <Group gap={2} wrap="nowrap">
                    <IconStar size={13} />
                    <Text size="xs">{card.voteAverage.toFixed(1)}</Text>
                  </Group>
                </Tooltip>
              ) : null}
            </Group>
          </Group>

          <Group gap={6} wrap="wrap">
            <Badge size="sm" variant="light">
              {card.year ?? 'année inconnue'}
            </Badge>
            {/* Les saisons n'existent que pour les séries. Le badge était
                inconditionnel, et affichait donc « ? saisons » sur un livre
                comme sur un film — une information vide là où il n'y a rien
                à compter. Pour une série, le « ? » reste : là, il dit
                vraiment « on ne sait pas encore ». */}
            {aDesSaisons && (
              <Badge size="sm" variant="light" color="grape">
                {card.seasons ?? '?'} saison{(card.seasons ?? 0) > 1 ? 's' : ''}
              </Badge>
            )}
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

          {/* Le vecteur de goût — absent tant que rien n'est noté, donc pas de
              ligne ni d'espace réservé sur les cartes qui ne l'ont pas encore. */}
          <AxisVector scores={card.axisScores} internal={card.internalScores} size="sm" />

          <Text size="xs" c="dimmed" lineClamp={3} dir="auto">
            {card.overview || 'Pas de synopsis dans le brut collecté.'}
          </Text>

          {/* L'atelier de notation. `stopPropagation` : ces boutons vivent sur
              une carte entièrement cliquable, et ouvrir la fiche par-dessus la
              page d'entraînement serait le contraire de ce qu'on a demandé. */}
          <Group gap={6}>
            <Tooltip label="Phase 1 — stabiliser le barème : OpenAI note, le contre-juge contredit">
              <Button
                size="compact-xs"
                variant="default"
                leftSection={<IconSchool size={13} />}
                onClick={(event) => {
                  event.stopPropagation()
                  onTraining(1)
                }}
              >
                Training 1
              </Button>
            </Tooltip>
            <Tooltip label="Phase 2 — régler les poids : la régression interne face au LLM">
              <Button
                size="compact-xs"
                variant="default"
                leftSection={<IconScale size={13} />}
                onClick={(event) => {
                  event.stopPropagation()
                  onTraining(2)
                }}
              >
                Training 2
              </Button>
            </Tooltip>
          </Group>

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
