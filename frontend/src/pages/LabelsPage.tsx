import {
  ActionIcon,
  AspectRatio,
  Badge,
  Button,
  Card,
  Center,
  FileButton,
  Group,
  Image,
  Menu,
  Pagination,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { modals } from '@mantine/modals'
import { notifications } from '@mantine/notifications'
import {
  IconCopy,
  IconDots,
  IconDownload,
  IconEdit,
  IconFileSpreadsheet,
  IconPencil,
  IconPlus,
  IconPrinter,
  IconSearch,
  IconTrash,
  IconUpload,
} from '@tabler/icons-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import {
  useDeleteLabel,
  useDuplicateLabel,
  useImportLabels,
  useLabelTags,
  useLabels,
  useSaveLabel,
} from '../api/hooks'
import type { LabelSummary } from '../api/types'
import { PrintLabelModal } from '../components/PrintLabelModal'
import { SaveLabelModal } from '../components/SaveLabelModal'
import { errorMessage, formatDateTime } from '../utils/format'

const PAGE_SIZE = 24

function LabelCard({
  label,
  onPrint,
  onEdit,
}: {
  label: LabelSummary
  onPrint: () => void
  onEdit: () => void
}) {
  const navigate = useNavigate()
  const remove = useDeleteLabel()
  const duplicate = useDuplicateLabel()
  const open = () =>
    navigate(label.kind === 'design' ? `/designer/${label.id}` : `/?label=${label.id}`)

  function confirmDelete() {
    modals.openConfirmModal({
      title: `Delete “${label.name}”?`,
      children: (
        <Text size="sm">The label is removed from the archive. Print history is kept.</Text>
      ),
      labels: { confirm: 'Delete', cancel: 'Cancel' },
      confirmProps: { color: 'red' },
      onConfirm: () => remove.mutate(label.id),
    })
  }

  return (
    <Card withBorder padding="sm">
      <Card.Section>
        <AspectRatio ratio={3 / 2} bg="var(--mantine-color-gray-light)">
          <Center p="xs" style={{ cursor: 'pointer' }} onClick={open}>
            <Image
              src={`/api/labels/${label.id}/preview.png?v=${encodeURIComponent(label.updated_at)}`}
              alt={`Preview of ${label.name}`}
              fit="contain"
              mah="100%"
              bg="white"
              style={{ boxShadow: '0 1px 3px rgba(0,0,0,.2)' }}
            />
          </Center>
        </AspectRatio>
      </Card.Section>
      <Group justify="space-between" mt="sm" wrap="nowrap" align="flex-start">
        <div style={{ minWidth: 0 }}>
          <Text fw={600} truncate>
            {label.name}
          </Text>
          <Text size="xs" c="dimmed">
            {formatDateTime(label.updated_at)}
          </Text>
        </div>
        <Menu position="bottom-end" withinPortal>
          <Menu.Target>
            <ActionIcon variant="subtle" aria-label={`Actions for ${label.name}`}>
              <IconDots size={16} />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<IconPencil size={14} />} onClick={open}>
              {label.kind === 'design' ? 'Open in designer' : 'Open in ZPL editor'}
            </Menu.Item>
            <Menu.Item leftSection={<IconPrinter size={14} />} onClick={onPrint}>
              Print…
            </Menu.Item>
            {label.variables.length > 0 && (
              <Menu.Item
                leftSection={<IconFileSpreadsheet size={14} />}
                onClick={() => navigate(`/templates/${label.id}`)}
              >
                Print from template / data file
              </Menu.Item>
            )}
            <Menu.Item leftSection={<IconEdit size={14} />} onClick={onEdit}>
              Rename / tags
            </Menu.Item>
            <Menu.Item
              leftSection={<IconCopy size={14} />}
              onClick={() => duplicate.mutate(label.id)}
            >
              Duplicate
            </Menu.Item>
            <Menu.Item
              leftSection={<IconDownload size={14} />}
              component="a"
              href={`/api/labels/${label.id}/export.zpl`}
            >
              Export .zpl
            </Menu.Item>
            <Menu.Divider />
            <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={confirmDelete}>
              Delete
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>
      {label.description && (
        <Text size="sm" c="dimmed" lineClamp={2} mt={4}>
          {label.description}
        </Text>
      )}
      <Group gap={4} mt="xs">
        <Badge size="xs" variant="light" color={label.kind === 'design' ? 'grape' : 'blue'}>
          {label.kind === 'design' ? 'Design' : 'ZPL'}
        </Badge>
        {label.variables.length > 0 && (
          <Badge size="xs" variant="light" color="teal">
            {label.variables.length} variable{label.variables.length > 1 ? 's' : ''}
          </Badge>
        )}
        {label.width_mm && label.height_mm && (
          <Badge size="xs" variant="outline" color="gray">
            {label.width_mm} × {label.height_mm} mm
          </Badge>
        )}
        {label.tags.map((tag) => (
          <Badge key={tag} size="xs" variant="dot" color="gray">
            {tag}
          </Badge>
        ))}
      </Group>
      <Button
        mt="sm"
        size="xs"
        variant="light"
        leftSection={<IconPrinter size={14} />}
        onClick={onPrint}
        fullWidth
      >
        Print
      </Button>
    </Card>
  )
}

export function LabelsPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [debouncedSearch] = useDebouncedValue(search, 300)
  const [tag, setTag] = useState<string | null>(null)
  const [kind, setKind] = useState('all')
  const [page, setPage] = useState(1)
  const [printing, setPrinting] = useState<LabelSummary | null>(null)
  const [editing, setEditing] = useState<LabelSummary | null>(null)
  const { data: tags = [] } = useLabelTags()
  const importLabels = useImportLabels()
  const saveLabel = useSaveLabel()
  const { data, isLoading } = useLabels({
    q: debouncedSearch,
    tag,
    kind: kind === 'all' ? null : kind,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  })

  async function handleImport(files: File[]) {
    if (files.length === 0) return
    try {
      const imported = await importLabels.mutateAsync(files)
      notifications.show({ color: 'green', message: `Imported ${imported.length} label(s)` })
    } catch (error) {
      notifications.show({ color: 'red', title: 'Import failed', message: errorMessage(error) })
    }
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Labels archive</Title>
        <Group gap="xs">
          <FileButton onChange={handleImport} accept=".zpl,.txt,.prn" multiple>
            {(props) => (
              <Button
                {...props}
                variant="default"
                leftSection={<IconUpload size={16} />}
                loading={importLabels.isPending}
              >
                Import .zpl
              </Button>
            )}
          </FileButton>
          <Button
            variant="default"
            leftSection={<IconPlus size={16} />}
            onClick={() => navigate('/')}
          >
            New ZPL label
          </Button>
          <Button leftSection={<IconPlus size={16} />} onClick={() => navigate('/designer')}>
            New design
          </Button>
        </Group>
      </Group>
      <Group>
        <TextInput
          placeholder="Search by name or description"
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => {
            setSearch(e.currentTarget.value)
            setPage(1)
          }}
          w={300}
        />
        <Select
          placeholder="All tags"
          data={tags}
          value={tag}
          onChange={(v) => {
            setTag(v)
            setPage(1)
          }}
          clearable
          w={180}
        />
        <SegmentedControl
          data={[
            { value: 'all', label: 'All' },
            { value: 'design', label: 'Designs' },
            { value: 'zpl', label: 'ZPL' },
          ]}
          value={kind}
          onChange={(v) => {
            setKind(v)
            setPage(1)
          }}
        />
      </Group>
      {!isLoading && data?.items.length === 0 && (
        <Text c="dimmed" ta="center" py="xl">
          No labels found. Save one from the ZPL editor or the designer.
        </Text>
      )}
      <SimpleGrid cols={{ base: 1, xs: 2, md: 3, xl: 4 }}>
        {data?.items.map((label) => (
          <LabelCard
            key={label.id}
            label={label}
            onPrint={() => setPrinting(label)}
            onEdit={() => setEditing(label)}
          />
        ))}
      </SimpleGrid>
      {data && data.total > PAGE_SIZE && (
        <Group justify="center">
          <Pagination total={Math.ceil(data.total / PAGE_SIZE)} value={page} onChange={setPage} />
        </Group>
      )}
      <PrintLabelModal label={printing} onClose={() => setPrinting(null)} />
      <SaveLabelModal
        opened={editing !== null}
        title="Edit label details"
        initial={editing ?? undefined}
        loading={saveLabel.isPending}
        onClose={() => setEditing(null)}
        onSave={async (details) => {
          if (!editing) return
          try {
            await saveLabel.mutateAsync({ id: editing.id, body: details })
            setEditing(null)
          } catch (error) {
            notifications.show({
              color: 'red',
              title: 'Saving failed',
              message: errorMessage(error),
            })
          }
        }}
      />
    </Stack>
  )
}
