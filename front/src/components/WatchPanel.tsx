import { Alert, Anchor, Badge, Group, Image, Stack, Text, Tooltip } from '@mantine/core'
import { IconExternalLink, IconInfoCircle } from '@tabler/icons-react'

import { tmdbImage } from '../api'
import type { Language, Watch } from '../types'

/**
 * Où regarder la série — par pays, jamais « en général ».
 *
 * TMDB indexe cette donnée par territoire, parce que c'est ainsi que les
 * droits se vendent : la même série est sur Netflix en France, sur Shahid en
 * Arabie saoudite, et nulle part en Turquie. Le pays vient de la région du
 * sélecteur de langue (`fr-FR` → France), ce qui évite un second sélecteur qui
 * dirait presque toujours la même chose que le premier.
 */
export function WatchPanel({ watch, languages }: { watch: Watch; languages: Language[] }) {
  const label = languages.find((entry) => entry.code.endsWith(`-${watch.country}`))
  const pays = label ? `${label.flag} ${watch.country}` : (watch.country ?? '—')

  if (watch.offers.length === 0) {
    return (
      <Stack gap="sm">
        {/* Trois situations très différentes, et les confondre fait chercher au
            mauvais endroit : pas de donnée du tout, une donnée qui existe mais
            pas pour ce pays, ou une langue sans région. */}
        <Alert color="gray" variant="light" icon={<IconInfoCircle size={18} />}>
          {watch.country === null ? (
            <Text size="sm">
              La langue choisie ne désigne aucun pays, et la disponibilité en streaming s'établit
              par territoire.
            </Text>
          ) : watch.countries.length === 0 ? (
            <Text size="sm">
              Aucune donnée de disponibilité dans le brut collecté pour cette série.
            </Text>
          ) : (
            <Stack gap={6}>
              <Text size="sm">
                Aucune plateforme en {pays} — mais la série est disponible ailleurs :
              </Text>
              <Group gap={4}>
                {watch.countries.map((code) => (
                  <Badge key={code} size="sm" variant="outline">
                    {code}
                  </Badge>
                ))}
              </Group>
              <Text size="xs" c="dimmed">
                Changer de langue dans l'en-tête change de pays.
              </Text>
            </Stack>
          )}
        </Alert>
        <Attribution link={watch.link} />
      </Stack>
    )
  }

  return (
    <Stack gap="lg">
      <Text size="sm" c="dimmed">
        Disponibilité en {pays}. Changer de langue dans l'en-tête change de pays.
      </Text>

      {watch.offers.map((offer) => (
        <Stack key={offer.kind} gap="xs">
          <Text size="sm" fw={600}>
            {offer.label}
          </Text>
          <Group gap="md">
            {offer.providers.map((provider) => (
              <Tooltip key={provider.id ?? provider.name} label={provider.name ?? ''}>
                <Group gap={8} wrap="nowrap">
                  {provider.logoPath && (
                    <Image
                      src={tmdbImage(provider.logoPath, 'w92')}
                      w={40}
                      h={40}
                      radius="sm"
                      alt=""
                      loading="lazy"
                    />
                  )}
                  <Text size="sm">{provider.name}</Text>
                </Group>
              </Tooltip>
            ))}
          </Group>
        </Stack>
      ))}

      <Attribution link={watch.link} />
    </Stack>
  )
}

/** TMDB tient cette donnée de JustWatch et impose de le citer. Le lien mène à
 *  la page qui fait autorité — la seule qui dira si l'offre a changé depuis la
 *  collecte, car ces droits bougent souvent. */
function Attribution({ link }: { link: string | null }) {
  return (
    <Group gap="xs">
      <Text size="xs" c="dimmed">
        Disponibilité fournie par JustWatch, via TMDB — susceptible d'avoir changé depuis la
        collecte.
      </Text>
      {link && (
        <Anchor href={link} target="_blank" rel="noreferrer noopener" size="xs">
          <Group gap={4}>
            vérifier <IconExternalLink size={12} />
          </Group>
        </Anchor>
      )}
    </Group>
  )
}
