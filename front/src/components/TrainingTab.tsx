import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  NumberInput,
  Paper,
  ScrollArea,
  Select,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconCopy, IconPhotoScan, IconPlayerPlay } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { ApiError, api } from '../api'
import type { AxisScore, Gaps, Phase1Result, Phase2Result, Rubric, TrainingRun } from '../types'

/**
 * L'atelier d'entraînement de la notation — le contenu des onglets Training 1
 * et Training 2 de la fiche série. Un onglet par phase, une même mécanique.
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
export function TrainingTab({ id, phase }: { id: number; phase: 1 | 2 }) {
  const queryClient = useQueryClient()

  const dossier = useQuery({
    queryKey: ['training-dossier', id],
    queryFn: () => api.trainingDossier(id),
    retry: false,
  })
  const rubrics = useQuery({ queryKey: ['rubrics'], queryFn: api.rubrics })

  // Les légendes visuelles : payées une fois, figées en base, relues par le
  // dossier — d'où l'invalidation, qui fait apparaître la section MEDIA.
  const caption = useMutation({
    mutationFn: () => api.captionWork(id),
    onSuccess: (result) => {
      notifications.show({
        color: 'teal',
        title: 'Visuels légendés',
        message:
          result.captioned > 0
            ? `${result.captioned} image(s) décrites par ${result.model}` +
              (result.already > 0 ? `, ${result.already} déjà en base.` : '.')
            : `Les ${result.already} images étaient déjà légendées — rien à payer.`,
      })
      void queryClient.invalidateQueries({ queryKey: ['training-dossier', id] })
    },
    onError: (error: Error) =>
      notifications.show({ color: 'red', title: 'Légende impossible', message: error.message }),
  })

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <Badge variant="light">#{id}</Badge>
        {dossier.data && (
          <Group gap="sm" wrap="nowrap">
            <Text size="sm" c="dimmed">
              dossier {dossier.data.chars.toLocaleString('fr-FR')} caractères ·{' '}
              {dossier.data.sections.episodeCount} synopsis d'épisodes ·{' '}
              {dossier.data.sections.mediaLines > 0
                ? `${dossier.data.sections.mediaLines} visuels légendés`
                : 'visuels non légendés'}{' '}
              · {dossier.data.sections.wikipediaChars > 0
                ? 'Wikipédia en'
                : 'pas de Wikipédia — enrichir aiderait'}
            </Text>
            <Tooltip
              label="Décrit les backdrops et stills d'épisodes avec le modèle de vision, une fois pour toutes — la section MEDIA du dossier."
              multiline
              w={280}
            >
              <Button
                size="compact-sm"
                variant="default"
                leftSection={<IconPhotoScan size={14} />}
                loading={caption.isPending}
                onClick={() => caption.mutate()}
              >
                Légender les visuels
              </Button>
            </Tooltip>
          </Group>
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

      {phase === 1 ? (
        <Phase1
          id={id}
          dossierText={dossier.data?.text}
          rubrics={rubrics.data ?? []}
          loading={rubrics.isLoading || dossier.isLoading}
        />
      ) : (
        <Phase2 id={id} rubrics={rubrics.data ?? []} />
      )}
    </Stack>
  )
}

/**
 * Copie dans le presse-papier, où que l'admin soit servie.
 *
 * `navigator.clipboard` n'existe qu'en contexte sécurisé — HTTPS ou
 * localhost. Or l'admin de production est servie en HTTP direct sur son
 * port : le bouton « Copier pour Claude.ai » y levait une erreur muette et
 * paraissait mort. Le repli est l'ancienne méthode `execCommand('copy')` sur
 * un textarea hors écran : dépréciée, mais précisément maintenue par les
 * navigateurs pour ce cas-là.
 */
async function copyText(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Le presse-papier moderne peut refuser (permission, focus perdu) :
      // on tente quand même l'ancien chemin plutôt que d'échouer.
    }
  }
  const zone = document.createElement('textarea')
  zone.value = text
  zone.setAttribute('readonly', '')
  zone.style.position = 'fixed'
  zone.style.opacity = '0'
  document.body.appendChild(zone)
  zone.focus()
  zone.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    zone.remove()
  }
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
  // La contre-note saisie à la main — le verdict de claude.ai, recopié axe par
  // axe. Vide tant qu'on n'a rien collé.
  const [manual, setManual] = useState<Record<string, number | null>>({})
  // La réponse de claude.ai, collée telle quelle : les lignes « axe: note »
  // remplissent la contre-note toutes seules.
  const [reply, setReply] = useState('')

  const selected = rubrics.find((entry) => entry.version === version) ?? rubrics[0] ?? null

  // Le prompt suit le barème choisi tant qu'il n'a pas été édité à la main —
  // ensuite l'éditeur fait foi, c'est lui qui est réellement envoyé.
  useEffect(() => {
    if (selected && prompt === '') setPrompt(selected.prompt)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.version])

  // Le journal des essais : c'est lui qui rend la page rechargeable. Sans
  // lui, les verdicts ne vivaient que dans l'état du navigateur et un F5
  // faisait croire que la notation n'avait jamais eu lieu.
  const runs = useQuery({ queryKey: ['training-runs', id], queryFn: () => api.trainingRuns(id) })
  const lastRun = runs.data?.[0] ?? null

  // L'essai affiché : celui qu'on vient de lancer, sinon le dernier du
  // journal. Régénérer écrase l'affichage — le journal, lui, garde tout.
  const shown =
    result !== null
      ? { ...result, storedAt: null as string | null }
      : lastRun?.openai
        ? {
            runId: lastRun.id,
            openai: lastRun.openai,
            haiku: lastRun.claude,
            gaps: lastRun.claude
              ? computeGaps(lastRun.openai.scores, lastRun.claude.scores, axesOf(lastRun))
              : null,
            storedAt: lastRun.createdAt,
          }
        : null

  const run = useMutation({
    mutationFn: () =>
      api.phase1({
        id,
        rubricVersion: selected?.version ?? 'v1',
        prompt,
        axes: selected?.axes ?? [],
      }),
    onSuccess: (next) => {
      setResult(next)
      setManual({})
      void client.invalidateQueries({ queryKey: ['training-runs', id] })
    },
    onError: (error: Error) =>
      notifications.show({ color: 'red', title: 'Notation échouée', message: error.message }),
  })

  const saveManual = useMutation({
    mutationFn: () =>
      api.manualScores({
        id,
        rubricVersion: selected?.version ?? 'v1',
        prompt,
        scores: Object.fromEntries(
          Object.entries(manual)
            .filter(([, score]) => score !== null && score !== undefined)
            .map(([axe, score]) => [axe, { score }]),
        ),
        // L'essai auquel la contre-note répond — celui qui est affiché,
        // qu'il soit tout frais ou relu du journal.
        runId: shown?.runId ?? null,
      }),
    onSuccess: (stored) => {
      notifications.show({
        color: 'teal',
        title: 'Contre-note enregistrée',
        message: `${stored.stored} axe(s) sous « ${stored.modele} » — même provenance qu'un juge automatique.`,
      })
      void client.invalidateQueries({ queryKey: ['training-runs', id] })
    },
    onError: (error: Error) =>
      notifications.show({ color: 'red', title: 'Enregistrement refusé', message: error.message }),
  })

  /** Consigne + dossier, prêts à coller dans claude.ai — le contre-jugement
   *  manuel quand il n'y a pas de clé Anthropic. */
  const copyForClaude = async () => {
    const axesList = (selected?.axes ?? []).join(', ')
    const text =
      `${prompt}\n\nReply with one line per axis, format "axis: score" (${axesList}).` +
      `\n\n----- DOSSIER -----\n\n${dossierText ?? ''}`
    if (await copyText(text)) {
      notifications.show({
        color: 'teal',
        title: 'Copié',
        message: 'Consigne + dossier dans le presse-papier — à coller dans claude.ai.',
      })
    } else {
      notifications.show({
        color: 'red',
        title: 'Copie impossible',
        message:
          'Le navigateur a refusé les deux méthodes de copie — sélectionner le dossier à la main.',
      })
    }
  }

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
            Noter (OpenAI)
          </Button>
          <Tooltip
            label="Copie consigne + dossier — à coller dans claude.ai pour le contre-jugement manuel"
            multiline
            w={260}
          >
            <Button
              variant="default"
              leftSection={<IconCopy size={16} />}
              onClick={copyForClaude}
              disabled={!dossierText || prompt.length < 50}
            >
              Copier pour Claude.ai
            </Button>
          </Tooltip>
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
            Le juge lit le dossier — une vingtaine de secondes.
          </Alert>
        )}

        {shown && (
          <Paper withBorder radius="md" p="sm">
            {shown.storedAt && (
              <Text size="xs" c="dimmed" mb={4}>
                Relu du journal — essai du {new Date(shown.storedAt).toLocaleString('fr-FR')}.
                « Noter (OpenAI) » régénère et prend sa place.
              </Text>
            )}
            {shown.gaps ? (
              <GapSummary gaps={shown.gaps} />
            ) : (
              <Text size="xs" c="dimmed">
                Contre-jugement manuel : « Copier pour Claude.ai », coller la réponse axe par axe
                ci-dessous — l'écart se calcule, « Enregistrer » lui donne la même provenance
                qu'un juge automatique. ≤ 1 : au niveau du bruit, le prompt tient · &gt; 2 : le
                prompt est ambigu sur les axes rouges.
              </Text>
            )}
            <Table mt="xs" verticalSpacing={6}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Axe</Table.Th>
                  <Table.Th>OpenAI ({shown.openai.model})</Table.Th>
                  <Table.Th>
                    {!shown.haiku
                      ? 'Claude.ai (à la main)'
                      : shown.haiku.model.includes('web-manuel')
                        ? 'Claude.ai (recopié)'
                        : `Haiku (${shown.haiku.model})`}
                  </Table.Th>
                  <Table.Th>Écart</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {axes.map((axe) => {
                  const openaiScore = shown.openai.scores[axe]?.score ?? null
                  const counterScore = shown.haiku
                    ? (shown.haiku.scores[axe]?.score ?? null)
                    : (manual[axe] ?? null)
                  const gap =
                    openaiScore !== null && counterScore !== null
                      ? Math.abs(openaiScore - counterScore)
                      : null
                  return (
                    <Table.Tr key={axe}>
                      <Table.Td>
                        <Text size="sm">{axe}</Text>
                      </Table.Td>
                      <Table.Td>
                        <ScoreCell entry={shown.openai.scores[axe]} />
                      </Table.Td>
                      <Table.Td>
                        {shown.haiku ? (
                          <ScoreCell entry={shown.haiku.scores[axe]} />
                        ) : (
                          <NumberInput
                            size="xs"
                            w={80}
                            min={1}
                            max={10}
                            placeholder="1-10"
                            value={manual[axe] ?? ''}
                            onChange={(next) =>
                              setManual((current) => ({
                                ...current,
                                [axe]: typeof next === 'number' ? next : null,
                              }))
                            }
                          />
                        )}
                      </Table.Td>
                      <Table.Td>
                        <GapBadge gap={gap} />
                      </Table.Td>
                    </Table.Tr>
                  )
                })}
              </Table.Tbody>
            </Table>
          </Paper>
        )}

        {/* La contre-note claude.ai — toujours visible, exprès : la réponse
            revient du site web bien après le clic « Noter », parfois après un
            rechargement de page. Elle ne doit dépendre d'aucun état fugace. */}
        {axes.length > 0 && (
          <Paper withBorder radius="md" p="sm">
            <Text size="sm" fw={600}>
              Contre-note claude.ai
            </Text>
            <Text size="xs" c="dimmed" mb={6}>
              « Copier pour Claude.ai », coller dans claude.ai, puis coller sa réponse ici — les
              lignes « axe: note » remplissent les cases toutes seules. Ajuster au besoin, puis
              enregistrer : la contre-note rejoint le journal de l'essai.
            </Text>
            <Textarea
              placeholder={axes.map((axe) => `${axe}: 5`).join('\n')}
              value={reply}
              onChange={(event) => {
                const next = event.currentTarget.value
                setReply(next)
                const parsed = parseClaudeReply(next, axes)
                if (Object.keys(parsed).length > 0) {
                  setManual((current) => ({ ...current, ...parsed }))
                }
              }}
              autosize
              minRows={3}
              maxRows={8}
              styles={{ input: { fontFamily: 'monospace', fontSize: 12 } }}
            />
            <Group gap="xs" mt="xs" align="flex-end" wrap="wrap">
              {axes.map((axe) => (
                <NumberInput
                  key={axe}
                  label={axe}
                  size="xs"
                  w={110}
                  min={1}
                  max={10}
                  placeholder="1-10"
                  value={manual[axe] ?? ''}
                  onChange={(next) =>
                    setManual((current) => ({
                      ...current,
                      [axe]: typeof next === 'number' ? next : null,
                    }))
                  }
                />
              ))}
              <Button
                size="xs"
                variant="default"
                onClick={() => saveManual.mutate()}
                loading={saveManual.isPending}
                disabled={Object.values(manual).every((score) => score === null)}
              >
                Enregistrer la contre-note
              </Button>
            </Group>
          </Paper>
        )}
      </Stack>
    </Group>
  )
}

/** Les axes d'un essai stocké — ceux que son juge OpenAI a réellement notés. */
function axesOf(run: TrainingRun): string[] {
  return run.openai ? Object.keys(run.openai.scores) : []
}

/**
 * Les écarts entre deux verdicts, même calcul que le serveur : par axe, et en
 * moyenne sur les axes notés des deux côtés. Refait ici parce que le journal
 * stocke les verdicts bruts, pas leur comparaison — c'est un affichage.
 */
function computeGaps(
  left: Record<string, AxisScore>,
  right: Record<string, AxisScore>,
  axes: string[],
): Gaps {
  const perAxis: Record<string, number | null> = {}
  const diffs: number[] = []
  for (const axe of axes) {
    const a = left[axe]?.score ?? null
    const b = right[axe]?.score ?? null
    if (a === null || b === null) {
      perAxis[axe] = null
    } else {
      const gap = Math.abs(a - b)
      perAxis[axe] = gap
      diffs.push(gap)
    }
  }
  return {
    perAxis,
    mean: diffs.length ? Math.round((diffs.reduce((s, g) => s + g, 0) / diffs.length) * 100) / 100 : null,
    scored: diffs.length,
  }
}

/**
 * Lit la réponse de claude.ai : une note par ligne, au format demandé par la
 * consigne copiée — `luminosite: 7`. Tolérant sur l'habillage (tirets de
 * liste, majuscules, `=`, décimales) mais strict sur les noms d'axes : une
 * ligne qui ne correspond à aucun axe du barème est ignorée, jamais devinée.
 */
function parseClaudeReply(text: string, axes: string[]): Record<string, number> {
  const scores: Record<string, number> = {}
  for (const line of text.split('\n')) {
    const match = line.match(/^\s*[-*•]?\s*"?([\p{L}_-]+)"?\s*[:=]\s*(\d+(?:[.,]\d+)?)/u)
    if (!match) continue
    const name = match[1].toLowerCase()
    const axe = axes.find((candidate) => candidate.toLowerCase() === name)
    if (!axe) continue
    const value = Math.round(Number(match[2].replace(',', '.')))
    if (value >= 1 && value <= 10) scores[axe] = value
  }
  return scores
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
          <Text size="xs" c="dimmed" mb={4}>
            Poids du {new Date(result.weights.trainedAt).toLocaleString('fr-FR')} — la version la
            plus récente du journal, entraînée sur {result.weights.works} œuvre(s).
          </Text>
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
