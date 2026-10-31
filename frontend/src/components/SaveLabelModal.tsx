import { Button, Group, Modal, Stack, TagsInput, TextInput, Textarea } from '@mantine/core'
import { useState } from 'react'

import { useLabelTags } from '../api/hooks'

export interface LabelDetails {
  name: string
  description: string
  tags: string[]
}

interface SaveLabelModalProps {
  opened: boolean
  onClose: () => void
  onSave: (details: LabelDetails) => void
  initial?: Partial<LabelDetails>
  title?: string
  loading?: boolean
}

function SaveLabelForm({
  initial,
  onClose,
  onSave,
  loading,
}: Omit<SaveLabelModalProps, 'opened' | 'title'>) {
  const { data: tags = [] } = useLabelTags()
  const [details, setDetails] = useState<LabelDetails>({
    name: initial?.name ?? '',
    description: initial?.description ?? '',
    tags: initial?.tags ?? [],
  })

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (details.name.trim()) onSave({ ...details, name: details.name.trim() })
      }}
    >
      <Stack>
        <TextInput
          label="Name"
          required
          data-autofocus
          value={details.name}
          onChange={(e) => setDetails({ ...details, name: e.currentTarget.value })}
        />
        <Textarea
          label="Description"
          autosize
          minRows={2}
          value={details.description}
          onChange={(e) => setDetails({ ...details, description: e.currentTarget.value })}
        />
        <TagsInput
          label="Tags"
          data={tags}
          value={details.tags}
          onChange={(value) => setDetails({ ...details, tags: value })}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={loading} disabled={!details.name.trim()}>
            Save
          </Button>
        </Group>
      </Stack>
    </form>
  )
}

export function SaveLabelModal({ opened, title = 'Save label', ...props }: SaveLabelModalProps) {
  return (
    <Modal opened={opened} onClose={props.onClose} title={title}>
      {opened && <SaveLabelForm {...props} />}
    </Modal>
  )
}
