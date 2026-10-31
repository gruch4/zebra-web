import { useDebouncedValue } from '@mantine/hooks'

import { apiBlob } from '../api/client'
import { usePngPreview } from './usePngPreview'

/** Live preview of an archived template filled with the given values. */
export function useTemplatePreview(
  labelId: number,
  values: Record<string, string>,
  enabled = true,
) {
  const [debounced] = useDebouncedValue(values, 300)
  return usePngPreview(
    ['template', labelId, debounced],
    () => apiBlob(`/api/templates/${labelId}/preview.png`, { json: { variables: debounced } }),
    enabled,
  )
}
