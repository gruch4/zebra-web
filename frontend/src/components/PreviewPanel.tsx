import { Alert, Box, Center, Image, List, LoadingOverlay, Paper, Text } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'

import { errorMessage } from '../utils/format'
import type { PngPreview } from './usePngPreview'

interface PreviewPanelProps {
  preview: PngPreview | undefined
  loading?: boolean
  error?: unknown
  emptyText?: string
  maxHeight?: number
}

export function PreviewPanel({
  preview,
  loading,
  error,
  emptyText = 'Nothing to preview yet',
  maxHeight = 600,
}: PreviewPanelProps) {
  return (
    <Box pos="relative">
      <LoadingOverlay visible={!!loading} overlayProps={{ blur: 1 }} loaderProps={{ size: 'sm' }} />
      {error ? (
        <Alert color="red" icon={<IconAlertTriangle size={16} />} title="Preview failed">
          {errorMessage(error)}
        </Alert>
      ) : preview ? (
        <>
          <Paper withBorder p="xs" bg="white" style={{ display: 'inline-block', maxWidth: '100%' }}>
            <Image
              src={preview.url}
              alt="Label preview"
              fit="contain"
              mah={maxHeight}
              style={{ imageRendering: 'pixelated' }}
            />
          </Paper>
          {preview.warnings.length > 0 && (
            <Alert
              color="yellow"
              mt="sm"
              icon={<IconAlertTriangle size={16} />}
              title="Preview notes"
            >
              <List size="sm">
                {preview.warnings.map((warning) => (
                  <List.Item key={warning}>{warning}</List.Item>
                ))}
              </List>
            </Alert>
          )}
        </>
      ) : (
        <Center h={160}>
          <Text c="dimmed">{emptyText}</Text>
        </Center>
      )}
    </Box>
  )
}
