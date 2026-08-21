import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ActionIcon,
  Alert,
  Box,
  Center,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import {
  IconAlertTriangle,
  IconFocusCentered,
  IconZoomIn,
  IconZoomOut,
} from '@tabler/icons-react'

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
  suggestion: 'var(--mantine-color-pink-5)',
}

const LIBELLES: Record<GrapheNoeud['type'], string> = {
  moi: 'le membre',
  oeuvre: 'ses œuvres',
  personne: 'acteurs et réalisateurs',
  voisin: 'voisins',
  suggestion: 'ce qu\'ils citent et pas lui',
}

const RAYONS: Record<GrapheNoeud['type'], number> = {
  moi: 13,
  oeuvre: 9,
  personne: 5,
  voisin: 7,
  suggestion: 8,
}

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
  suggestion: 2,
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

interface Cadre {
  x: number
  y: number
  l: number
  h: number
}

export function GrapheMembre({ id }: { id: number }) {
  const svg = useRef<SVGSVGElement>(null)
  // La fenêtre regardée, en coordonnées du dessin. Zoomer et déplacer, c'est
  // la bouger — pas transformer les nœuds : les épaisseurs de trait et les
  // tailles de texte restent alors constantes à l'écran, ce qu'un `transform`
  // sur un groupe ne donne pas.
  const [vue, setVue] = useState<Cadre | null>(null)
  const glisse = useRef<{ x: number; y: number; vue: Cadre } | null>(null)

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
      cadre: {
        x: Math.min(...xs) - marge,
        y: Math.min(...ys) - marge,
        l: Math.max(...xs) - Math.min(...xs) + 2 * marge,
        h: Math.max(...ys) - Math.min(...ys) + 2 * marge,
      },
    }
  }, [graphe.data, id])

  // Le cadre d'origine dès que la disposition change, et à chaque changement
  // de membre : sans cela, ouvrir un second membre garderait le zoom du
  // premier, cadré sur un endroit qui n'a plus de sens.
  useEffect(() => {
    setVue(dispose ? { ...dispose.cadre } : null)
  }, [dispose])

  function zoomer(facteur: number, ancre?: { x: number; y: number }) {
    setVue((v) => {
      if (!v) return v
      // Bornes : au-delà, on ne lit plus rien — ni les étiquettes trop
      // petites, ni un nœud unique qui remplit l'écran.
      const l = Math.min(Math.max(v.l * facteur, 120), 6000)
      const h = (l / v.l) * v.h
      const cx = ancre?.x ?? v.x + v.l / 2
      const cy = ancre?.y ?? v.y + v.h / 2
      // Le point sous le curseur ne bouge pas : c'est ce qui rend le zoom à la
      // molette utilisable pour aller chercher un coin du dessin.
      return { x: cx - ((cx - v.x) * l) / v.l, y: cy - ((cy - v.y) * h) / v.h, l, h }
    })
  }

  /** Un point de l'écran vers les coordonnées du dessin. */
  function versDessin(e: { clientX: number; clientY: number }): { x: number; y: number } | null {
    const boite = svg.current?.getBoundingClientRect()
    if (!boite || !vue) return null
    return {
      x: vue.x + ((e.clientX - boite.left) / boite.width) * vue.l,
      y: vue.y + ((e.clientY - boite.top) / boite.height) * vue.h,
    }
  }

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

  const { points, index } = dispose
  const cadre = vue ?? dispose.cadre

  return (
    <Stack gap="xs">
      <Paper withBorder p={0} style={{ overflow: 'hidden', position: 'relative' }}>
        <Group gap={4} style={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }}>
          <Tooltip label="Zoomer — ou la molette">
            <ActionIcon variant="default" size="sm" onClick={() => zoomer(1 / 1.3)}>
              <IconZoomIn size={15} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label="Dézoomer">
            <ActionIcon variant="default" size="sm" onClick={() => zoomer(1.3)}>
              <IconZoomOut size={15} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label="Tout revoir">
            <ActionIcon variant="default" size="sm" onClick={() => setVue({ ...dispose.cadre })}>
              <IconFocusCentered size={15} />
            </ActionIcon>
          </Tooltip>
        </Group>
        <Box
          component="svg"
          ref={svg}
          viewBox={`${cadre.x} ${cadre.y} ${cadre.l} ${cadre.h}`}
          preserveAspectRatio="xMidYMid meet"
          onWheel={(e: React.WheelEvent<SVGSVGElement>) => {
            // Pas de `preventDefault` : React attache l'écouteur en passif, il
            // serait sans effet et l'avertissement le dit. Le dessin ne
            // dépasse pas de son cadre, la page ne défile donc pas dessous.
            const ancre = versDessin(e)
            zoomer(e.deltaY > 0 ? 1.12 : 1 / 1.12, ancre ?? undefined)
          }}
          onPointerDown={(e: React.PointerEvent<SVGSVGElement>) => {
            if (!vue) return
            glisse.current = { x: e.clientX, y: e.clientY, vue }
            e.currentTarget.setPointerCapture(e.pointerId)
          }}
          onPointerMove={(e: React.PointerEvent<SVGSVGElement>) => {
            const depart = glisse.current
            const boite = svg.current?.getBoundingClientRect()
            if (!depart || !boite) return
            // Le déplacement est converti en unités du dessin : à fort zoom, un
            // pixel d'écran vaut moins qu'une unité, et le contraire de loin.
            setVue({
              ...depart.vue,
              x: depart.vue.x - ((e.clientX - depart.x) / boite.width) * depart.vue.l,
              y: depart.vue.y - ((e.clientY - depart.y) / boite.height) * depart.vue.h,
            })
          }}
          onPointerUp={(e: React.PointerEvent<SVGSVGElement>) => {
            glisse.current = null
            e.currentTarget.releasePointerCapture(e.pointerId)
          }}
          style={{
            width: '100%',
            height: 620,
            display: 'block',
            cursor: glisse.current ? 'grabbing' : 'grab',
            touchAction: 'none',
          }}
        >
          {graphe.data.aretes.map((a, i) => {
            const de = index.get(a.de)
            const vers = index.get(a.vers)
            if (!de || !vers) return null
            const role = a.type !== 'cite'
            const propose = traitSuggestion(index, a.vers)
            return (
              <line
                key={i}
                x1={de.x}
                y1={de.y}
                x2={vers.x}
                y2={vers.y}
                stroke={
                  propose
                    ? 'var(--mantine-color-pink-3)'
                    : role
                      ? 'var(--mantine-color-gray-4)'
                      : 'var(--mantine-color-gray-5)'
                }
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
                {p.voisins ? ` — citée par ${p.voisins} voisin(s)` : ''}
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
          {(['moi', 'oeuvre', 'personne', 'voisin', 'suggestion'] as const).map((t) => (
            <Group key={t} gap={6}>
              <Box w={10} h={10} style={{ borderRadius: 5, background: COULEURS[t] }} />
              <Text size="xs" c="dimmed">
                {LIBELLES[t]}
              </Text>
            </Group>
          ))}
        </Group>
        {graphe.data.plafonds && (
          <Text size="xs" c="dimmed">
            au plus {graphe.data.plafonds.oeuvres} œuvres, {graphe.data.plafonds.personnesParOeuvre}{' '}
            personnes par œuvre, {graphe.data.plafonds.voisins} voisins,{' '}
            {graphe.data.plafonds.suggestions} suggestions
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

/** Le trait d'une arête. Une suggestion se distingue de ce qui est déjà cité :
 *  c'est la seule couche qui propose au lieu de constater. */
function traitSuggestion(index: Map<string, GrapheNoeud>, vers: string): boolean {
  return index.get(vers)?.type === 'suggestion'
}
