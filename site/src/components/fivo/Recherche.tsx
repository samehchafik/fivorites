// L'onglet Recherche : la frappe débouncée, les filtres, les cartes.
//
// Le débounce est court (150 ms) et chaque frappe ANNULE la requête
// précédente (AbortController) : c'est ce qui garantit que la liste affichée
// correspond toujours au texte du champ, jamais à une réponse en retard.
//
// Le panneau **reste monté** quand on regarde les suggestions (voir
// `FivoSuggest`) : la frappe, les filtres, les cartes et la position de
// défilement survivent à la bascule — on retrouve sa recherche là où on l'a
// laissée. Caché, il ne cherche pas : un univers changé pendant qu'on lit les
// suggestions n'est rattrapé qu'au retour, et une seule fois.
//
// La liste se PAGINE. Elle rendait douze cartes sans rien dire de la suite,
// ce qui laissait croire que le catalogue s'arrêtait là ; elle annonce
// maintenant son total et se prolonge d'un bouton, en ajoutant à la suite
// plutôt qu'en remplaçant — on ne perd pas ce qu'on lisait.

import { TextInput } from '@mantine/core'
import { useEffect, useRef, useState } from 'react'

import { chargerFiltres, rechercher } from './api'
import { CarteOeuvre } from './CarteOeuvre'
import { BarreFiltres } from './BarreFiltres'
import {
  TYPE_LABELS,
  type Carte,
  type GroupeFiltre,
  type Statut,
  type UniversSlug,
} from './types'

const DEBOUNCE_MS = 150
const FRAPPE_MIN = 2

export function Recherche({
  univers,
  langue,
  statuts,
  actif,
  onOuvrir,
  onClasser,
  onDeclasser,
}: {
  univers: UniversSlug
  /** La langue de qui cherche : elle restreint les titres cherchés ET ceux
   *  affichés. Sans elle, la liste mêlait quarante-cinq langues. */
  langue: string
  /** Les classements de la session, par pivot — pour rallumer les boutons. */
  statuts: Record<number, Statut>
  /** L'onglet est-il celui qu'on regarde ? Caché, le panneau garde tout et
   *  ne cherche rien. */
  actif: boolean
  /** Ouvre la fiche : la clé de vignette, et le pivot pour les boutons. */
  onOuvrir: (identifiant: number, oeuvreId: number | null) => void
  onClasser: (oeuvreId: number, univers: UniversSlug, statut: Statut) => void
  onDeclasser: (oeuvreId: number) => void
}) {
  const [texte, setTexte] = useState('')
  const [cartes, setCartes] = useState<Carte[]>([])
  const [etat, setEtat] = useState<'repos' | 'en-cours' | 'servi' | 'erreur'>('repos')
  const [total, setTotal] = useState(0)
  const [approche, setApproche] = useState(false)
  const [encore, setEncore] = useState(false)
  const [page, setPage] = useState(1)
  const [suite, setSuite] = useState(false)

  const [groupes, setGroupes] = useState<GroupeFiltre[]>([])
  // Les valeurs cochées, par dimension : `{genres: [...], plateformes: [...]}`.
  const [choisis, setChoisis] = useState<Record<string, string[]>>({})
  const [deplies, setDeplies] = useState<string[]>([])

  // Ce que les cartes affichées reflètent déjà — même rôle que dans
  // `Suggestions` : revenir sur l'onglet ne doit pas rejouer la requête qui
  // rendrait exactement la liste qui est là. Les filtres en font partie : les
  // cocher est une nouvelle recherche, pas un nouvel affichage.
  const charge = useRef<{
    texte: string
    univers: UniversSlug
    filtres: string
    langue: string
  } | null>(null)

  // Les groupes de filtres, rechargés à chaque changement d'univers ET de
  // langue : les plateformes sont indexées par pays, donc « Netflix » en
  // France n'est pas la même liste que « Shahid » en Arabie saoudite. En
  // échec (ES absent), la barre disparaît — la recherche marche toujours.
  useEffect(() => {
    let abandonne = false
    setChoisis({})
    setDeplies([])
    chargerFiltres(univers, langue)
      .then((reponse) => {
        if (!abandonne) setGroupes(reponse.groupes)
      })
      .catch(() => {
        if (!abandonne) setGroupes([])
      })
    return () => {
      abandonne = true
    }
  }, [univers, langue])

  // La recherche : première page à chaque changement de frappe, de filtre ou
  // d'univers ; page suivante quand on demande la suite.
  useEffect(() => {
    const propre = texte.trim()
    // La signature de ce qui est coché, toutes dimensions confondues : c'est
    // elle qui dit si la recherche affichée est encore la bonne.
    const signature = JSON.stringify(
      Object.fromEntries(Object.entries(choisis).map(([c, v]) => [c, [...v].sort()])),
    )
    if (propre.length < FRAPPE_MIN) {
      setCartes([])
      setEtat('repos')
      setTotal(0)
      setEncore(false)
      charge.current = null
      return
    }
    if (!actif) return
    const dejaVu =
      charge.current?.texte === propre &&
      charge.current.univers === univers &&
      charge.current.filtres === signature &&
      charge.current.langue === langue
    if (dejaVu && !suite) return

    const demandee = suite ? page + 1 : 1
    setEtat('en-cours')
    const controleur = new AbortController()
    const minuterie = setTimeout(async () => {
      try {
        const reponse = await rechercher(univers, propre, {
          page: demandee,
          filtres: choisis,
          langue,
          signal: controleur.signal,
        })
        // On AJOUTE à la suite pour une page suivante, on remplace sinon :
        // charger plus ne doit pas faire sauter ce qu'on lisait.
        setCartes((actuelles) =>
          demandee > 1 ? [...actuelles, ...reponse.items] : reponse.items,
        )
        setTotal(reponse.total)
        setApproche(reponse.totalApproche)
        setEncore(reponse.encore)
        setPage(demandee)
        setEtat('servi')
        charge.current = { texte: propre, univers, filtres: signature, langue }
      } catch {
        if (!controleur.signal.aborted) setEtat('erreur')
      } finally {
        setSuite(false)
      }
    }, demandee > 1 ? 0 : DEBOUNCE_MS)
    return () => {
      clearTimeout(minuterie)
      controleur.abort()
    }
  }, [texte, univers, actif, choisis, suite, page, langue])

  const basculer = (champ: string, valeur: string) =>
    setChoisis((actuels) => {
      const cochees = actuels[champ] ?? []
      const suivantes = cochees.includes(valeur)
        ? cochees.filter((v) => v !== valeur)
        : [...cochees, valeur]
      // Une dimension sans valeur cochée sort de la carte : elle ne doit pas
      // partir en paramètre vide.
      const suivants = { ...actuels }
      if (suivantes.length) suivants[champ] = suivantes
      else delete suivants[champ]
      return suivants
    })

  return (
    <div>
      <TextInput
        className="fivo-champ"
        type="search"
        size="md"
        radius="xl"
        value={texte}
        onChange={(evenement) => setTexte(evenement.currentTarget.value)}
        placeholder="Un titre, un genre, un acteur, un auteur… (« Dune », « policier », « Spielberg »)"
        aria-label="Rechercher une œuvre"
        autoComplete="off"
      />

      <BarreFiltres
        groupes={groupes}
        choisis={choisis}
        deplies={deplies}
        onBasculer={basculer}
        onDeplier={(champ) => setDeplies((actuels) => [...actuels, champ])}
        onEffacer={() => setChoisis({})}
      />

      {etat === 'repos' && (
        <p className="fivo-message">
          Cherchez les œuvres qui vous ont marqué, puis classez-les : c'est comme ça que FIVO
          apprend vos goûts.
        </p>
      )}
      {etat === 'erreur' && (
        <p className="fivo-message fivo-erreur">
          La recherche ne répond pas — réessayez dans un instant.
        </p>
      )}
      {etat === 'servi' && cartes.length === 0 && (
        <p className="fivo-message">
          Rien trouvé pour « {texte.trim()} »
          {Object.keys(choisis).length > 0 ? ' avec ces filtres' : ''}. Essayez autrement ?
        </p>
      )}

      {cartes.length > 0 && (
        <p className="fivo-compte">
          {cartes.length} sur {approche ? `plus de ${total}` : total}
        </p>
      )}

      <div className="fivo-liste" aria-busy={etat === 'en-cours'}>
        {cartes.map((carte) => (
          <CarteOeuvre
            key={carte.id}
            titre={carte.titre ?? carte.titreOriginal}
            annee={carte.annee}
            type={TYPE_LABELS[univers]}
            affiche={carte.affiche}
            genres={carte.genres}
            synopsis={carte.synopsis}
            note={carte.note}
            statutActuel={carte.oeuvreId != null ? (statuts[carte.oeuvreId] ?? null) : null}
            classable={carte.oeuvreId != null}
            onOuvrir={() => onOuvrir(carte.id, carte.oeuvreId)}
            onClasser={(statut) => {
              if (carte.oeuvreId != null) onClasser(carte.oeuvreId, univers, statut)
            }}
            onDeclasser={() => {
              if (carte.oeuvreId != null) onDeclasser(carte.oeuvreId)
            }}
          />
        ))}
      </div>

      {encore && (
        <button
          type="button"
          className="fivo-suite"
          disabled={etat === 'en-cours'}
          onClick={() => setSuite(true)}
        >
          {etat === 'en-cours' ? 'Chargement…' : 'Charger plus'}
        </button>
      )}
    </div>
  )
}
