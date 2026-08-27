// La pile de cartes de l'onglet Suggestions — le geste du composant V1.
//
// Le design vient de `home-module-1.gif` et de `block-tinder.css` de la V1 :
// une pile d'affiches légèrement tournées, celle du dessus qu'on jette dans
// une direction, et trois demi-disques aux bords qui disent laquelle fait
// quoi. Les chiffres sont ceux de la V1 — seuil à 0,25 du plateau, rotation
// proportionnelle jusqu'à 45°, sortie en 400 ms — parce que c'est ce qui
// donne la sensation d'origine, et qu'elle avait été réglée à la main.
//
// Trois différences assumées avec la V1 :
//
// * **Pointer Events** plutôt que Hammer.js : les quatre gestes tiennent en
//   trente lignes natives, et une dépendance de moins est une dépendance de
//   moins. Souris, doigt et stylet passent par le même chemin.
// * **Le clavier fonctionne.** Les flèches classent, la barre passe. Une
//   interface qui ne s'utilise qu'en glissant exclut ceux qui ne glissent
//   pas, et ça n'était pas acceptable.
// * **La raison de la suggestion est affichée**, sous le titre : notre moteur
//   sait pourquoi il propose, la V1 ne le disait pas.

import { useEffect, useRef, useState } from 'react'

import { urlAffiche } from './api'
import { useTextes } from './textes'
import type { Statut, Suggestion } from './types'

/** Les quatre directions du plateau, et ce qu'elles décident. */
type Geste = 'aime' | 'aime_pas' | 'a_voir' | 'passer'

// Le seuil de la V1 : un quart du plateau franchi vaut décision. En dessous,
// la carte revient à sa place — un frôlement ne classe pas une œuvre.
const SEUIL = 0.25

// La durée de la sortie, celle de la V1. La carte suivante ne prend sa place
// qu'après, sinon la pile sauterait sous le doigt.
const SORTIE_MS = 400

// En dessous de ce reste, on demande la suite : la pile ne doit jamais se
// vider sous les doigts de qui enchaîne les gestes.
const RESTE_AVANT_RECHARGE = 3

// Ce que la pile montre derrière la carte du dessus. Cinq comme en V1 : au-delà
// on empile des affiches que personne ne distingue.
const PROFONDEUR = 5

const GESTES: Record<Geste, { classe: string; statut: Statut | null }> = {
  aime: { classe: 'sortie-aime', statut: 'aime' },
  aime_pas: { classe: 'sortie-aime-pas', statut: 'aime_pas' },
  a_voir: { classe: 'sortie-a-voir', statut: 'a_voir' },
  // « Passer » ne classe rien : l'œuvre n'est ni aimée ni écartée, on ne veut
  // simplement pas se prononcer maintenant.
  passer: { classe: 'sortie-passer', statut: null },
}

export function PileSuggestions({
  suggestions,
  masques = [],
  sur = [],
  type,
  explication,
  onClasser,
  onOuvrir,
  onRecharger,
}: {
  suggestions: Suggestion[]
  /** Les genres masqués (« moins de dessins animés »). La pile purge sa file
   *  locale elle-même : attendre le rechargement laisserait la carte du
   *  genre qu'on vient de masquer sous le doigt. */
  masques?: string[]
  /** Les plateformes choisies (« sur Netflix ») — même purge, en positif. */
  sur?: string[]
  /** « Série », « Film », « Livre » — affiché sous le titre. */
  type: string
  /** La phrase qui dit pourquoi cette œuvre est proposée. */
  explication: (suggestion: Suggestion) => string
  onClasser: (oeuvreId: number, statut: Statut) => void
  onOuvrir: (identifiant: number, oeuvreId: number | null) => void
  /** La pile s'épuise : il faut d'autres cartes. */
  onRecharger: () => void
}) {
  // La file locale : la pile consomme sa propre liste, sans attendre un
  // rechargement à chaque geste — sinon la pile se réordonnerait sous la main.
  const t = useTextes()
  const [file, setFile] = useState<Suggestion[]>(suggestions)
  const [glisse, setGlisse] = useState<{ x: number; y: number } | null>(null)
  const [sortie, setSortie] = useState<Geste | null>(null)
  const plateau = useRef<HTMLDivElement>(null)
  const depart = useRef<{ x: number; y: number } | null>(null)
  const demande = useRef(false)

  // Les nouvelles cartes s'ajoutent à la suite, sans jeter ce qui reste : on
  // ne veut pas qu'un rechargement fasse disparaître la carte qu'on regarde.
  //
  // Le droit de redemander ne se rouvre QUE si la réponse a apporté du neuf.
  // Sans cette condition, une pile courte bouclait : moins de trois cartes →
  // recharge → le moteur rend les mêmes œuvres → rien de neuf mais le
  // verrou sautait → recharge… Mesuré à l'écran : des centaines de requêtes
  // identiques en quelques secondes. Un geste du visiteur rouvre le droit
  // (voir `jeter`) — lui change réellement la donne, il ajoute une exclusion.
  useEffect(() => {
    setFile((restantes) => {
      const connues = new Set(restantes.map((s) => s.oeuvreId))
      const neuves = suggestions.filter((s) => !connues.has(s.oeuvreId))
      if (neuves.length > 0) demande.current = false
      return [...restantes, ...neuves]
    })
  }, [suggestions])

  // Le masquage et le choix de plateformes purgent la file SUR PLACE : la
  // carte écartée disparaît au clic, et le rechargement — qui suit — comble
  // avec autre chose.
  useEffect(() => {
    if (masques.length === 0 && sur.length === 0) return
    setFile((restantes) =>
      restantes.filter(
        (suggestion) =>
          !(suggestion.genres ?? []).some((genre) => masques.includes(genre)) &&
          (sur.length === 0 ||
            (suggestion.plateformes ?? []).some((plateforme) => sur.includes(plateforme))),
      ),
    )
  }, [masques, sur])

  useEffect(() => {
    if (file.length <= RESTE_AVANT_RECHARGE && !demande.current) {
      demande.current = true
      onRecharger()
    }
  }, [file.length, onRecharger])

  const dessus = file[0]

  const jeter = (geste: Geste) => {
    if (!dessus || sortie) return
    setSortie(geste)
    setGlisse(null)
    const { statut } = GESTES[geste]
    if (statut) onClasser(dessus.oeuvreId, statut)
    // La carte part, PUIS la file avance : l'animation doit se voir.
    window.setTimeout(() => {
      setFile((restantes) => restantes.slice(1))
      setSortie(null)
      // Un geste rouvre le droit de recharger : la donne a changé — une
      // œuvre de plus est classée ou passée, la prochaine réponse peut
      // différer de la précédente.
      demande.current = false
    }, SORTIE_MS)
  }

  // --- Le geste ------------------------------------------------------------

  const auDepart = (evenement: React.PointerEvent) => {
    if (sortie) return
    depart.current = { x: evenement.clientX, y: evenement.clientY }
    evenement.currentTarget.setPointerCapture(evenement.pointerId)
  }

  const auMouvement = (evenement: React.PointerEvent) => {
    if (!depart.current) return
    setGlisse({
      x: evenement.clientX - depart.current.x,
      y: evenement.clientY - depart.current.y,
    })
  }

  // Le navigateur reprend le doigt (il a décidé que c'était un défilement) :
  // on ABANDONNE, on ne classe pas. Brancher `pointercancel` sur le
  // relâchement classait « passer » — voire « j'ai vu & aimé » — au premier
  // doigt qui remontait la page depuis la carte.
  const auAnnulation = () => {
    depart.current = null
    setGlisse(null)
  }

  const auRelachement = (evenement: React.PointerEvent) => {
    if (!depart.current) return
    // L'écart se lit sur l'événement de RELÂCHEMENT, pas sur le dernier
    // mouvement reçu : un geste vif — un doigt qui balaie, une souris qu'on
    // lance — produit très peu de `pointermove`, parfois aucun, et se
    // retrouvait ignoré. Mesuré : un glissé complet ne classait rien.
    const ecart = {
      x: evenement.clientX - depart.current.x,
      y: evenement.clientY - depart.current.y,
    }
    const cadre = plateau.current
    const partX = cadre ? ecart.x / cadre.clientWidth : 0
    const partY = cadre ? ecart.y / cadre.clientHeight : 0
    depart.current = null

    // L'axe le plus franchi décide — un geste en diagonale ne doit pas
    // déclencher deux classements ni le mauvais.
    if (Math.abs(partX) > Math.abs(partY)) {
      if (partX > SEUIL) return jeter('a_voir')
      if (partX < -SEUIL) return jeter('aime_pas')
    } else {
      if (partY < -SEUIL) return jeter('aime')
      if (partY > SEUIL) return jeter('passer')
    }
    // Sous le seuil : la carte revient. Un frôlement ne classe rien.
    setGlisse(null)
  }

  const auClavier = (evenement: React.KeyboardEvent) => {
    const touches: Record<string, Geste> = {
      ArrowUp: 'aime',
      ArrowLeft: 'aime_pas',
      ArrowRight: 'a_voir',
      ArrowDown: 'passer',
      ' ': 'passer',
    }
    const geste = touches[evenement.key]
    if (geste) {
      evenement.preventDefault()
      jeter(geste)
    }
  }

  if (!dessus) {
    return <p className="fivo-message">{t.dit('pile.vide')}</p>
  }

  // La rotation suit le geste, comme en V1 : proportionnelle à la part de
  // plateau franchie, jusqu'à 45 degrés.
  const cadre = plateau.current
  const partX = glisse && cadre ? glisse.x / cadre.clientWidth : 0
  const angle = partX * 45
  const styleDessus = glisse
    ? {
        transform: `translate(-50%, -50%) translate(${glisse.x}px, ${glisse.y}px) rotate(${angle}deg)`,
        transition: 'none' as const,
      }
    : undefined

  return (
    <div className="fivo-plateau" ref={plateau}>
      {/* Les trois demi-disques de la V1. Cliquables : le geste n'est pas
          obligatoire, et il ne l'était pas non plus en V1. */}
      <button
        type="button"
        className="fivo-aide fivo-aide-aime-pas"
        onClick={() => jeter('aime_pas')}
      >
        <span className="fivo-aide-fleche" aria-hidden="true">
          ←
        </span>
        <span className="fivo-aide-texte">{t.dit('geste.aime_pas')}</span>
      </button>
      <button type="button" className="fivo-aide fivo-aide-aime" onClick={() => jeter('aime')}>
        <span className="fivo-aide-fleche" aria-hidden="true">
          ↑
        </span>
        <span className="fivo-aide-texte">{t.dit('geste.aime')}</span>
      </button>
      <button type="button" className="fivo-aide fivo-aide-a-voir" onClick={() => jeter('a_voir')}>
        <span className="fivo-aide-fleche" aria-hidden="true">
          →
        </span>
        <span className="fivo-aide-texte">{t.dit('geste.a_voir')}</span>
      </button>

      {/* La pile : la carte du dessus en dernier dans le DOM, comme en V1 —
          l'ordre du document fait l'empilement, sans z-index à tenir. */}
      {file
        .slice(0, PROFONDEUR)
        .reverse()
        .map((suggestion, rang, montrees) => {
          const estDessus = rang === montrees.length - 1
          const profondeur = montrees.length - 1 - rang
          const affiche = urlAffiche(suggestion.affiche, 'w342')
          return (
            <article
              key={suggestion.oeuvreId}
              className={[
                'fivo-carte-pile',
                `fivo-carte-rang-${profondeur}`,
                estDessus && sortie ? GESTES[sortie].classe : '',
                estDessus && suggestion.corrobore ? 'fivo-carte-corroboree' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              style={estDessus ? styleDessus : undefined}
              onPointerDown={estDessus ? auDepart : undefined}
              onPointerMove={estDessus ? auMouvement : undefined}
              onPointerUp={estDessus ? auRelachement : undefined}
              onPointerCancel={estDessus ? auAnnulation : undefined}
              onKeyDown={estDessus ? auClavier : undefined}
              tabIndex={estDessus ? 0 : -1}
              aria-hidden={!estDessus}
              aria-label={
                estDessus
                  ? t.dit('pile.aria', { titre: suggestion.titre ?? t.dit('carte.cette_oeuvre') })
                  : undefined
              }
            >
              {affiche ? (
                <img className="fivo-pile-affiche" src={affiche} alt="" draggable={false} />
              ) : (
                <div className="fivo-pile-affiche fivo-pile-affiche-vide" aria-hidden="true" />
              )}
              {/* Le texte n'appartient qu'à la carte du dessus. Le laisser sur
                  les cartes du dessous le faisait traverser celle du dessus —
                  vu à l'écran — et la V1 ne montre elle aussi qu'un titre. */}
              {estDessus && (
              <div className="fivo-pile-texte">
                <h3 dir="auto">{suggestion.titre ?? t.dit('carte.sans_titre')}</h3>
                <p className="fivo-pile-meta">
                  <strong>{suggestion.annee ?? t.dit('carte.annee_inconnue')}</strong> ·{' '}
                  <strong>{type}</strong>
                </p>
                <p
                  className={`fivo-pile-raison${
                    suggestion.corrobore ? ' fivo-pile-raison-forte' : ''
                  }`}
                >
                  {suggestion.corrobore && <span aria-hidden="true">✦ </span>}
                  {explication(suggestion)}
                </p>
                {/* Le ⓘ de la V1 : il ouvrait le synopsis, il ouvre ici la
                    fiche entière — saisons, distribution, gestes compris. */}
                <button
                  type="button"
                  className="fivo-pile-info"
                  onPointerDown={(evenement) => evenement.stopPropagation()}
                  onClick={() => onOuvrir(suggestion.id, suggestion.oeuvreId)}
                  title={t.dit('pile.voir_fiche')}
                >
                  ⓘ
                </button>
              </div>
              )}
            </article>
          )
        })}

      {/* « ▶︎▶︎ PASSER » de la V1, en pied de plateau. */}
      <button type="button" className="fivo-aide-passer" onClick={() => jeter('passer')}>
        <span className="fivo-passer-fleches" aria-hidden="true">
          ▶︎▶︎
        </span>{' '}
        {t.dit('pile.passer')}
      </button>
    </div>
  )
}
