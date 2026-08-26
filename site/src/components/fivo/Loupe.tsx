// La loupe : une image en grand, et rien d'autre.
//
// Elle existe parce qu'une affiche de 118 pixels ne se regarde pas — on la
// reconnaît. Cliquer dessus doit donner l'image, à la taille que TMDB sert de
// mieux, sur un fond qui ne dispute rien.
//
// `original` et non une taille fixe : une affiche fait 2 000 pixels de haut,
// un portrait 3 000, une image de fond 3 840. Demander « la plus grande » est
// le seul choix qui marche pour les trois — et la loupe ne s'ouvre qu'au
// clic, donc jamais rien n'est téléchargé sans qu'on l'ait demandé.

import { Modal } from '@mantine/core'

import { urlAffiche } from './api'
import { useTextes } from './textes'

export function Loupe({
  image,
  legende,
  onFermer,
}: {
  /** Le chemin TMDB (ou l'URL complète d'une couverture Open Library). */
  image: string | null
  legende?: string | null
  onFermer: () => void
}) {
  const t = useTextes()
  const grande = urlAffiche(image, 'original')
  return (
    <Modal
      opened={image !== null}
      onClose={onFermer}
      size="auto"
      centered
      padding={0}
      radius={4}
      title={null}
      withCloseButton={false}
      overlayProps={{ backgroundOpacity: 0.9 }}
      classNames={{ content: 'loupe', body: 'loupe-corps' }}
    >
      {grande && (
        // Le clic sur l'image referme aussi : c'est ce qu'on essaie
        // spontanément, et ne rien faire donnerait l'impression d'un blocage.
        <button type="button" className="loupe-bouton" onClick={onFermer} title={t.dit('commun.fermer')}>
          <img src={grande} alt={legende ?? ''} />
          {legende && <figcaption>{legende}</figcaption>}
        </button>
      )}
    </Modal>
  )
}
