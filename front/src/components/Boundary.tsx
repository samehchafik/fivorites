import { Alert, Anchor, Button, Code, Container, Group, Stack, Text, Title } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * Le filet sous l'application.
 *
 * Sans lui, une seule propriété manquante dans une réponse d'API blanchit toute
 * la page : React démonte l'arbre entier et rien ne dit pourquoi. C'est arrivé
 * — le front lisait `translated.name` sur une API qui ne renvoyait pas encore
 * ce champ — et l'écran blanc n'aidait personne à comprendre qu'il fallait
 * reconstruire l'image.
 *
 * Ce cas n'est pas exotique ici : `www/` se déploie par `git pull` et l'API par
 * un `docker build`. Les deux moitiés peuvent donc être d'une version
 * différente à tout moment, et le seront chaque fois qu'on oubliera le second.
 * Le message le dit, plutôt que de laisser chercher.
 *
 * Une classe, parce que React n'offre pas d'équivalent en composant de
 * fonction : `componentDidCatch` n'a pas de crochet.
 */
export class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Laissé dans la console : c'est là qu'on ira chercher la pile, et le
    // message affiché ne la contient volontairement pas.
    console.error('Erreur de rendu', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <Container size="sm" py="xl">
        <Alert color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
          <Stack gap="sm">
            <Title order={4}>L'affichage s'est interrompu</Title>

            <Text size="sm">
              La cause la plus fréquente est un décalage de version : le front est déployé par{' '}
              <Code>git pull</Code>, l'API par <Code>docker compose build admin</Code>. Quand le
              second est oublié, le front lit des champs que l'API ne renvoie pas encore.
            </Text>

            <Code block>{String(this.state.error)}</Code>

            <Text size="xs" c="dimmed">
              Front <Code>{__APP_VERSION__}</Code> — la pile complète est dans la console du
              navigateur.
            </Text>

            <Group>
              <Button size="xs" onClick={() => window.location.reload()}>
                Recharger
              </Button>
              <Anchor href="/api/health" size="xs" target="_blank" rel="noreferrer">
                Vérifier que l'API répond
              </Anchor>
            </Group>
          </Stack>
        </Alert>
      </Container>
    )
  }
}
