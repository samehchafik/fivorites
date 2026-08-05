import { Center, Loader } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, api } from './api'
import { Dashboard } from './components/Dashboard'
import { LoginPage } from './components/LoginPage'
import type { Account } from './types'

/**
 * Deux écrans, et rien entre les deux : la session décide.
 *
 * Il n'y a volontairement pas de routeur. L'administration a une seule page ;
 * un routeur n'apporterait ici qu'un repli SPA à configurer côté serveur et
 * des URL à maintenir pour une navigation qui n'existe pas.
 */
export function App() {
  const client = useQueryClient()

  const session = useQuery<Account | null>({
    queryKey: ['session'],
    queryFn: async () => {
      try {
        return await api.me()
      } catch (error) {
        // Pas de session : ce n'est pas une panne, c'est l'écran de connexion.
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
  })

  if (session.isLoading) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    )
  }

  if (!session.data) {
    return <LoginPage onSignedIn={(account) => client.setQueryData(['session'], account)} />
  }

  return (
    <Dashboard
      account={session.data}
      onSignedOut={() => {
        // Tout le cache est purgé, pas seulement la session : les chiffres
        // d'acquisition ne doivent pas réapparaître au prochain compte connecté.
        client.clear()
        client.setQueryData(['session'], null)
      }}
    />
  )
}
