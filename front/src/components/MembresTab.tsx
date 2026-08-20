import { useState } from 'react'
import {
  Badge,
  Center,
  Drawer,
  Group,
  Image,
  Loader,
  Pagination,
  Paper,
  ScrollArea,
  Skeleton,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { useQuery } from '@tanstack/react-query'
import { IconArrowDown, IconArrowUp, IconArrowsSort, IconSearch } from '@tabler/icons-react'

import { api } from '../api'
import { POSTER_FALLBACK, formatDate, formatNumber, titleDirection } from '../display'
import type { Membre, MembreFive } from '../types'

const COLONNES: { cle: string; libelle: string; triable: boolean; aligne?: 'right' }[] = [
  { cle: 'pseudo', libelle: 'Pseudo', triable: true },
  { cle: 'email', libelle: 'Email', triable: false },
  { cle: 'fives', libelle: 'Tops', triable: true, aligne: 'right' },
  { cle: 'positions', libelle: 'Œuvres citées', triable: true, aligne: 'right' },
  { cle: 'creation', libelle: 'Inscription', triable: true },
  { cle: 'connexion', libelle: 'Dernière visite', triable: true },
]

const UNIVERS: Record<string, string> = { series: 'Séries', movies: 'Films' }
const PERIODES: Record<string, string> = { life: 'de toujours', moment: 'du moment', year: "de l'année" }

/** La liste des membres, et leurs tops au clic.
 *
 *  Deux requêtes distinctes, et c'est le point de conception : la liste ne
 *  porte que des compteurs, le détail n'est chargé que pour la ligne ouverte.
 *  Joindre les positions à la liste ferait descendre 324 000 lignes pour en
 *  montrer cinquante.
 */
export function MembresTab() {
  const [recherche, setRecherche] = useState('')
  const [rechercheRetardee] = useDebouncedValue(recherche, 350)
  const [avecFives, setAvecFives] = useState(false)
  const [tri, setTri] = useState('fives')
  const [ordre, setOrdre] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [ouvert, setOuvert] = useState<Membre | null>(null)

  const pageSize = 50
  const liste = useQuery({
    queryKey: ['membres', rechercheRetardee, avecFives, tri, ordre, page],
    queryFn: () =>
      api.membres({
        q: rechercheRetardee || undefined,
        avecFives: avecFives || undefined,
        tri,
        ordre,
        page,
        pageSize,
      }),
    // La liste ne bouge pas d'elle-même : les membres viennent d'un import,
    // pas d'inscriptions en cours. Inutile de la rejouer à chaque focus.
    staleTime: 60_000,
  })

  const detail = useQuery({
    queryKey: ['membre-fives', ouvert?.id],
    queryFn: () => api.membreFives(ouvert!.id),
    enabled: ouvert !== null,
  })

  function trierPar(cle: string) {
    if (cle === tri) {
      setOrdre((o) => (o === 'desc' ? 'asc' : 'desc'))
    } else {
      setTri(cle)
      setOrdre(cle === 'pseudo' ? 'asc' : 'desc')
    }
    setPage(1)
  }

  const total = liste.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <Stack gap="md">
      <Paper withBorder p="md">
        <Group justify="space-between" align="flex-end">
          <TextInput
            label="Chercher"
            description="Dans le pseudo et dans l'email"
            placeholder="pseudo ou email"
            leftSection={<IconSearch size={16} />}
            value={recherche}
            onChange={(e) => {
              setRecherche(e.currentTarget.value)
              setPage(1)
            }}
            w={320}
          />
          <Switch
            label="Seulement ceux qui ont un top"
            checked={avecFives}
            onChange={(e) => {
              setAvecFives(e.currentTarget.checked)
              setPage(1)
            }}
            mb={6}
          />
          <Text size="sm" c="dimmed" mb={6}>
            {formatNumber(total)} membre{total > 1 ? 's' : ''}
          </Text>
        </Group>
      </Paper>

      <Paper withBorder>
        <ScrollArea>
          <Table highlightOnHover striped="even" miw={800}>
            <Table.Thead>
              <Table.Tr>
                {COLONNES.map((c) => (
                  <Table.Th key={c.cle} ta={c.aligne}>
                    {c.triable ? (
                      <UnstyledButton onClick={() => trierPar(c.cle)}>
                        <Group gap={4} wrap="nowrap" justify={c.aligne ? 'flex-end' : undefined}>
                          <Text size="sm" fw={600}>
                            {c.libelle}
                          </Text>
                          {tri !== c.cle ? (
                            <IconArrowsSort size={14} opacity={0.4} />
                          ) : ordre === 'desc' ? (
                            <IconArrowDown size={14} />
                          ) : (
                            <IconArrowUp size={14} />
                          )}
                        </Group>
                      </UnstyledButton>
                    ) : (
                      <Text size="sm" fw={600}>
                        {c.libelle}
                      </Text>
                    )}
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {liste.isLoading
                ? Array.from({ length: 10 }, (_, i) => (
                    <Table.Tr key={i}>
                      {COLONNES.map((c) => (
                        <Table.Td key={c.cle}>
                          <Skeleton h={18} />
                        </Table.Td>
                      ))}
                    </Table.Tr>
                  ))
                : liste.data?.items.map((m) => (
                    <Table.Tr
                      key={m.id}
                      tabIndex={0}
                      onClick={() => setOuvert(m)}
                      // Une ligne cliquable qui ne répond pas au clavier
                      // n'est cliquable que pour ceux qui ont une souris.
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          setOuvert(m)
                        }
                      }}
                      style={{ cursor: 'pointer' }}
                    >
                      <Table.Td>
                        <Group gap="xs" wrap="nowrap">
                          <Text size="sm" dir={titleDirection}>
                            {m.pseudo ?? <Text span c="dimmed" fs="italic">sans pseudo</Text>}
                          </Text>
                          {m.bani && (
                            <Badge size="xs" color="red" variant="light">
                              banni
                            </Badge>
                          )}
                          {m.masque && (
                            <Tooltip label="Ne paraît jamais côté public — importé de la V1">
                              <Badge size="xs" color="gray" variant="light">
                                masqué
                              </Badge>
                            </Tooltip>
                          )}
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        {m.email ? (
                          <Text size="sm">{m.email}</Text>
                        ) : (
                          /* 37 006 membres sont dans ce cas : ils ont publié un
                             top sans jamais créer de compte. Ce n'est pas une
                             donnée manquante, c'est leur statut. */
                          <Tooltip label="A publié un top sans créer de compte">
                            <Badge size="xs" variant="light" color="gray">
                              invité
                            </Badge>
                          </Tooltip>
                        )}
                      </Table.Td>
                      <Table.Td ta="right">{m.fives}</Table.Td>
                      <Table.Td ta="right">{m.positions}</Table.Td>
                      <Table.Td>{formatDate(m.creation)}</Table.Td>
                      <Table.Td>{formatDate(m.derniereConnexion)}</Table.Td>
                    </Table.Tr>
                  ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>

        {!liste.isLoading && liste.data?.items.length === 0 && (
          <Center p="xl">
            <Text c="dimmed">Aucun membre pour cette recherche.</Text>
          </Center>
        )}

        {pages > 1 && (
          <Group justify="center" p="md">
            <Pagination value={page} onChange={setPage} total={pages} siblings={1} />
          </Group>
        )}
      </Paper>

      <Drawer
        opened={ouvert !== null}
        onClose={() => setOuvert(null)}
        position="right"
        size="xl"
        title={
          <Group gap="xs">
            <Title order={4}>{ouvert?.pseudo ?? 'Membre sans pseudo'}</Title>
            <Text c="dimmed" size="sm">
              {ouvert?.email ?? 'invité'}
            </Text>
          </Group>
        }
      >
        {detail.isLoading ? (
          <Center p="xl">
            <Loader />
          </Center>
        ) : (
          <Stack gap="lg">
            {detail.data?.fives.length === 0 && (
              <Text c="dimmed">Ce membre n'a aucun top.</Text>
            )}
            {detail.data?.fives.map((five) => (
              <TopDuMembre key={five.id} five={five} />
            ))}
          </Stack>
        )}
      </Drawer>
    </Stack>
  )
}

/** Un top : son intitulé, puis ses positions dans l'ordre du classement.
 *
 *  Le rang est affiché tel qu'il est stocké et n'est pas renuméroté : un top
 *  V1 peut compter plus de cinq entrées — 476 en ont, jusqu'à 118 — et masquer
 *  la queue ferait disparaître des citations bien réelles. */
function TopDuMembre({ five }: { five: MembreFive }) {
  return (
    <Paper withBorder p="md">
      <Group justify="space-between" mb="sm">
        <Group gap="xs">
          <Badge variant="light">{UNIVERS[five.univers] ?? five.univers}</Badge>
          <Text fw={600}>{five.titre ?? `Top ${PERIODES[five.periode] ?? five.periode}`}</Text>
        </Group>
        <Text size="xs" c="dimmed">
          {five.positions.length} œuvre{five.positions.length > 1 ? 's' : ''} · {formatDate(five.creation)}
        </Text>
      </Group>

      <Stack gap="xs">
        {five.positions.map((p) => (
          <Group key={p.rang} gap="sm" wrap="nowrap" align="flex-start">
            <Text size="sm" c="dimmed" w={20} ta="right">
              {p.rang}
            </Text>
            <Image
              src={p.poster ? `https://image.tmdb.org/t/p/w92${p.poster}` : POSTER_FALLBACK}
              w={32}
              h={48}
              radius="sm"
              fit="cover"
            />
            <Stack gap={2} style={{ flex: 1 }}>
              <Group gap="xs">
                <Text size="sm" fw={500} dir={titleDirection}>
                  {p.titre ?? p.titreSaisi ?? `œuvre ${p.oeuvreId}`}
                </Text>
                {p.annee && (
                  <Text size="xs" c="dimmed">
                    {p.annee}
                  </Text>
                )}
                {p.idTmdb === null && (
                  /* Œuvre née de la V1, sans fiche TMDB : le dire évite de
                     chercher pourquoi elle n'a ni affiche ni note. */
                  <Tooltip label="Créée depuis la V1, sans fiche TMDB">
                    <Badge size="xs" variant="outline" color="gray">
                      hors TMDB
                    </Badge>
                  </Tooltip>
                )}
              </Group>
              {p.pourquoi && (
                <Text size="xs" c="dimmed" fs="italic">
                  « {p.pourquoi} »
                </Text>
              )}
            </Stack>
          </Group>
        ))}
      </Stack>
    </Paper>
  )
}
