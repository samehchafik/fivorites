// Le thème Mantine du site public — la charte V1 injectée dans le framework.
//
// Mantine apporte les comportements (onglets, champs, boutons, clavier,
// aria) ; la V1 apporte les pixels : Fira Sans partout, Libre Baskerville en
// titres, et le carmin #FA0036 comme couleur primaire, décliné en dix tons
// comme Mantine les attend (l'index 6 est le ton « filled » par défaut).

import { createTheme } from '@mantine/core'

export const theme_fivo = createTheme({
  fontFamily: "'Fira Sans', Verdana, sans-serif",
  headings: {
    fontFamily: "'Fira Sans', Verdana, sans-serif",
    fontWeight: '500',
  },
  primaryColor: 'carmin',
  colors: {
    carmin: [
      '#ffe5eb',
      '#ffb3c4',
      '#ff809d',
      '#ff4d76',
      '#fa1a4f',
      '#fa0036', // le rouge signature de la V1 (--red)
      '#d4002e',
      '#a80025',
      '#8c001f',
      '#700031', // le sombre des dégradés (--purple-dark)
    ],
  },
  defaultRadius: 'md',
})
