import { Group, Select, Stack, Text, Tooltip } from '@mantine/core'
import { IconLanguage } from '@tabler/icons-react'

import { formatNumber } from '../display'
import type { Language, Summary } from '../types'

/**
 * Le sélecteur de langue — la commande principale de cet écran.
 *
 * Chaque option porte ce qui est collecté dans cette langue, pour que le choix
 * soit informé : une langue configurée mais jamais collectée se voit sans avoir
 * à la sélectionner pour le découvrir.
 *
 * Le chiffre est **explicite dans la liste déroulée** — « 1 240 saisons ·
 * 310 séries ». Il ne l'était pas, et un nombre nu à côté d'un nom de langue
 * ne dit pas ce qu'il compte : on peut y lire des séries, des épisodes, un
 * pourcentage. Le champ fermé reste compact, la liste explique.
 */
export function LanguagePicker({
  languages,
  value,
  onChange,
  summary,
}: {
  languages: Language[]
  value: string
  onChange: (code: string) => void
  summary: Summary | undefined
}) {
  const statsOf = (code: string) => summary?.byLang[code]

  const data = languages.map((language) => {
    const collected = statsOf(language.code)?.partsOk ?? 0
    return {
      value: language.code,
      label: `${language.flag} ${language.label}${collected ? ` · ${formatNumber(collected)}` : ' · —'}`,
    }
  })

  return (
    <Group gap={6} wrap="nowrap">
      <Text size="sm" c="dimmed" visibleFrom="md">
        Langue
      </Text>
      <Tooltip label="Le nombre est celui des saisons collectées dans cette langue" withArrow>
        <Select
          aria-label="Langue affichée"
          leftSection={<IconLanguage size={16} />}
          data={data}
          value={value}
          onChange={(code) => code && onChange(code)}
          allowDeselect={false}
          checkIconPosition="right"
          w={230}
          size="sm"
          renderOption={({ option }) => {
            const language = languages.find((entry) => entry.code === option.value)
            const stats = statsOf(option.value)
            return (
              <Stack gap={0}>
                <Text size="sm">
                  {language?.flag} {language?.label}
                </Text>
                <Text size="xs" c="dimmed">
                  {stats && stats.partsOk > 0
                    ? `${formatNumber(stats.partsOk)} saison(s) · ${formatNumber(stats.worksOk)} série(s)`
                    : 'rien de collecté'}
                </Text>
              </Stack>
            )
          }}
        />
      </Tooltip>
    </Group>
  )
}
