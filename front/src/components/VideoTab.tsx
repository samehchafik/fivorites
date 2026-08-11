import { useState } from 'react'
import { AspectRatio, Badge, Card, Group, SimpleGrid, Stack, Text } from '@mantine/core'
import { IconBrandYoutube, IconPlayerPlay } from '@tabler/icons-react'

import type { Video } from '../types'

/**
 * Les vidéos d'une série : une lecture, une liste, et rien d'autre.
 *
 * Le lecteur n'est monté qu'au clic. Charger une iframe YouTube coûte plusieurs
 * centaines de kilo-octets et pose des cookies chez un tiers : tant que
 * personne n'a demandé à voir la bande-annonce, l'admin ne doit rien lui
 * réclamer. Les vignettes viennent de `img.youtube.com`, qui sert une image
 * statique sans script ni cookie.
 */
function miniature(v: Video): string | null {
  return v.site === 'YouTube' ? `https://img.youtube.com/vi/${v.key}/hqdefault.jpg` : null
}

function lien(v: Video): string | null {
  if (v.site === 'YouTube') return `https://www.youtube.com/watch?v=${v.key}`
  if (v.site === 'Vimeo') return `https://vimeo.com/${v.key}`
  return null
}

function integration(v: Video): string | null {
  if (v.site === 'YouTube') return `https://www.youtube-nocookie.com/embed/${v.key}?autoplay=1`
  if (v.site === 'Vimeo') return `https://player.vimeo.com/video/${v.key}?autoplay=1`
  return null
}

/** Les types tels que TMDB les nomme — traduits, le reste passe tel quel. */
const TYPES: Record<string, string> = {
  Trailer: 'Bande-annonce',
  Teaser: 'Teaser',
  Clip: 'Extrait',
  Featurette: 'Making-of',
  'Behind the Scenes': 'Coulisses',
  'Opening Credits': 'Générique',
  Bloopers: 'Bêtisier',
}

export function VideoTab({ videos }: { videos: Video[] }) {
  const [ouverte, setOuverte] = useState<Video | null>(null)

  if (videos.length === 0) {
    return (
      <Stack gap="xs">
        <Text c="dimmed">Aucune vidéo.</Text>
        <Text size="sm" c="dimmed">
          Les vidéos vivent dans le brut TMDB depuis la collecte, mais une passe séparée les rend
          lisibles. Si cette série vient d'être collectée, lancer&nbsp;
          <Text span ff="monospace" size="sm">
            fiv-sourcing videos
          </Text>
          .
        </Text>
      </Stack>
    )
  }

  const cadre = ouverte && integration(ouverte)

  return (
    <Stack gap="lg">
      {cadre && (
        <Stack gap="xs">
          <AspectRatio ratio={16 / 9}>
            <iframe
              src={cadre}
              title={ouverte?.name ?? 'Vidéo'}
              style={{ border: 0, borderRadius: 8 }}
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; picture-in-picture"
              allowFullScreen
            />
          </AspectRatio>
          <Text size="sm" fw={500}>
            {ouverte?.name}
          </Text>
        </Stack>
      )}

      <SimpleGrid cols={{ base: 2, sm: 3, md: 4 }} spacing="md">
        {videos.map((v) => {
          const vignette = miniature(v)
          const url = lien(v)
          const active = ouverte?.key === v.key
          return (
            <Card
              key={`${v.site}-${v.key}`}
              padding="xs"
              withBorder
              style={{
                cursor: integration(v) ? 'pointer' : 'default',
                outline: active ? '2px solid var(--mantine-color-blue-5)' : undefined,
              }}
              onClick={() => (integration(v) ? setOuverte(active ? null : v) : undefined)}
            >
              <Card.Section>
                <AspectRatio ratio={16 / 9}>
                  {vignette ? (
                    <img
                      src={vignette}
                      alt=""
                      loading="lazy"
                      style={{ objectFit: 'cover', width: '100%', height: '100%' }}
                    />
                  ) : (
                    <Group justify="center" bg="var(--mantine-color-default-border)">
                      <IconPlayerPlay size={24} />
                    </Group>
                  )}
                </AspectRatio>
              </Card.Section>

              <Stack gap={4} mt="xs">
                <Text size="sm" lineClamp={2} title={v.name ?? undefined}>
                  {v.name ?? `${v.site} · ${v.key}`}
                </Text>
                <Group gap={4}>
                  <Badge size="xs" variant="light" color={v.official ? 'teal' : 'gray'}>
                    {TYPES[v.type] ?? v.type}
                  </Badge>
                  {v.lang && (
                    <Badge size="xs" variant="default">
                      {v.lang}
                    </Badge>
                  )}
                  {v.season !== null && (
                    <Badge size="xs" variant="default">
                      S{v.season}
                    </Badge>
                  )}
                  {url && (
                    <Text
                      component="a"
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      size="xs"
                      c="dimmed"
                      onClick={(e) => e.stopPropagation()}
                      title={`Ouvrir sur ${v.site}`}
                    >
                      <IconBrandYoutube size={14} />
                    </Text>
                  )}
                </Group>
              </Stack>
            </Card>
          )
        })}
      </SimpleGrid>
    </Stack>
  )
}
