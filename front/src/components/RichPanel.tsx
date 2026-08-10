import {
  Alert,
  Anchor,
  Badge,
  Card,
  Center,
  Group,
  Image,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core'
import { IconAlertTriangle, IconExternalLink, IconInfoCircle } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api'
import { formatDate, formatNumber } from '../display'
import type { RichEntry, RichFacts, RichSources } from '../types'

/**
 * Ce que les sources tierces apportent, source par source.
 *
 * Le groupement suit la question qu'on se pose devant une fiche : « qu'apporte
 * Wikipédia ? », pas « qu'y a-t-il en français ? ». D'où une carte par source,
 * et à l'intérieur une ligne par langue — Wikipédia en porte cinq, Wikidata et
 * TVmaze une seule, leur contenu n'étant pas linguistique.
 *
 * Les faits affichés sont **canoniques** : `normalize.py`, côté sourcing, leur
 * impose les mêmes clés quelle que soit la source. C'est ce qui permet de les
 * rendre ici sans savoir d'où ils viennent, et c'est pourquoi ce composant ne
 * contient aucune branche « si Wikidata alors… ».
 *
 * Chargé à l'ouverture de l'onglet, jamais avec la fiche : la plupart des
 * séries n'ont encore aucun enrichissement, et le peu qui en ont portent des
 * articles de cent kilooctets.
 */

/** Le nom d'affichage des sources. Une source inconnue s'affiche telle quelle
 *  plutôt que d'être masquée : le jour où le sourcing en ajoute une, elle
 *  apparaît d'elle-même, même sans passer ici. */
const NOMS: Record<string, string> = {
  wikipedia: 'Wikipédia',
  wikidata: 'Wikidata',
  tvmaze: 'TVmaze',
  imdb: 'IMDb',
}

const STATUTS: Record<string, string> = {
  en_cours: 'en cours',
  terminee: 'terminée',
  annulee: 'annulée',
}

export function RichPanel({ id }: { id: number }) {
  const rich = useQuery<RichSources>({
    queryKey: ['rich', id],
    queryFn: () => api.rich(id),
  })

  if (rich.isLoading) {
    return (
      <Center p="xl">
        <Loader size="sm" />
      </Center>
    )
  }

  if (rich.error) {
    return (
      <Alert color="yellow" variant="light" icon={<IconAlertTriangle size={18} />}>
        {(rich.error as Error).message}
      </Alert>
    )
  }

  const data = rich.data
  if (!data || data.sources.length === 0) {
    return (
      <Stack gap="sm">
        <Alert color="gray" variant="light" icon={<IconInfoCircle size={18} />}>
          Aucun enrichissement pour cette série. Ce n'est pas une anomalie :
          l'enrichissement (Wikipédia, Wikidata, TVmaze) passe après la collecte TMDB et ne couvre
          pas encore tout le catalogue.
        </Alert>
        {data?.oeuvre && <Identite oeuvre={data.oeuvre} />}
      </Stack>
    )
  }

  return (
    <Stack gap="md">
      {data.oeuvre && <Identite oeuvre={data.oeuvre} />}

      {data.sources.map((groupe) => (
        <Card key={groupe.source} withBorder padding="md" radius="md">
          <Group justify="space-between" mb="sm" wrap="nowrap">
            <Title order={5}>{NOMS[groupe.source] ?? groupe.source}</Title>
            <Group gap="xs">
              <Badge variant="light">
                {groupe.entries.length} ligne{groupe.entries.length > 1 ? 's' : ''}
              </Badge>
              {groupe.chars > 0 && (
                <Badge variant="light" color="grape">
                  {formatNumber(groupe.chars)} caractères
                </Badge>
              )}
              {groupe.media > 0 && (
                <Badge variant="light" color="teal">
                  {groupe.media} visuel{groupe.media > 1 ? 's' : ''}
                </Badge>
              )}
            </Group>
          </Group>

          <Stack gap="lg">
            {groupe.entries.map((entree) => (
              <Entree key={`${entree.lang}-${entree.sourceId}`} entree={entree} />
            ))}
          </Stack>
        </Card>
      ))}
    </Stack>
  )
}

/** Les identifiants externes du pivot. Ils ne viennent d'aucune source en
 *  particulier : c'est par eux que le raccordement a été fait, et les voir
 *  explique pourquoi telle source a répondu et telle autre non. */
function Identite({ oeuvre }: { oeuvre: NonNullable<RichSources['oeuvre']> }) {
  const liens = [
    oeuvre.wikidataQid && {
      label: oeuvre.wikidataQid,
      href: `https://www.wikidata.org/wiki/${oeuvre.wikidataQid}`,
    },
    oeuvre.imdbId && {
      label: oeuvre.imdbId,
      href: `https://www.imdb.com/title/${oeuvre.imdbId}/`,
    },
    oeuvre.tvmazeId && {
      label: `TVmaze ${oeuvre.tvmazeId}`,
      href: `https://www.tvmaze.com/shows/${oeuvre.tvmazeId}`,
    },
  ].filter(Boolean) as { label: string; href: string }[]

  return (
    <Group gap="xs" align="center">
      <Text size="xs" c="dimmed">
        Raccordée à
      </Text>
      {liens.length === 0 ? (
        <Text size="xs" c="dimmed">
          aucun identifiant externe
        </Text>
      ) : (
        liens.map((lien) => (
          <Anchor key={lien.href} href={lien.href} target="_blank" rel="noreferrer" size="xs">
            {lien.label} <IconExternalLink size={11} style={{ verticalAlign: 'middle' }} />
          </Anchor>
        ))
      )}
    </Group>
  )
}

function Entree({ entree }: { entree: RichEntry }) {
  return (
    <Stack gap={6}>
      <Group gap="xs" wrap="nowrap">
        {entree.lang && (
          <Badge size="sm" variant="filled">
            {entree.lang.toUpperCase()}
          </Badge>
        )}
        {entree.url ? (
          <Anchor href={entree.url} target="_blank" rel="noreferrer" size="sm" lineClamp={1}>
            {entree.sourceId} <IconExternalLink size={12} style={{ verticalAlign: 'middle' }} />
          </Anchor>
        ) : (
          <Text size="sm">{entree.sourceId}</Text>
        )}
        <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          {entree.contentChars > 0 && `${formatNumber(entree.contentChars)} car. · `}
          {entree.resolvedBy && `par ${entree.resolvedBy} · `}
          {formatDate(entree.fetchedAt)}
        </Text>
      </Group>

      <Faits facts={entree.facts} />

      {entree.extract && (
        <Text size="sm" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>
          {entree.extract}
          {/* Le texte complet n'est pas rapatrié : un article pèse des
              centaines de kilooctets et se lit chez la source. */}
          {entree.truncated && ' […]'}
        </Text>
      )}

      {entree.media.length > 0 && (
        <SimpleGrid cols={{ base: 3, sm: 6 }} spacing="xs">
          {entree.media.map((visuel, index) => (
            <Image
              key={visuel.url ?? index}
              src={visuel.url}
              alt={visuel.type ?? ''}
              h={90}
              fit="contain"
            />
          ))}
        </SimpleGrid>
      )}
    </Stack>
  )
}

/** Les faits canoniques, dans l'ordre du schéma. Une clé absente ne s'affiche
 *  pas — le sourcing n'invente rien, l'admin n'invente pas non plus un « — »
 *  qui laisserait croire à une valeur vide plutôt qu'à une absence. */
function Faits({ facts }: { facts: RichFacts }) {
  const lignes: [string, string][] = []
  const ajouter = (label: string, valeur: string | undefined | null) => {
    if (valeur) lignes.push([label, valeur])
  }

  ajouter('Titre', facts.titre)
  ajouter('Autres titres', facts.titres_alternatifs?.join(' · '))
  ajouter('Année', facts.annee ? String(facts.annee) : undefined)
  ajouter('Statut', facts.statut && (STATUTS[facts.statut] ?? facts.statut))
  ajouter('Pays', facts.pays?.join(', '))
  ajouter('Langues', facts.langues?.join(', '))
  ajouter('Diffuseur', facts.diffuseur)
  ajouter(
    'Lieux',
    facts.lieux?.map((lieu) => `${lieu.nom} (${lieu.type})`).join(' · '),
  )
  ajouter(
    'Calendrier',
    [facts.calendrier?.jours?.join(', '), facts.calendrier?.heure].filter(Boolean).join(' à '),
  )
  if (facts.episodes?.total) {
    const detail = [
      `${facts.episodes.total} épisode(s)`,
      facts.episodes.dates && `${facts.episodes.dates} daté(s)`,
      facts.episodes.resumes && `${facts.episodes.resumes} résumé(s)`,
    ].filter(Boolean)
    ajouter('Épisodes', detail.join(' · '))
  }

  if (lignes.length === 0) return null

  return (
    <Group gap="xs" wrap="wrap">
      {lignes.map(([label, valeur]) => (
        <Badge key={label} variant="outline" color="gray" size="sm" tt="none">
          <Text span size="xs" c="dimmed">
            {label} :
          </Text>{' '}
          {valeur}
        </Badge>
      ))}
    </Group>
  )
}
