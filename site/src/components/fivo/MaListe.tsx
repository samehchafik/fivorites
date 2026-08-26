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

import { listerSignaux } from './api'
import { CarteOeuvre } from './CarteOeuvre'
import { useTextes } from './textes'
import type { CleTexte } from '../../i18n/textes'
import { type Signal, type Statut, type UniversSlug } from './types'

// L'ordre des sections : ce qui reste à faire d'abord, ce qui est acquis
// ensuite, ce qui est écarté en dernier.
const SECTIONS: Array<{ statut: Statut; titre: CleTexte }> = [
  { statut: 'a_voir', titre: 'liste.a_voir' },
  { statut: 'aime', titre: 'liste.aime' },
  { statut: 'aime_pas', titre: 'liste.aime_pas' },
]

export function MaListe({
  langue,
  statuts,
  versionSignaux,
  actif,
  onOuvrir,
  onClasser,
  onDeclasser,
}: {
  /** La langue : les titres de la liste se relisent dedans. */
  langue: string
  /** Les classements de la session, par pivot — la source de vérité des
   *  boutons, tenue par `FivoSuggest`. La liste, elle, porte l'affichage. */
  statuts: Record<number, Statut>
  versionSignaux: number
  actif: boolean
  /** Ouvre la fiche — avec son univers, puisque la liste les mélange. */
  onOuvrir: (identifiant: number, oeuvreId: number, univers: UniversSlug) => void
  onClasser: (oeuvreId: number, univers: UniversSlug, statut: Statut) => void
  onDeclasser: (oeuvreId: number) => void
}) {
  const t = useTextes()
  const [items, setItems] = useState<Signal[]>([])
  const [etat, setEtat] = useState<'en-cours' | 'servi' | 'erreur'>('en-cours')
  // Ce que la liste affichée reflète déjà — même règle que dans les deux
  // autres onglets : caché, le panneau ne recharge rien ; visible, il ne
  // recharge que si quelque chose a bougé.
  const charge = useRef<{ version: number; langue: string } | null>(null)

  useEffect(() => {
    if (!actif) return
    if (charge.current?.version === versionSignaux && charge.current.langue === langue) return
    let abandonne = false
    setEtat('en-cours')
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

  if (etat === 'erreur') {
    return <p className="fivo-message fivo-erreur">{t.dit('liste.erreur')}</p>
  }
  if (etat === 'en-cours' && items.length === 0) {
    return <p className="fivo-message">{t.dit('commun.chargement')}</p>
  }
  if (etat === 'servi' && items.length === 0) {
    return <p className="fivo-message">{t.dit('liste.vide')}</p>
  }

  return (
    <div className="fivo-mes-listes">
      <p className="fivo-message fivo-message-discret">{t.dit('liste.tous_univers')}</p>
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
