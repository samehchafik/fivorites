// Les bandes-annonces, lues SUR PLACE.
//
// Avant, la vignette était un lien sortant : cliquer emportait le visiteur
// sur YouTube — et avec lui sa recherche, ses filtres, sa pile de
// suggestions et la fiche qu'il lisait. Revenir voulait dire tout refaire.
// Le lecteur s'ouvre donc DANS la fiche.
//
// Deux règles tenues ici :
//
// * **rien avant le clic.** Une iframe par vidéo, c'est un mégaoctet et
//   autant de traceurs chargés pour une bande-annonce que personne n'a
//   demandée. La vignette est une façade ; l'iframe n'existe qu'après le
//   geste, et une seule à la fois.
// * **`youtube-nocookie`**, servi par l'API (`Video.integration`) : le
//   lecteur qui ne dépose rien tant qu'on ne lance pas la lecture.
//
// Le lien sortant reste, en second : certains veulent la page d'origine, ses
// commentaires, sa qualité maximale. Ce n'est simplement plus le seul choix.

import { useState } from 'react'

import { useTextes } from './textes'
import type { Video } from './types'

/** L'identité d'une vidéo dans la liste — `site` seul ne suffit pas. */
function cle_de(video: Video): string {
  return `${video.site}-${video.cle}`
}

export function Videos({ videos }: { videos: Video[] }) {
  const t = useTextes()
  // La vidéo en lecture, ou `null`. Une seule : deux lecteurs qui parlent en
  // même temps dans la même fiche, personne ne veut ça.
  const [lecture, setLecture] = useState<string | null>(null)

  return (
    <ul className="fiche-videos">
      {videos.map((video) => {
        const identite = cle_de(video)
        const nom = video.nom ?? video.type
        const meta = [
          video.type,
          video.langue?.toUpperCase(),
          video.saison ? t.dit('saison.titre', { numero: video.saison }) : null,
        ]
          .filter(Boolean)
          .join(' · ')

        if (lecture === identite && video.integration) {
          return (
            <li key={identite} className="fiche-video-ouverte">
              <div className="fiche-video-cadre">
                <iframe
                  src={`${video.integration}?autoplay=1&rel=0`}
                  title={t.dit('video.lecteur', { nom })}
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  referrerPolicy="strict-origin-when-cross-origin"
                  allowFullScreen
                />
              </div>
              <div className="fiche-video-pied">
                <strong>{nom}</strong>
                <button type="button" className="fiche-video-fermer" onClick={() => setLecture(null)}>
                  ✕ {t.dit('video.fermer')}
                </button>
                {video.url && (
                  <a href={video.url} target="_blank" rel="noreferrer noopener">
                    {t.dit('video.ouvrir', { site: video.site })}
                  </a>
                )}
              </div>
            </li>
          )
        }

        return (
          <li key={identite}>
            {/* La façade. Un bouton et non un lien : ce clic ne navigue pas,
                il remplace la vignette par le lecteur — l'annoncer comme un
                lien serait mentir au clavier comme au lecteur d'écran. */}
            <button
              type="button"
              className="fiche-video-facade"
              onClick={() => video.integration && setLecture(identite)}
              disabled={!video.integration}
              title={video.integration ? t.dit('video.lire') : nom}
            >
              {video.vignette ? (
                <img src={video.vignette} alt="" loading="lazy" />
              ) : (
                <span className="fiche-video-vide" aria-hidden="true" />
              )}
              <span className="fiche-video-lecture" aria-hidden="true">
                ▶
              </span>
              <strong>{nom}</strong>
              <span className="fiche-video-meta">{meta}</span>
            </button>
            {/* Sans lecteur intégrable (un site que l'API ne sait pas
                encadrer), le lien sortant redevient le seul chemin — et il
                est alors le geste principal, pas un secours caché. */}
            {!video.integration && video.url && (
              <a
                className="fiche-video-lien"
                href={video.url}
                target="_blank"
                rel="noreferrer noopener"
              >
                {t.dit('video.ouvrir', { site: video.site })}
              </a>
            )}
          </li>
        )
      })}
    </ul>
  )
}
