import {
  Button,
  Checkbox,
  FileInput,
  Group,
  Image,
  Modal,
  NumberInput,
  Paper,
  Slider,
  Stack,
  Text,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api/client'
import type { GraphicResult } from '../api/types'
import { errorMessage } from '../utils/format'
import { dotsToMm } from '../utils/units'

interface ImageImportModalProps {
  opened: boolean
  onClose: () => void
  onAdd: (graphic: GraphicResult) => void
  dpi: number
  maxWidth: number
}

export function ImageImportModal({ opened, onClose, onAdd, dpi, maxWidth }: ImageImportModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [width, setWidth] = useState<number | ''>('')
  const [threshold, setThreshold] = useState(128)
  const [dither, setDither] = useState(false)
  const [invert, setInvert] = useState(false)
  const [options] = useDebouncedValue({ width, threshold, dither, invert }, 300)

  const conversion = useQuery({
    queryKey: ['graphic', file?.name, file?.size, file?.lastModified, options],
    queryFn: () => {
      const form = new FormData()
      form.append('file', file!)
      form.append('width', String(options.width || Math.min(maxWidth, 400)))
      form.append('threshold', String(options.threshold))
      form.append('dither', String(options.dither))
      form.append('invert', String(options.invert))
      return api<GraphicResult>('/api/graphics/convert', { form })
    },
    enabled: opened && file !== null,
    retry: false,
  })

  function close() {
    setFile(null)
    onClose()
  }

  return (
    <Modal opened={opened} onClose={close} title="Add image / logo" size="lg">
      <Stack>
        <FileInput
          label="Image file"
          placeholder="PNG, JPG, GIF, BMP…"
          accept="image/*"
          value={file}
          onChange={setFile}
        />
        <Group grow align="flex-start">
          <NumberInput
            label="Width (dots)"
            description={width ? `${dotsToMm(Number(width), dpi)} mm` : 'Default: up to 400 dots'}
            min={1}
            max={2400}
            value={width}
            onChange={(v) => setWidth(v === '' ? '' : Number(v))}
          />
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Threshold
            </Text>
            <Slider min={1} max={254} value={threshold} onChange={setThreshold} disabled={dither} />
          </Stack>
        </Group>
        <Group>
          <Checkbox
            label="Dither (photos)"
            checked={dither}
            onChange={(e) => setDither(e.currentTarget.checked)}
          />
          <Checkbox
            label="Invert"
            checked={invert}
            onChange={(e) => setInvert(e.currentTarget.checked)}
          />
        </Group>
        {conversion.error && (
          <Text c="red" size="sm">
            {errorMessage(conversion.error)}
          </Text>
        )}
        {conversion.data && (
          <Paper withBorder p="xs" bg="white">
            <Image src={conversion.data.preview} alt="Converted image" mah={300} fit="contain" />
            <Text size="xs" c="dimmed" mt={4}>
              {conversion.data.width} × {conversion.data.height} dots
            </Text>
          </Paper>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={close}>
            Cancel
          </Button>
          <Button
            disabled={!conversion.data || conversion.isFetching}
            onClick={() => {
              if (conversion.data) onAdd(conversion.data)
              close()
            }}
          >
            Add to label
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
