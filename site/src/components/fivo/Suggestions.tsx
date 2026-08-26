// L'onglet Mes suggestions : ce que le moteur propose, et toujours pourquoi.
//
// Le panneau **reste monté** quand on regarde la recherche (voir
// `FivoSuggest`) : revenir ici ne doit pas rejouer un chargement pour
// réafficher ce qu'on venait de lire. D'où la règle de rafraîchissement,
// tenue par `charge` : on ne recharge que si quelque chose a bougé depuis le
// dernier affichage — un univers changé, ou un classement posé entre-temps —
// et **seulement quand l'onglet est visible**. Classer trois œuvres dans la
// recherche déclenche donc UNE requête à la bascule, pas trois en arrière-plan.
//
// C'est ce qui donne le comportement attendu : on cherche, on classe, on
// bascule — et les suggestions arrivent enrichies de ce qu'on vient de faire.
//
// DEUX PRÉSENTATIONS, et elles ne servent pas la même chose. La **pile** —
// celle de la V1 — fait décider vite : une œuvre à la fois, un geste, la
// suivante. La **liste** fait comparer : on voit dix propositions côte à côte
// avec leur raison, on choisit. Le choix est retenu, parce que c'est une
// habitude, pas une humeur.

import { UnstyledButton } from '@mantine/core'
import { useEffect, useRef, useState } from 'react'

import { chargerSuggestions } from './api'
import { CarteOeuvre } from './CarteOeuvre'
import { retenir, retenu } from './memoire'
import { PileSuggestions } from './PileSuggestions'
import { useTextes } from './textes'
import type { Textes } from '../../i18n/textes'
import { type Statut, type Suggestion, type UniversSlug } from './types'

// Les sources du moteur ne disent pas la même chose, et le visiteur doit
// pouvoir les distinguer : « des gens comme vous ont aimé » n'est pas « ça
// ressemble ». Une suggestion inexpliquée ressemble à de la publicité.
//
// La CORROBORATION passe devant tout : quand le contenu et la communauté
// désignent la même œuvre, c'est la meilleure raison qu'on sache donner, et
// c'est aussi ce que le moteur a le plus fortement classé.
type Vue = 'pile' | 'liste'

const CLE_VUE = 'fivo-vue-suggestions'

function vueInitiale(): Vue {
  return retenu(CLE_VUE) === 'liste' ? 'liste' : 'pile'
}

function expliquer(suggestion: Suggestion, t: Textes): string {
  const voisins = suggestion.voisins ?? 0
  if (suggestion.corrobore) {
    return t.compte(voisins, 'raison.corrobore_un', 'raison.corrobore')
  }
  if (suggestion.source === 'voisins') {
    return t.compte(voisins, 'raison.voisins_un', 'raison.voisins')
  }
  if (suggestion.source === 'proche') {
    return suggestion.distance != null
      ? t.dit('raison.proche_distance', { distance: t.nombre(Number(suggestion.distance.toFixed(2))) })
      : t.dit('raison.proche')
  }
  // Les affinités : on nomme les genres partagés quand il y en a. Sinon la
  // correspondance s'est faite sur un nom (acteur, réalisateur, auteur) et on
  // reste neutre plutôt que d'affirmer lequel — l'index ne le dit pas.
  if (suggestion.communs.length > 0) {
    return t.dit('raison.communs', { communs: suggestion.communs.slice(0, 3).join(', ') })
  }
  return t.dit('raison.defaut')
}

export function Suggestions({
  univers,
  statuts,
  versionSignaux,
  actif,
  onOuvrir,
  onClasser,
  onDeclasser,
}: {
  univers: UniversSlug
  /** Les classements de la session, par pivot. La LISTE s'en sert pour
   *  rallumer ses boutons ; la pile n'en a pas besoin — une carte jetée
   *  quitte la pile. */
  statuts: Record<number, Statut>
  /** Incrémentée à chaque geste de classement — le déclencheur du rechargement. */
  versionSignaux: number
  /** L'onglet est-il celui qu'on regarde ? Le panneau reste monté quand il ne
   *  l'est pas : il garde sa liste, et ne va pas la rafraîchir pour personne. */
  actif: boolean
  onOuvrir: (identifiant: number, oeuvreId: number | null) => void
  onClasser: (oeuvreId: number, univers: UniversSlug, statut: Statut) => void
  onDeclasser: (oeuvreId: number) => void
}) {
  const t = useTextes()
  const [items, setItems] = useState<Suggestion[]>([])
  const [raison, setRaison] = useState<string | null>(null)
  const [etat, setEtat] = useState<'en-cours' | 'servi' | 'erreur'>('en-cours')
  // Les classements faits DANS la pile. Ils font monter `versionSignaux`
  // comme les autres, mais ne doivent pas provoquer de rechargement : la pile
  // gère sa file elle-même, et refaire la requête à chaque carte jetée
  // réordonnerait ce qui reste sous la main. On les retranche donc de la
  // version qu'on compare.
  const absorbees = useRef(0)
  // Les demandes de la pile quand elle s'épuise — le seul rechargement
  // qu'elle déclenche.
  const [recharges, setRecharges] = useState(0)
  // La vue démarre sur la pile puis suit le choix retenu, lu après le montage
  // — la page est construite à l'avance, le navigateur de qui la reçoit n'est
  // pas connu au build.
  const [vue, setVue] = useState<Vue>('pile')

  useEffect(() => {
    setVue(vueInitiale())
  }, [])

  const choisirVue = (choisie: Vue) => {
    setVue(choisie)
    retenir(CLE_VUE, choisie)
  }
  // Ce que la liste affichée reflète déjà. Une référence plutôt qu'un état :
  // elle ne décide d'aucun rendu, elle évite seulement de recharger ce qui
  // est à jour — la mettre en `useState` relancerait l'effet pour rien.
  const charge = useRef<{
    univers: UniversSlug
    version: number
    recharges: number
  } | null>(null)

  useEffect(() => {
    if (!actif) return
    // La version « utile » ignore ce que la pile a absorbé : seuls les
    // classements venus d'ailleurs (l'onglet Recherche, la fiche) justifient
    // de rejouer la requête.
    const utile = versionSignaux - absorbees.current
    const dejaVu =
      charge.current !== null &&
      charge.current.univers === univers &&
      charge.current.version === utile &&
      charge.current.recharges === recharges
    if (dejaVu) return

    let abandonne = false
    setEtat('en-cours')
    chargerSuggestions(univers)
      .then((reponse) => {
        if (abandonne) return
        setItems(reponse.items)
        setRaison(reponse.raison)
        setEtat('servi')
        charge.current = { univers, version: utile, recharges }
      })
      .catch(() => {
        if (!abandonne) setEtat('erreur')
      })
    return () => {
      abandonne = true
    }
  }, [univers, versionSignaux, actif, recharges])

  // Les suggestions déjà classées pendant la consultation restent affichées
  // (avec leur bouton allumé) jusqu'au prochain rechargement : les faire
  // disparaître sous le doigt serait déroutant.
  return (
    <div>
      {etat === 'erreur' && (
        <p className="fivo-message fivo-erreur">{t.dit('suggestions.erreur')}</p>
      )}
      {etat === 'servi' && (raison === 'aucune_session' || raison === 'aucun_aime') && (
        <p className="fivo-message">{t.dit('suggestions.commencez')}</p>
      )}
      {etat === 'servi' && raison === 'aucun_resultat' && (
        <p className="fivo-message">{t.dit('suggestions.aucun_resultat')}</p>
      )}

      {items.length > 0 && (
        <>
          {/* Le choix de présentation. Deux boutons plutôt qu'un interrupteur :
              on veut voir les deux possibilités, pas devoir deviner l'état
              courant d'une bascule. */}
          <div className="fivo-vues" role="group" aria-label={t.dit('vue.groupe')}>
            <UnstyledButton
              className={`fivo-vue${vue === 'pile' ? ' actif' : ''}`}
              aria-pressed={vue === 'pile'}
              onClick={() => choisirVue('pile')}
              title={t.dit('vue.pile_titre')}
            >
              <span aria-hidden="true">▤</span> {t.dit('vue.pile')}
            </UnstyledButton>
            <UnstyledButton
              className={`fivo-vue${vue === 'liste' ? ' actif' : ''}`}
              aria-pressed={vue === 'liste'}
              onClick={() => choisirVue('liste')}
              title={t.dit('vue.liste_titre')}
            >
              <span aria-hidden="true">☰</span> {t.dit('vue.liste')}
            </UnstyledButton>
          </div>

          {vue === 'pile' ? (
            <PileSuggestions
              suggestions={items}
              type={t.dit(`type.${univers}`)}
              explication={(suggestion) => expliquer(suggestion, t)}
              onClasser={(oeuvreId, statut) => {
                // Le geste de la pile est absorbé : il ne doit pas rejouer la
                // requête et réordonner ce qui reste (voir `absorbees`).
                absorbees.current += 1
                onClasser(oeuvreId, univers, statut)
              }}
              onOuvrir={onOuvrir}
              onRecharger={() => setRecharges((tour) => tour + 1)}
            />
          ) : (
            // La liste garde ses cartes classées, boutons allumés : ici on
            // compare, et faire disparaître ce qu'on vient de classer ferait
            // sauter la ligne qu'on lisait. Le geste est absorbé de la même
            // façon — c'est à la bascule d'onglet que la liste se renouvelle.
            <div className="fivo-liste">
              {items.map((suggestion) => (
                <CarteOeuvre
                  key={suggestion.oeuvreId}
                  titre={suggestion.titre}
                  annee={suggestion.annee}
                  type={t.dit(`type.${univers}`)}
                  affiche={suggestion.affiche}
                  explication={expliquer(suggestion, t)}
                  fort={suggestion.corrobore}
                  statutActuel={statuts[suggestion.oeuvreId] ?? null}
                  classable
                  onOuvrir={() => onOuvrir(suggestion.id, suggestion.oeuvreId)}
                  onClasser={(statut) => {
                    absorbees.current += 1
                    onClasser(suggestion.oeuvreId, univers, statut)
                  }}
                  onDeclasser={() => {
                    absorbees.current += 1
                    onDeclasser(suggestion.oeuvreId)
                  }}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
