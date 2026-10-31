import { keepPreviousData, useQuery } from '@tanstack/react-query'

export interface PngPreview {
  url: string
  warnings: string[]
  labelCount: number
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

export async function readPngResponse(response: Response): Promise<PngPreview> {
  const warnings = JSON.parse(response.headers.get('X-Render-Warnings') ?? '[]') as string[]
  const labelCount = Number(response.headers.get('X-Label-Count') ?? '1')
  return { url: await blobToDataUrl(await response.blob()), warnings, labelCount }
}

/** Fetch a PNG preview endpoint and expose it as a data URL with render warnings. */
export function usePngPreview(key: unknown[], request: () => Promise<Response>, enabled = true) {
  return useQuery({
    queryKey: ['png', ...key],
    queryFn: async () => readPngResponse(await request()),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: false,
  })
}
