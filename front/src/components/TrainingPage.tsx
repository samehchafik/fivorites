import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconArrowLeft, IconPlayerPlay, IconScale, IconSchool } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { ApiError, api } from '../api'
import type { AxisScore, Gaps, Phase1Result, Phase2Result, Rubric } from '../types'

/**
 * L'atelier d'entraînement de la notation. Deux phases, une même page.
 *
 * **Training 1 — stabiliser le barème.** Le prompt s'édite à droite, le
 * dossier se lit à gauche, et un clic envoie la même consigne à deux juges :
 * OpenAI note, Haiku contre-note. L'écart par axe est la seule mesure qui
 * compte : au-delà du bruit (~1 point), c'est le prompt qui est ambigu — on le
 * corrige et on rejoue. Quand une formulation tient, on la fige en nouvelle
 * version : les notes précédentes restent comparables entre elles.
 *
 * **Training 2 — régler les poids.** La régression interne prédit les axes
 * depuis l'embedding du dossier ; on la confronte à une note LLM. Divergence
 * forte → le bouton « Réentraîner » refait les poids sur tout l'historique ;
 * divergence au niveau du bruit → les poids tiennent, on continue.
 */
export function TrainingPage({
  id,
  phase,
  onBack,
}: {
  id: number
  phase: 1 | 2
  onBack: () => void
}) {
  const [tab, setTab] = useState<'1' | '2'>(phase === 2 ? '2' : '1')

  const dossier = useQuery({
    queryKey: ['training-dossier', id],
    queryFn: () => api.trainingDossier(id),
    retry: false,
  })
  const rubrics = useQuery({ queryKey: ['rubrics'], queryFn: api.rubrics })

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <Group gap="sm" wrap="nowrap">
          <Button variant="default" leftSection={<IconArrowLeft size={16} />} onClick={onBack}>
            Catalogue
          </Button>
          <Title order={4} lineClamp={1}>
            {dossier.data?.title ?? `Série ${id}`}
          </Title>
          <Badge variant="light">#{id}</Badge>
        </Group>
        {dossier.data && (
          <Text size="sm" c="dimmed">
            dossier {dossier.data.chars.toLocaleString('fr-FR')} caractères ·{' '}
            {dossier.data.sections.episodeCount} synopsis d'épisodes ·{' '}
            {dossier.data.sections.wikipediaChars > 0
              ? 'Wikipédia en'
              : 'pas de Wikipédia — enrichir aiderait'}
          </Text>
        )}
      </Group>

      {dossier.error instanceof ApiError && (
        <Alert color="red" variant="light">
          {dossier.error.message}
        </Alert>
      )}
      {dossier.data && !dossier.data.enough && (
        <Alert color="yellow" variant="light" title="Dossier trop maigre">
          {dossier.data.chars} caractères de matière anglaise : noter cette série produirait des
          nombres sans valeur. L'enrichir d'abord (`fiv-sourcing enrich --id {id}`).
        </Alert>
      )}

      <Tabs value={tab} onChange={(next) => next && setTab(next as '1' | '2')}>
        <Tabs.List mb="md">
          <Tabs.Tab value="1" leftSection={<IconSchool size={16} />}>
            Training 1 — le barème
          </Tabs.Tab>
          <Tabs.Tab value="2" leftSection={<IconScale size={16} />}>
            Training 2 — les poids
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="1">
          <Phase1
            id={id}
            dossierText={dossier.data?.text}
            rubrics={rubrics.data ?? []}
            loading={rubrics.isLoading || dossier.isLoading}
          />
        </Tabs.Panel>
        <Tabs.Panel value="2">
          <Phase2 id={id} rubrics={rubrics.data ?? []} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}

/** L'écart coloré : vert au niveau du bruit, rouge au-delà de l'ambiguïté. */
function GapBadge({ gap }: { gap: number | null | undefined }) {
  if (gap === null || gap === undefined) {
    return (
      <Badge variant="light" color="gray">
        —
      </Badge>
    )
  }
  const color = gap <= 1 ? 'teal' : gap <= 2 ? 'yellow' : 'red'
  return (
    <Badge variant="light" color={color}>
      {gap.toFixed(1)}
    </Badge>
  )
}

function ScoreCell({ entry }: { entry: AxisScore | undefined }) {
  if (!entry || entry.score === null || entry.score === undefined) {
    return (
      <Text size="sm" c="dimmed">
        null
      </Text>
    )
  }
  return (
    <Group gap={6} wrap="nowrap">
      <Text fw={600}>{entry.score}</Text>
      {entry.confidence !== null && entry.confidence !== undefined && (
        <Tooltip label="Confiance déclarée par le juge">
          <Text size="xs" c="dimmed">
            ±{entry.confidence.toFixed(2)}
          </Text>
        </Tooltip>
      )}
    </Group>
  )
}

function GapSummary({ gaps }: { gaps: Gaps }) {
  return (
    <Group gap="xs">
      <Text size="sm">Écart moyen :</Text>
      <GapBadge gap={gaps.mean} />
      <Text size="xs" c="dimmed">
        sur {gaps.scored} axe(s) notés des deux côtés · ≤ 1 : au niveau du bruit, le prompt tient ·
        &gt; 2 : le prompt est ambigu sur les axes rouges
      </Text>
    </Group>
  )
}

// ------------------------------------------------------------------ phase 1

function Phase1({
  id,
  dossierText,
  rubrics,
  loading,
}: {
  id: number
  dossierText: string | undefined
  rubrics: Rubric[]
  loading: boolean
}) {
  const client = useQueryClient()
  const [version, setVersion] = useState<string | null>(null)
  const [prompt, setPrompt] = useState('')
  const [newVersion, setNewVersion] = useState('')
  const [result, setResult] = useState<Phase1Result | null>(null)

  const selected = rubrics.find((entry) => entry.version === version) ?? rubrics[0] ?? null

  // Le prompt suit le barème choisi tant qu'il n'a pas été édité à la main —
  // ensuite l'éditeur fait foi, c'est lui qui est réellement envoyé.
  useEffect(() => {
    if (selected && prompt === '') setPrompt(selected.prompt)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.version])

  const run = useMutation({
    mutationFn: () =>
      api.phase1({
        id,
        rubricVersion: selected?.version ?? 'v1',
        prompt,
        axes: selected?.axes ?? [],
      }),
    onSuccess: setResult,
    onError: (error: Error) =>
      notifications.show({ color: 'red', title: 'Notation échouée', message: error.message }),
  })

  const save = useMutation({
    mutationFn: () =>
      api.saveRubric({
        version: newVersion.trim(),
        prompt,
        axes: selected?.axes ?? [],
        note: `depuis ${selected?.version ?? '—'}`,
      }),
    onSuccess: (created) => {
      void client.invalidateQueries({ queryKey: ['rubrics'] })
      setVersion(created.version)
      setNewVersion('')
      notifications.show({
        color: 'teal',
        title: 'Barème figé',
        message: `${created.version} — les prochaines notes lui seront rattachées.`,
      })
    },
    onError: (error: Error) =>
      notifications.show({ color: 'red', title: 'Version refusée', message: error.message }),
  })

  const axes = selected?.axes ?? []
  const edited = selected !== null && prompt !== selected.prompt

  return (
    <Group align="flex-start" gap="md" wrap="nowrap">
      {/* Le dossier : ce que les juges lisent, exactement. */}
      <Paper withBorder radius="md" p="sm" style={{ flex: 1, minWidth: 0 }}>
        <Text size="sm" fw={600} mb={6}>
          Le dossier soumis aux juges
        </Text>
        <ScrollArea h={560}>
          {loading ? (
            <Loader size="sm" />
          ) : (
            <Text size="xs" ff="monospace" style={{ whiteSpace: 'pre-wrap' }}>
              {dossierText ?? '—'}
            </Text>
          )}
        </ScrollArea>
      </Paper>

      {/* Le barème, l'essai, le verdict. */}
      <Stack gap="sm" style={{ flex: 1, minWidth: 0 }}>
        <Group gap="sm" align="flex-end">
          <Select
            label="Barème"
            data={rubrics.map((entry) => ({ value: entry.version, label: entry.version }))}
            value={selected?.version ?? null}
            onChange={setVersion}
            allowDeselect={false}
            w={180}
          />
          <Button
            leftSection={<IconPlayerPlay size={16} />}
            onClick={() => run.mutate()}
            loading={run.isPending}
            disabled={!selected || prompt.length < 50}
          >
            Noter avec les deux juges
          </Button>
          {edited && (
            <Badge color="yellow" variant="light">
              prompt édité, non figé
            </Badge>
          )}
        </Group>

        <Textarea
          label="La consigne envoyée (system prompt)"
          description="Éditable librement — chaque essai est tracé par son empreinte. Une formulation qui tient se fige en nouvelle version."
          value={prompt}
          onChange={(event) => setPrompt(event.currentTarget.value)}
          autosize
          minRows={10}
          maxRows={16}
          styles={{ input: { fontFamily: 'monospace', fontSize: 12 } }}
        />

        {edited && (
          <Group gap="xs" align="flex-end">
            <TextInput
              label="Figer comme version"
              placeholder="v2-luminosite-precisee"
              value={newVersion}
              onChange={(event) => setNewVersion(event.currentTarget.value)}
              w={260}
            />
            <Button
              variant="default"
              onClick={() => save.mutate()}
              loading={save.isPending}
              disabled={newVersion.trim().length === 0}
            >
              Figer
            </Button>
          </Group>
        )}

        {run.isPending && (
          <Alert color="blue" variant="light">
            Les deux juges lisent le dossier — une vingtaine de secondes.
          </Alert>
        )}

        {result && (
          <Paper withBorder radius="md" p="sm">
            <GapSummary gaps={result.gaps} />
            <Table mt="xs" verticalSpacing={6}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Axe</Table.Th>
                  <Table.Th>OpenAI ({result.openai.model})</Table.Th>
                  <Table.Th>Haiku ({result.haiku.model})</Table.Th>
                  <Table.Th>Écart</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {axes.map((axe) => (
                  <Table.Tr key={axe}>
                    <Table.Td>
                      <Text size="sm">{axe}</Text>
                    </Table.Td>
                    <Table.Td>
                      <ScoreCell entry={result.openai.scores[axe]} />
                    </Table.Td>
                    <Table.Td>
                      <ScoreCell entry={result.haiku.scores[axe]} />
                    </Table.Td>
                    <Table.Td>
                      <GapBadge gap={result.gaps.perAxis[axe]} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Paper>
        )}
      </Stack>
    </Group>
  )
}

// ------------------------------------------------------------------ phase 2

function Phase2({ id, rubrics }: { id: number; rubrics: Rubric[] }) {
  const [version, setVersion] = useState<string | null>(null)
  const [result, setResult] = useState<Phase2Result | null>(null)

  const selected = rubrics.find((entry) => entry.version === version) ?? rubrics[0] ?? null

  const train = useMutation({
    mutationFn: () => api.trainWeights(selected?.version ?? 'v1'),
    onSuccess: (bilan) =>
      notifications.show({
        color: 'teal',
        title: `Poids réentraînés sur ${bilan.works} œuvre(s)`,
        message: bilan.axes
          .map((axe) =>
            axe.skipped ? `${axe.axe} : trop peu de notes` : `${axe.axe} : MAE ${axe.maeFit}`,
          )
          .join(' · '),
      }),
    onError: (error: Error) =>
      notifications.show({ color: 'red', title: 'Entraînement refusé', message: error.message }),
  })

  const compare = useMutation({
    mutationFn: (runLlm: boolean) =>
      api.phase2({ id, rubricVersion: selected?.version ?? 'v1', runLlm }),
    onSuccess: setResult,
    onError: (error: Error) =>
      notifications.show({ color: 'red', title: 'Comparaison échouée', message: error.message }),
  })

  const axes = selected?.axes ?? []

  return (
    <Stack gap="sm">
      <Group gap="sm" align="flex-end">
        <Select
          label="Barème"
          data={rubrics.map((entry) => ({ value: entry.version, label: entry.version }))}
          value={selected?.version ?? null}
          onChange={setVersion}
          allowDeselect={false}
          w={180}
        />
        <Button
          variant="default"
          onClick={() => train.mutate()}
          loading={train.isPending}
          disabled={!selected}
        >
          Réentraîner les poids
        </Button>
        <Button
          onClick={() => compare.mutate(false)}
          loading={compare.isPending}
          disabled={!selected}
        >
          Comparer (notes stockées)
        </Button>
        <Tooltip label="Note aussi l'œuvre avec OpenAI maintenant — un appel payant" multiline w={240}>
          <Button
            variant="light"
            onClick={() => compare.mutate(true)}
            loading={compare.isPending}
            disabled={!selected}
          >
            Comparer (note fraîche)
          </Button>
        </Tooltip>
      </Group>

      <Text size="xs" c="dimmed">
        La boucle : les poids prédisent, le LLM vérifie. Écart au niveau du bruit (≤ 1) → les
        poids tiennent, on continue sur le lot suivant. Écart au-delà → « Réentraîner » refait la
        régression sur tout l'historique de notes du barème.
      </Text>

      {result && (
        <Paper withBorder radius="md" p="sm">
          {result.gaps ? (
            <GapSummary gaps={result.gaps} />
          ) : (
            <Alert color="yellow" variant="light">
              Aucune note LLM stockée pour cette œuvre sur ce barème — « Comparer (note fraîche) »
              en produit une.
            </Alert>
          )}
          <Table mt="xs" verticalSpacing={6}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Axe</Table.Th>
                <Table.Th>Interne (poids)</Table.Th>
                <Table.Th>
                  LLM{' '}
                  {result.llm.origin
                    ? `(${result.llm.origin.model}${result.llm.origin.fresh ? ', fraîche' : ', stockée'})`
                    : ''}
                </Table.Th>
                <Table.Th>Écart</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {axes.map((axe) => (
                <Table.Tr key={axe}>
                  <Table.Td>
                    <Text size="sm">{axe}</Text>
                  </Table.Td>
                  <Table.Td>
                    {result.internal[axe] ? (
                      <Group gap={6} wrap="nowrap">
                        <Text fw={600}>{result.internal[axe].score}</Text>
                        <Tooltip
                          label={`entraîné sur ${result.internal[axe].trainedOn} œuvre(s) — MAE d'ajustement ${result.internal[axe].maeFit ?? '—'}`}
                        >
                          <Text size="xs" c="dimmed">
                            n={result.internal[axe].trainedOn}
                          </Text>
                        </Tooltip>
                      </Group>
                    ) : (
                      <Text size="sm" c="dimmed">
                        pas de poids
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <ScoreCell entry={result.llm.scores[axe]} />
                  </Table.Td>
                  <Table.Td>
                    <GapBadge gap={result.gaps?.perAxis[axe]} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
    </Stack>
  )
}
