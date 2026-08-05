import { MantineProvider, createTheme } from '@mantine/core'
import '@mantine/core/styles.css'
import { Notifications } from '@mantine/notifications'
import '@mantine/notifications/styles.css'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'

const theme = createTheme({
  primaryColor: 'indigo',
  defaultRadius: 'md',
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  headings: { fontWeight: '600' },
})

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Un tableau d'avancement n'a pas à se recharger au moindre retour sur
      // l'onglet : les chiffres bougent à l'échelle de la collecte, pas de la
      // seconde. Le bouton « rafraîchir » est là pour les impatients.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
)
