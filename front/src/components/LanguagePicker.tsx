import { Group, Select, Stack, Text } from '@mantine/core'
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
 * Le chiffre est un **nombre de séries** : celles qui ont au moins une partie
 * collectée dans cette langue. C'était un nombre de saisons, qui ne se compare
 * à rien — ni au catalogue, ni aux fiches collectées — et qu'on lisait
 * naturellement comme des séries. Deux fois trop grand, donc, pour la seule
 * question qu'on se pose ici : « combien d'œuvres ai-je dans cette langue ».
 *
 * La liste déroulée l'écrit en toutes lettres ; le champ fermé reste compact,
 * faute de place dans l'en-tête.
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
    const collected = statsOf(language.code)?.worksOk ?? 0
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
      {/* Pas de `Tooltip` autour de ce `Select`, et c'est un piège coûteux :
          Mantine clone l'enfant d'un Tooltip pour lui imposer sa référence, ce
          qui prend la place de celle dont la Combobox a besoin pour ancrer son
          menu — le déroulant ne s'ouvre alors plus au clic. Le défaut est
          invisible à un `.click()` synthétique, qui passe outre la gestion des
          événements de pointeur : il ne se voit qu'à la souris.
          L'explication du chiffre vit donc dans les options elles-mêmes, où
          elle est écrite en toutes lettres. */}
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
                {stats && stats.worksOk > 0
                  ? `${formatNumber(stats.worksOk)} série(s) collectée(s)`
                  : 'rien de collecté'}
              </Text>
            </Stack>
          )
        }}
      />
    </Group>
  )
}
