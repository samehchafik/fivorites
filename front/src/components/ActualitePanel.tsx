import { Badge, Center, Group, Loader, Stack, Text, Timeline } from '@mantine/core'
import { IconExternalLink, IconNews } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api'
import { formatDate } from '../display'

/**
 * L'actualité de l'œuvre : les événements datés que la dérivation lui a liés.
 *
 * Deux provenances, distinguées à l'écran parce qu'elles n'ont pas la même
 * fiabilité : les diffs internes (« tmdb ») sont des faits — c'est notre
 * propre pivot, la liaison est certaine — tandis qu'un item de presse est lié
 * par un matching de titres, et son score accompagne la ligne.
 *
 * Chargé à l'ouverture de l'onglet, jamais avec la fiche : la plupart des
 * œuvres n'ont pas d'actualité, et c'est l'état normal du catalogue.
 */

/** Le vocabulaire fermé de `sourcing.actualite`, en clair. Un type inconnu
 *  s'affiche tel quel : le jour où le sourcing en ajoute un, il apparaît de
 *  lui-même plutôt que d'être masqué. */
const TYPES: Record<string, string> = {
  saison_annoncee: 'Nouvelle saison',
  date_diffusion: 'Diffusion',
  diffusion_terminee: 'Fin de diffusion',
  annulation: 'Annulation',
  sortie: 'Sortie',
  parution: 'Parution',
  critique: 'Critique',
  adaptation: 'Adaptation',
  prix: 'Prix',
  deces: 'Décès',
  autre: 'Actualité',
}

const COULEURS: Record<string, string> = {
  saison_annoncee: 'teal',
  date_diffusion: 'blue',
  diffusion_terminee: 'gray',
  annulation: 'red',
  sortie: 'teal',
  prix: 'yellow',
}

export function ActualitePanel({ id, media }: { id: number; media: string }) {
  const actualite = useQuery({
    queryKey: ['actualite', id, media],
    queryFn: () => api.actualite(id, media),
  })

  if (actualite.isLoading) {
    return (
      <Center py="xl">
        <Loader size="sm" />
      </Center>
    )
  }
  const evenements = actualite.data?.evenements ?? []
  if (evenements.length === 0) {
    return (
      <Center py="xl">
        <Stack gap={4} align="center">
          <IconNews size={28} opacity={0.4} />
          <Text c="dimmed" size="sm">
            Aucune actualité pour cette œuvre — la dérivation n'a rien relevé.
          </Text>
        </Stack>
      </Center>
    )
  }

  return (
    <Timeline active={-1} bulletSize={18} lineWidth={2}>
      {evenements.map((evt, n) => (
        <Timeline.Item
          key={n}
          title={
            <Group gap="xs">
              <Badge size="sm" variant="light" color={COULEURS[evt.type] ?? 'gray'}>
                {TYPES[evt.type] ?? evt.type}
              </Badge>
              <Text size="sm" fw={500}>
                {evt.titre}
              </Text>
            </Group>
          }
        >
          <Text size="xs" c="dimmed">
            {formatDate(evt.survenuLe)} · {evt.editeur}
            {evt.confiance !== null && ` · liaison ${Math.round(evt.confiance * 100)} %`}
            {evt.url && (
              <>
                {' · '}
                <a href={evt.url} target="_blank" rel="noreferrer">
                  source <IconExternalLink size={10} />
                </a>
              </>
            )}
          </Text>
        </Timeline.Item>
      ))}
    </Timeline>
  )
}
