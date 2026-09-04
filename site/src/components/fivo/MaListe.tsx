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

import { chargerFives, listerSignaux, urlAffiche } from './api'
import { CarteOeuvre } from './CarteOeuvre'
import { lireBrouillon } from './Fives'
import { useTextes } from './textes'
import type { CleTexte } from '../../i18n/textes'
import { type Compte, type Five, type Signal, type Statut, type UniversSlug } from './types'

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
  const [topFives, setTopFives] = useState<Five[]>([])
  const [topMoment, setTopMoment] = useState<Five[]>([])
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
      // instantanée.
      setTopFives(lireBrouillon(univers, 'vie'))
      setTopMoment(lireBrouillon(univers, 'moment'))
      return
    }
    let abandonne = false
    chargerFives(univers, 'vie')
      .then((reponse) => {
        if (!abandonne) setTopFives(reponse.items)
      })
      .catch(() => {
        // Un TOP 5 illisible ne casse pas la liste : la section se montre vide.
        if (!abandonne) setTopFives([])
      })
    chargerFives(univers, 'moment')
      .then((reponse) => {
        if (!abandonne) setTopMoment(reponse.items)
      })
      .catch(() => {
        if (!abandonne) setTopMoment([])
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

  // « Le TOP 5 de ma vie » — la première section de la maquette. En lecture
  // seule : le palmarès s'édite dans l'onglet Mes fives, « Modifier » y mène.
  const sectionTop5 = (
    <section className="fivo-section-liste fivo-section-top5">
      <h4>
        {t.dit('liste.top5')}
        <button type="button" className="compte-lien fivo-top5-modifier" onClick={onVoirFives}>
          {t.dit('liste.top5_modifier')}
        </button>
      </h4>
      {topFives.length === 0 ? (
        <p className="fivo-message fivo-message-discret">
          {t.dit('liste.top5_vide')}{' '}
          <button type="button" className="compte-lien" onClick={onVoirFives}>
            {t.dit('fives.commencer')}
          </button>
        </p>
      ) : (
        <ol className="fives-cases">
          {topFives.map((five) => {
            const affiche = urlAffiche(five.affiche, 'w92')
            return (
              <li key={five.rang} className="fives-case fives-case-pleine">
                <span className="fives-rang" aria-hidden="true">
                  {five.rang}
                </span>
                <button
                  type="button"
                  className="fives-oeuvre"
                  onClick={() => five.id !== null && onOuvrir(five.id, five.oeuvreId, univers)}
                  title={five.titre ?? undefined}
                >
                  {affiche ? (
                    <img src={affiche} alt="" loading="lazy" />
                  ) : (
                    <span className="fives-affiche-vide" aria-hidden="true" />
                  )}
                  <strong dir="auto">{five.titre ?? t.dit('carte.sans_titre')}</strong>
                </button>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )

  // « Le TOP du moment » — seulement s'il existe : contrairement au TOP 5
  // de la vie, il n'est pas un passage obligé.
  const sectionMoment = topMoment.length > 0 && (
    <section className="fivo-section-liste fivo-section-top5">
      <h4>
        {t.dit('fives.moment')}
        <button type="button" className="compte-lien fivo-top5-modifier" onClick={onVoirFives}>
          {t.dit('liste.top5_modifier')}
        </button>
      </h4>
      <ol className="fives-cases">
        {topMoment.map((five) => {
          const affiche = urlAffiche(five.affiche, 'w92')
          return (
            <li key={five.rang} className="fives-case fives-case-pleine">
              <span className="fives-rang" aria-hidden="true">
                {five.rang}
              </span>
              <button
                type="button"
                className="fives-oeuvre"
                onClick={() => five.id !== null && onOuvrir(five.id, five.oeuvreId, univers)}
                title={five.titre ?? undefined}
              >
                {affiche ? (
                  <img src={affiche} alt="" loading="lazy" />
                ) : (
                  <span className="fives-affiche-vide" aria-hidden="true" />
                )}
                <strong dir="auto">{five.titre ?? t.dit('carte.sans_titre')}</strong>
              </button>
            </li>
          )
        })}
      </ol>
    </section>
  )

  if (etat === 'servi' && items.length === 0) {
    return (
      <div className="fivo-mes-listes">
        {sectionTop5}
        {sectionMoment}
        <p className="fivo-message">{t.dit('liste.vide')}</p>
      </div>
    )
  }

  return (
    <div className="fivo-mes-listes">
      <p className="fivo-message fivo-message-discret">{t.dit('liste.tous_univers')}</p>
      {sectionTop5}
      {sectionMoment}
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
