import { Button, Stack, Text, Title } from '@mantine/core'
import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <Stack align="center" py="xl">
      <Title order={2}>Page not found</Title>
      <Text c="dimmed">The page you are looking for does not exist.</Text>
      <Button component={Link} to="/">
        Go to Print ZPL
      </Button>
    </Stack>
  )
}
