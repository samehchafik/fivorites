import { useMemo } from 'react'
import { Alert, Box, Center, Group, Loader, Paper, Stack, Text } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { IconAlertTriangle } from '@tabler/icons-react'

import { api } from '../api'
import type { GrapheArete, GrapheNoeud } from '../types'

/**
 * Le voisinage d'un membre, dessiné.
 *
 * Pourquoi une simulation écrite à la main plutôt qu'une bibliothèque : le
 * graphe fait soixante-dix nœuds, la mise en place tient en cinquante lignes,
 * et la plus légère des bibliothèques de rendu pèse plus que tout le reste du
 * bundle réuni. Ce qu'on perdrait — le zoom, le glisser-déposer — n'est pas ce
 * qu'on regarde ici : on veut voir *ce qui relie* deux œuvres, pas manipuler.
 *
 * La simulation tourne une fois, dans un `useMemo`, et rend des coordonnées
 * figées. Pas d'animation : soixante-dix nœuds qui frétillent ne disent rien
 * de plus qu'une image nette, et une image nette se lit à la capture d'écran.
 */

const COULEURS: Record<GrapheNoeud['type'], string> = {
  moi: 'var(--mantine-color-blue-6)',
  oeuvre: 'var(--mantine-color-violet-5)',
  personne: 'var(--mantine-color-teal-5)',
  voisin: 'var(--mantine-color-orange-5)',
}

const RAYONS: Record<GrapheNoeud['type'], number> = { moi: 13, oeuvre: 9, personne: 5, voisin: 7 }

// La longueur au repos d'un ressort, par nature de lien, et l'écart entre les
// trois est ce qui fait lire le dessin en couches plutôt qu'en pelote : les
// personnes serrées contre leur œuvre, le membre à distance moyenne de ses
// œuvres, les voisins repoussés au large. Sans le troisième réglage, un voisin
// qui partage six œuvres se retrouve tiré au centre par six ressorts et vient
// se superposer au membre lui-même — constaté à l'écran.
const REPOS: Record<string, number> = { cite: 210, moi: 120, role: 62 }

// La force de répulsion. Assez haute pour que soixante nœuds tiennent sans se
// toucher dans un tiroir de 780 pixels.
const REPULSION = 5200

// Tout le monde ne pousse pas pareil, et c'est ce qui rend le dessin lisible :
// les nœuds qu'on lit — le membre, ses œuvres — se font de la place, les
// quarante pastilles d'acteurs se serrent en périphérie. Une répulsion
// uniforme donnait un tas au centre, où les titres se recouvraient.
const POIDS: Record<GrapheNoeud['type'], number> = {
  moi: 3,
  oeuvre: 2.4,
  voisin: 1.3,
  personne: 1,
}

interface Point extends GrapheNoeud {
  x: number
  y: number
  vx: number
  vy: number
}

function nature(a: GrapheArete, moi: string): keyof typeof REPOS {
  if (a.de === moi) return 'moi'
  return a.type === 'cite' ? 'cite' : 'role'
}

/** Fruchterman-Reingold, version courte : répulsion entre tous, ressorts sur
 *  les arêtes, refroidissement linéaire. Départ en spirale déterministe —
 *  aucun hasard, donc le même graphe donne toujours la même image. */
function disposer(noeuds: GrapheNoeud[], aretes: GrapheArete[], moi: string): Point[] {
  const points: Point[] = noeuds.map((n, i) => {
    const angle = i * 2.399963 // l'angle d'or : une spirale sans amas
    const rayon = n.type === 'moi' ? 0 : 40 + 9 * Math.sqrt(i)
    return { ...n, x: Math.cos(angle) * rayon, y: Math.sin(angle) * rayon, vx: 0, vy: 0 }
  })
  const index = new Map(points.map((p) => [p.id, p]))
  const liens = aretes
    .map((a) => ({ a: index.get(a.de), b: index.get(a.vers), repos: REPOS[nature(a, moi)] }))
    .filter((l): l is { a: Point; b: Point; repos: number } => !!l.a && !!l.b)

  for (let pas = 0; pas < 500; pas++) {
    const froid = 1 - pas / 500
    for (const p of points) {
      p.vx = 0
      p.vy = 0
    }
    // Répulsion : tout le monde contre tout le monde. 70 nœuds, donc 2 400
    // paires — le coût est invisible et le code reste lisible.
    for (let i = 0; i < points.length; i++) {
      for (let j = i + 1; j < points.length; j++) {
        const p = points[i]
        const q = points[j]
        let dx = p.x - q.x
        let dy = p.y - q.y
        let d2 = dx * dx + dy * dy
        if (d2 < 1) {
          // Deux nœuds exactement superposés ne se repousseraient jamais :
          // on les décolle dans une direction stable, pas au hasard.
          dx = (i - j) * 0.5
          dy = 0.5
          d2 = 1
        }
        const force = (REPULSION * POIDS[p.type] * POIDS[q.type]) / d2
        const d = Math.sqrt(d2)
        p.vx += (dx / d) * force
        p.vy += (dy / d) * force
        q.vx -= (dx / d) * force
        q.vy -= (dy / d) * force
      }
    }
    // Ressorts.
    for (const { a, b, repos } of liens) {
      const dx = b.x - a.x
      const dy = b.y - a.y
      const d = Math.hypot(dx, dy) || 1
      const force = (d - repos) * 0.08
      a.vx += (dx / d) * force
      a.vy += (dy / d) * force
      b.vx -= (dx / d) * force
      b.vy -= (dy / d) * force
    }
    for (const p of points) {
      if (p.type === 'moi') continue // le membre reste au centre : c'est son graphe
      p.vx -= p.x * 0.010 // rappel vers le centre, sinon les feuilles s'échappent
      p.vy -= p.y * 0.010
      const pas_max = 12 * froid
      const v = Math.hypot(p.vx, p.vy) || 1
      p.x += (p.vx / v) * Math.min(v, pas_max)
      p.y += (p.vy / v) * Math.min(v, pas_max)
    }
  }
  return points
}

export function GrapheMembre({ id }: { id: number }) {
  const graphe = useQuery({
    queryKey: ['membre-graphe', id],
    queryFn: () => api.membreGraphe(id),
    staleTime: 60_000,
  })

  const dispose = useMemo(() => {
    if (!graphe.data?.noeuds.length) return null
    const moi = `membre:${id}`
    const points = disposer(graphe.data.noeuds, graphe.data.aretes, moi)
    const index = new Map(points.map((p) => [p.id, p]))
    const marge = 60
    const xs = points.map((p) => p.x)
    const ys = points.map((p) => p.y)
    return {
      points,
      index,
      vue: [
        Math.min(...xs) - marge,
        Math.min(...ys) - marge,
        Math.max(...xs) - Math.min(...xs) + 2 * marge,
        Math.max(...ys) - Math.min(...ys) + 2 * marge,
      ].join(' '),
    }
  }, [graphe.data, id])

  if (graphe.isLoading) {
    return (
      <Center p="xl">
        <Loader />
      </Center>
    )
  }

  if (graphe.isError) {
    return (
      <Alert color="yellow" variant="light" icon={<IconAlertTriangle size={18} />}>
        Le graphe n'a pas répondu. {(graphe.error as Error).message}
      </Alert>
    )
  }

  if (!graphe.data?.projete || !dispose) {
    return (
      <Alert color="gray" variant="light" icon={<IconAlertTriangle size={18} />}>
        Ce membre n'a aucun nœud dans le graphe. Soit il ne cite rien, soit la projection n'a
        pas encore tourné — <code>fiv-admin graphe projeter-membres</code>.
      </Alert>
    )
  }

  const { points, index, vue } = dispose

  return (
    <Stack gap="xs">
      <Paper withBorder p={0} style={{ overflow: 'hidden' }}>
        <Box
          component="svg"
          viewBox={vue}
          preserveAspectRatio="xMidYMid meet"
          style={{ width: '100%', height: 520, display: 'block' }}
        >
          {graphe.data.aretes.map((a, i) => {
            const de = index.get(a.de)
            const vers = index.get(a.vers)
            if (!de || !vers) return null
            const role = a.type !== 'cite'
            return (
              <line
                key={i}
                x1={de.x}
                y1={de.y}
                x2={vers.x}
                y2={vers.y}
                stroke={role ? 'var(--mantine-color-gray-4)' : 'var(--mantine-color-gray-5)'}
                strokeWidth={a.de === `membre:${id}` ? 1.6 : 0.8}
                strokeDasharray={role ? '3 3' : undefined}
              />
            )
          })}
          {points.map((p) => (
            <g key={p.id}>
              <circle cx={p.x} cy={p.y} r={RAYONS[p.type]} fill={COULEURS[p.type]} />
              <title>
                {p.libelle}
                {p.annee ? ` (${p.annee})` : ''}
                {p.communes ? ` — ${p.communes} œuvre(s) en commun` : ''}
              </title>
              {/* On n'étiquette pas tout : une personne qui ne relie qu'une
                  seule œuvre n'apprend rien et encombre. Celles qui en relient
                  deux sont exactement ce qu'on cherche à voir. */}
              {etiquetable(p, graphe.data.aretes) && (
                <text
                  x={p.x}
                  y={p.y - RAYONS[p.type] - 4}
                  textAnchor="middle"
                  style={{
                    fontSize: p.type === 'oeuvre' ? 11 : 9,
                    fontWeight: p.type === 'oeuvre' ? 600 : 400,
                    fill: 'var(--mantine-color-text)',
                    // Le liseré : sans lui, un titre qui croise une arête
                    // devient illisible. `paint-order` met le contour DERRIÈRE
                    // le remplissage — sinon il mange la lettre.
                    stroke: 'var(--mantine-color-body)',
                    strokeWidth: 3,
                    paintOrder: 'stroke',
                    pointerEvents: 'none',
                  }}
                >
                  {p.libelle.length > 24 ? `${p.libelle.slice(0, 23)}…` : p.libelle}
                </text>
              )}
            </g>
          ))}
        </Box>
      </Paper>

      <Group gap="lg" justify="space-between">
        <Group gap="md">
          {(['moi', 'oeuvre', 'personne', 'voisin'] as const).map((t) => (
            <Group key={t} gap={6}>
              <Box w={10} h={10} style={{ borderRadius: 5, background: COULEURS[t] }} />
              <Text size="xs" c="dimmed">
                {{ moi: 'le membre', oeuvre: 'ses œuvres', personne: 'acteurs et réalisateurs', voisin: 'voisins' }[t]}
              </Text>
            </Group>
          ))}
        </Group>
        {graphe.data.plafonds && (
          <Text size="xs" c="dimmed">
            au plus {graphe.data.plafonds.oeuvres} œuvres, {graphe.data.plafonds.personnesParOeuvre}{' '}
            personnes par œuvre, {graphe.data.plafonds.voisins} voisins
          </Text>
        )}
      </Group>
    </Stack>
  )
}

function compteLiens(aretes: GrapheArete[], id: string): number {
  return aretes.filter((a) => a.de === id || a.vers === id).length
}

/** Ce qu'on nomme, et ce qu'on laisse en pastille.
 *
 *  Deux règles, et la même raison derrière : une étiquette qui n'apprend rien
 *  coûte de la place à celles qui apprennent quelque chose.
 *
 *  * une personne qui ne relie qu'une œuvre ne dit rien — celle qui en relie
 *    deux est exactement ce qu'on cherche à voir ;
 *  * un voisin sans pseudo s'appellerait « membre 32120 », ce qui n'est pas un
 *    nom. Son survol le donne, le dessin s'en passe.
 */
function etiquetable(p: GrapheNoeud, aretes: GrapheArete[]): boolean {
  if (p.type === 'personne') return compteLiens(aretes, p.id) > 1
  if (p.type === 'voisin') return !p.libelle.startsWith('membre ')
  return true
}
