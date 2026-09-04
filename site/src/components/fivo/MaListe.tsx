// L'onglet « Ma liste » : ce qui a été classé, en trois sections.
//
// Il manquait la moitié du contrat. On demandait au visiteur de dire ce qu'il
// avait vu et aimé, ce qu'il voulait voir, ce dont il ne voulait pas — et
// rien ne lui rendait jamais ces listes. Un geste dont on ne revoit pas la
// trace ressemble à un geste perdu.
//
// Trois différences avec les deux autres onglets, et elles sont voulues :
//
// * **tous les univers ensemble.** Ce qu'on a classé ne se range pas par
//   onglet : on cherche « ce que j'ai aimé », pas « les séries que j'ai
//   aimées ». Le type de chaque œuvre est écrit sur sa carte.
// * **les trois sections restent affichées** même vides — leur ordre dit ce
//   que le site attend de vous : à voir, vus & aimés, pas pour moi.
// * **rien ne disparaît sous la main.** Déclasser une œuvre ici la retire de
//   sa section au rechargement suivant, pas à l'instant du clic : voir la
//   ligne qu'on vient de toucher s'évaporer est déroutant.

import { useEffect, useRef, useState } from 'react'

import { chargerPalmares, listerSignaux } from './api'
import { CarteOeuvre } from './CarteOeuvre'
import { BandeFives, lirePalmaresLocaux } from './Fives'
import { useTextes } from './textes'
import type { CleTexte } from '../../i18n/textes'
import {
  type Compte,
  type Palmares,
  type Signal,
  type Statut,
  type UniversSlug,
} from './types'

// L'ordre des sections : ce qui reste à faire d'abord, ce qui est acquis
// ensuite, ce qui est écarté en dernier.
const SECTIONS: Array<{ statut: Statut; titre: CleTexte }> = [
  { statut: 'a_voir', titre: 'liste.a_voir' },
  { statut: 'aime', titre: 'liste.aime' },
  { statut: 'aime_pas', titre: 'liste.aime_pas' },
]

export function MaListe({
  langue,
  univers,
  compte,
  statuts,
  versionSignaux,
  actif,
  onOuvrir,
  onClasser,
  onDeclasser,
  onVoirFives,
}: {
  /** La langue : les titres de la liste se relisent dedans. */
  langue: string
  /** L'univers courant de l'îlot — le TOP 5 affiché est le sien. */
  univers: UniversSlug
  /** Le compte connecté, ou null : le TOP 5 se lit au serveur ou au brouillon. */
  compte: Compte | null
  /** Les classements de la session, par pivot — la source de vérité des
   *  boutons, tenue par `FivoSuggest`. La liste, elle, porte l'affichage. */
  statuts: Record<number, Statut>
  versionSignaux: number
  actif: boolean
  /** Ouvre la fiche — avec son univers, puisque la liste les mélange. */
  onOuvrir: (identifiant: number, oeuvreId: number, univers: UniversSlug) => void
  onClasser: (oeuvreId: number, univers: UniversSlug, statut: Statut) => void
  onDeclasser: (oeuvreId: number) => void
  /** « Modifier » le TOP 5 : l'îlot bascule sur l'onglet Mes fives. */
  onVoirFives: () => void
}) {
  const t = useTextes()
  const [items, setItems] = useState<Signal[]>([])
  const [etat, setEtat] = useState<'en-cours' | 'servi' | 'erreur'>('en-cours')
  // Les palmarès de l'univers courant — la première section de la maquette.
  // Rechargés à chaque ouverture de l'onglet : ils ont pu changer à côté.
  const [tops, setTops] = useState<Palmares[]>([])
  // Ce que la liste affichée reflète déjà — même règle que dans les deux
  // autres onglets : caché, le panneau ne recharge rien ; visible, il ne
  // recharge que si quelque chose a bougé.
  const charge = useRef<{ version: number; langue: string } | null>(null)

  useEffect(() => {
    if (!actif) return
    if (charge.current?.version === versionSignaux && charge.current.langue === langue) return
    let abandonne = false
    setEtat('en-cours')
    // Le rechargement n'arrive que si quelque chose a bougé : la liste
    // affichée est périmée, on la vide plutôt que de la laisser sous les
    // yeux pendant la requête.
    setItems([])
    listerSignaux(langue)
      .then((reponse) => {
        if (abandonne) return
        setItems(reponse.items)
        setEtat('servi')
        charge.current = { version: versionSignaux, langue }
      })
      .catch(() => {
        if (!abandonne) setEtat('erreur')
      })
    return () => {
      abandonne = true
    }
  }, [actif, versionSignaux, langue])

  useEffect(() => {
    if (!actif) return
    if (compte === null) {
      // Sans compte, les palmarès sont les brouillons locaux — lecture
      // instantanée. Celui de la vie passe devant, comme au serveur.
      setTops(
        [...lirePalmaresLocaux(univers)].sort((a, b) => Number(b.vie) - Number(a.vie)),
      )
      return
    }
    let abandonne = false
    chargerPalmares(univers)
      .then((reponse) => {
        // Ici (et seulement ici) le couronné passe devant : Ma liste est une
        // lecture, l'ordre de création n'y dit rien.
        if (!abandonne)
          setTops([...reponse.items].sort((a, b) => Number(b.vie) - Number(a.vie)))
      })
      .catch(() => {
        // Des palmarès illisibles ne cassent pas la liste : section vide.
        if (!abandonne) setTops([])
      })
    return () => {
      abandonne = true
    }
  }, [actif, univers, compte?.id])

  if (etat === 'erreur') {
    return <p className="fivo-message fivo-erreur">{t.dit('liste.erreur')}</p>
  }
  if (etat === 'en-cours' && items.length === 0) {
    return <p className="fivo-message">{t.dit('commun.chargement')}</p>
  }

  // Les TOP 5 — les premières sections de la maquette, en lecture seule :
  // les palmarès s'éditent dans l'onglet Mes fives, « Modifier » y mène.
  // Celui de la vie s'affiche même vide (c'est le geste attendu) ; les
  // autres portent le nom que leur auteur leur a donné.
  const sectionsTops = (
    <>
      {tops.length === 0 && (
        <section className="fivo-section-liste fivo-section-top5">
          <h4>{t.dit('liste.top5')}</h4>
          <p className="fivo-message fivo-message-discret">
            {t.dit('liste.top5_vide')}{' '}
            <button type="button" className="compte-lien" onClick={onVoirFives}>
              {t.dit('fives.commencer')}
            </button>
          </p>
        </section>
      )}
      {tops.map((palm) => (
        <section key={palm.id} className="fivo-section-liste fivo-section-top5">
          <h4>
            {palm.vie && (
              <span className="fives-couronne" aria-hidden="true">
                ★
              </span>
            )}
            <span dir="auto">
              {palm.titre ?? (palm.vie ? t.dit('liste.top5') : t.dit('fives.sans_titre'))}
            </span>
            <button
              type="button"
              className="compte-lien fivo-top5-modifier"
              onClick={onVoirFives}
            >
              {t.dit('liste.top5_modifier')}
            </button>
          </h4>
          {palm.oeuvres.length === 0 ? (
            <p className="fivo-message fivo-message-discret">{t.dit('liste.top5_vide')}</p>
          ) : (
            <BandeFives
              oeuvres={palm.oeuvres}
              onOuvrir={(identifiant, oeuvreId) =>
                oeuvreId !== null && onOuvrir(identifiant, oeuvreId, univers)
              }
            />
          )}
        </section>
      ))}
    </>
  )

  if (etat === 'servi' && items.length === 0) {
    return (
      <div className="fivo-mes-listes">
        {sectionsTops}
        <p className="fivo-message">{t.dit('liste.vide')}</p>
      </div>
    )
  }

  return (
    <div className="fivo-mes-listes">
      <p className="fivo-message fivo-message-discret">{t.dit('liste.tous_univers')}</p>
      {sectionsTops}
      {SECTIONS.map(({ statut, titre }) => {
        const dedans = items.filter((item) => item.statut === statut)
        return (
          <section key={statut} className={`fivo-section-liste fivo-section-${statut}`}>
            <h4>
              {t.dit(titre)}
              <span className="fivo-section-compte">
                {t.compte(dedans.length, 'liste.compte_une', 'liste.compte')}
              </span>
            </h4>
            {dedans.length === 0 ? (
              <p className="fivo-message fivo-message-discret">{t.dit('liste.vide_section')}</p>
            ) : (
              <div className="fivo-liste">
                {dedans.map((item) => (
                  <CarteOeuvre
                    key={`${item.univers}-${item.oeuvreId}`}
                    titre={item.titre}
                    annee={item.annee}
                    type={t.dit(`type.${item.univers}`)}
                    affiche={item.affiche}
                    statutActuel={statuts[item.oeuvreId] ?? null}
                    classable
                    onOuvrir={() =>
                      item.id !== null && onOuvrir(item.id, item.oeuvreId, item.univers)
                    }
                    onClasser={(choisi) => onClasser(item.oeuvreId, item.univers, choisi)}
                    onDeclasser={() => onDeclasser(item.oeuvreId)}
                    onRetirer={() => onDeclasser(item.oeuvreId)}
                  />
                ))}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
