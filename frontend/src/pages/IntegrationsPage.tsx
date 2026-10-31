import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Code,
  CopyButton,
  Group,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { modals } from '@mantine/modals'
import { notifications } from '@mantine/notifications'
import { IconCheck, IconCopy, IconPlus, IconTrash } from '@tabler/icons-react'
import { useState } from 'react'

import { useApiTokens, useCreateApiToken, useRevokeApiToken } from '../api/hooks'
import type { ApiToken, ApiTokenCreated, ApiTokenStatus } from '../api/types'
import { endOfLocalDay, errorMessage, formatDateTime } from '../utils/format'

const STATUS_COLORS: Record<ApiTokenStatus, string> = {
  active: 'green',
  expired: 'orange',
  revoked: 'gray',
}

function CreateTokenModal({
  opened,
  onClose,
  onCreated,
}: {
  opened: boolean
  onClose: () => void
  onCreated: (token: ApiTokenCreated) => void
}) {
  return (
    <Modal opened={opened} onClose={onClose} title="Create API token">
      {opened && <CreateTokenForm onClose={onClose} onCreated={onCreated} />}
    </Modal>
  )
}

function CreateTokenForm({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (token: ApiTokenCreated) => void
}) {
  const create = useCreateApiToken()
  const [name, setName] = useState('')
  const [expires, setExpires] = useState('')
  const today = new Date().toLocaleDateString('sv') // YYYY-MM-DD in local time

  async function submit() {
    try {
      const token = await create.mutateAsync({
        name: name.trim(),
        expires_at: expires ? endOfLocalDay(expires) : null,
      })
      onClose()
      onCreated(token)
    } catch (error) {
      notifications.show({ color: 'red', title: 'Creating failed', message: errorMessage(error) })
    }
  }

  return (
    <Stack>
      <TextInput
        label="Name"
        description="What will use this token, e.g. “Home inventory”. Shown on the labels and prints it creates."
        required
        maxLength={100}
        data-autofocus
        value={name}
        onChange={(e) => setName(e.currentTarget.value)}
      />
      <TextInput
        label="Expires"
        description="Optional. The token stops working at the end of this day."
        type="date"
        min={today}
        value={expires}
        onChange={(e) => setExpires(e.currentTarget.value)}
      />
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={submit} loading={create.isPending} disabled={!name.trim()}>
          Create token
        </Button>
      </Group>
    </Stack>
  )
}

function curlExample(token: string): string {
  return [
    `curl -X POST ${window.location.origin}/api/v1/print \\`,
    `  -H "Authorization: Bearer ${token}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"zpl": "^XA^FO50,50^A0N,40,40^FDHello^FS^XZ"}'`,
  ].join('\n')
}

function TokenSecretModal({
  token,
  onClose,
}: {
  token: ApiTokenCreated | null
  onClose: () => void
}) {
  return (
    <Modal
      opened={token !== null}
      onClose={onClose}
      title="Your new API token"
      size="lg"
      closeOnClickOutside={false}
      closeOnEscape={false}
      withCloseButton={false}
    >
      {token && (
        <Stack>
          <Alert color="yellow" title="Copy it now">
            This token is shown only once and cannot be recovered. If you lose it, revoke it and
            create a new one.
          </Alert>
          <Group wrap="nowrap" align="flex-start">
            <Code
              block
              style={{ flex: 1, wordBreak: 'break-all', whiteSpace: 'pre-wrap', userSelect: 'all' }}
            >
              {token.token}
            </Code>
            {/* The clipboard API only exists on HTTPS and localhost, not on http://<lan-ip>. */}
            {window.isSecureContext && (
              <CopyButton value={token.token}>
                {({ copied, copy }) => (
                  <Button
                    variant={copied ? 'light' : 'default'}
                    color={copied ? 'green' : undefined}
                    leftSection={copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
                    onClick={copy}
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                )}
              </CopyButton>
            )}
          </Group>
          {!window.isSecureContext && (
            <Text size="sm" c="dimmed">
              This page is not served over HTTPS, so the browser blocks the copy button. Click the
              token to select it, then copy it manually.
            </Text>
          )}
          <Text size="sm">Try it:</Text>
          <Code block>{curlExample(token.token)}</Code>
          <Group justify="flex-end">
            <Button onClick={onClose}>Done</Button>
          </Group>
        </Stack>
      )}
    </Modal>
  )
}

function TokenRow({ token, onRevoke }: { token: ApiToken; onRevoke: () => void }) {
  return (
    <Table.Tr>
      <Table.Td>
        <Group gap="xs">
          <Text fw={500} c={token.status === 'active' ? undefined : 'dimmed'}>
            {token.name}
          </Text>
          {token.shared && (
            <Tooltip label="Created before login was enabled; every user can manage it">
              <Badge size="xs" variant="outline" color="gray">
                Shared
              </Badge>
            </Tooltip>
          )}
        </Group>
      </Table.Td>
      <Table.Td ff="monospace">{token.prefix}…</Table.Td>
      <Table.Td>{token.owner}</Table.Td>
      <Table.Td>{formatDateTime(token.created_at)}</Table.Td>
      <Table.Td>{token.expires_at ? formatDateTime(token.expires_at) : '—'}</Table.Td>
      <Table.Td>{token.last_used_at ? formatDateTime(token.last_used_at) : 'Never'}</Table.Td>
      <Table.Td>
        <Badge color={STATUS_COLORS[token.status]} variant="light">
          {token.status}
        </Badge>
      </Table.Td>
      <Table.Td>
        {token.status !== 'revoked' && (
          <Group justify="flex-end">
            <Tooltip label="Revoke">
              <ActionIcon
                variant="subtle"
                color="red"
                aria-label={`Revoke ${token.name}`}
                onClick={onRevoke}
              >
                <IconTrash size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        )}
      </Table.Td>
    </Table.Tr>
  )
}

export function IntegrationsPage() {
  const { data: tokens = [], isLoading } = useApiTokens()
  const revoke = useRevokeApiToken()
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<ApiTokenCreated | null>(null)

  function confirmRevoke(token: ApiToken) {
    modals.openConfirmModal({
      title: `Revoke “${token.name}”?`,
      children: (
        <Text size="sm">
          Anything using this token stops working immediately. Labels and prints it already made are
          kept.
        </Text>
      ),
      labels: { confirm: 'Revoke', cancel: 'Cancel' },
      confirmProps: { color: 'red' },
      onConfirm: () =>
        revoke.mutate(token.id, {
          onError: (error) =>
            notifications.show({
              color: 'red',
              title: 'Revoking failed',
              message: errorMessage(error),
            }),
        }),
    })
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>API access</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
          Create token
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        Other systems can print labels and save them to the archive through the API. Create a token
        for each system. A token keeps working even if the person who made it loses access to this
        app, so revoke the ones you no longer need. Read the{' '}
        <Anchor href="/api/v1/docs" target="_blank" rel="noreferrer">
          API documentation
        </Anchor>{' '}
        or get the{' '}
        <Anchor href="/api/v1/openapi.json" target="_blank" rel="noreferrer">
          OpenAPI spec
        </Anchor>
        .
      </Text>
      {tokens.some((token) => token.shared) && (
        <Alert color="yellow" title="Tokens from before login was enabled">
          Tokens marked “Shared” were created while anyone could open this app. They still work, and
          every logged-in user can revoke them. Revoke the ones you do not recognise.
        </Alert>
      )}
      <Card withBorder p={0}>
        <Table.ScrollContainer minWidth={900}>
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                <Table.Th>Token</Table.Th>
                <Table.Th>Created by</Table.Th>
                <Table.Th>Created</Table.Th>
                <Table.Th>Expires</Table.Th>
                <Table.Th>Last used</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {tokens.map((token) => (
                <TokenRow key={token.id} token={token} onRevoke={() => confirmRevoke(token)} />
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {!isLoading && tokens.length === 0 && (
          <Text c="dimmed" ta="center" p="lg">
            No API tokens yet.
          </Text>
        )}
      </Card>
      <CreateTokenModal
        opened={creating}
        onClose={() => setCreating(false)}
        onCreated={setCreated}
      />
      <TokenSecretModal token={created} onClose={() => setCreated(null)} />
    </Stack>
  )
}
