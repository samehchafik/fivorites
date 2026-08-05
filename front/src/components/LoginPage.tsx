import {
  Alert,
  Button,
  Center,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useMutation } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'

import { ApiError, api } from '../api'
import type { Account } from '../types'

export function LoginPage({ onSignedIn }: { onSignedIn: (account: Account) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const signIn = useMutation({
    mutationFn: () => api.login(username.trim(), password),
    onSuccess: onSignedIn,
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (username.trim() && password) signIn.mutate()
  }

  // Le 429 mérite un autre mot que le 401 : « réessayez » n'aide pas quand la
  // porte est verrouillée pour cinq minutes.
  const error = signIn.error
  const message =
    error instanceof ApiError && error.status === 429
      ? error.message
      : error
        ? 'Identifiants invalides.'
        : null

  return (
    <Center h="100vh" p="md">
      <Paper withBorder shadow="md" p="xl" radius="md" w={400} component="form" onSubmit={submit}>
        <Stack gap="lg">
          <div>
            <Title order={3}>Fivorites — administration</Title>
            <Text size="sm" c="dimmed">
              Suivi de l'acquisition, par univers et par langue.
            </Text>
          </div>

          {message && (
            <Alert color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
              {message}
            </Alert>
          )}

          <TextInput
            label="Identifiant"
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            autoComplete="username"
            autoFocus
            required
          />
          <PasswordInput
            label="Mot de passe"
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            autoComplete="current-password"
            required
          />

          <Button type="submit" loading={signIn.isPending} fullWidth>
            Se connecter
          </Button>

          <Text size="xs" c="dimmed">
            Les comptes se créent en ligne de commande : <code>fiv-admin user add</code>. Il n'y a
            pas d'inscription.
          </Text>
        </Stack>
      </Paper>
    </Center>
  )
}
