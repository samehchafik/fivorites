import { Group, Select, Text } from '@mantine/core'
import { IconLanguage } from '@tabler/icons-react'

import { formatNumber } from '../display'
import type { Language, Summary } from '../types'

/**
 * Le sélecteur de langue — la commande principale de cet écran.
 *
 * Chaque option porte le nombre de parties déjà collectées dans cette langue :
 * choisir une langue devient une décision informée, et une langue configurée
 * mais jamais collectée se voit sans avoir à la sélectionner pour le découvrir.
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
  const data = languages.map((language) => {
    const collected = summary?.byLang[language.code]?.partsOk ?? 0
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
      />
    </Group>
  )
}
