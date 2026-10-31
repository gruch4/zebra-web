import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { ElementPreview } from '../api/types'
import type { DesignElement } from './types'

/**
 * Backend-rendered appearance of an element at the origin, rotated as it prints, with
 * variables filled in with `values` (e.g. their defaults).
 */
export function useElementPreview(
  element: DesignElement,
  dpi: number,
  enabled: boolean,
  values: Record<string, string> = {},
) {
  // The position is applied on the canvas, so it is not part of the key.
  const { x: _x, y: _y, id: _id, name: _name, ...content } = element
  return useQuery({
    queryKey: ['element-preview', dpi, content, values],
    queryFn: ({ signal }) =>
      api<ElementPreview>('/api/designer/element-preview', {
        json: { element: { ...content, id: 'preview', x: 0, y: 0 }, dpi, values },
        signal,
      }),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  })
}
