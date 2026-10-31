export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(ApiError.describe(status, detail))
    this.status = status
    this.detail = detail
  }

  static describe(status: number, detail: unknown): string {
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'message' in detail) {
      return String((detail as { message: unknown }).message)
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          const loc = Array.isArray(item?.loc) ? item.loc.slice(1).join('.') : ''
          return loc ? `${loc}: ${item.msg}` : String(item?.msg ?? item)
        })
        .join('; ')
    }
    return `Request failed (${status})`
  }
}

export function loginUrl(): string {
  const next = window.location.pathname + window.location.search
  return `/auth/login?next=${encodeURIComponent(next)}`
}

interface RequestOptions {
  method?: string
  json?: unknown
  form?: FormData
  signal?: AbortSignal
  keepalive?: boolean // let the request finish when the page is being left
}

async function send(path: string, options: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = {}
  let body: BodyInit | undefined
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  } else if (options.form) {
    body = options.form
  }
  const response = await fetch(path, {
    method: options.method ?? (body ? 'POST' : 'GET'),
    headers,
    body,
    signal: options.signal,
    keepalive: options.keepalive,
    credentials: 'same-origin',
  })
  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      const data = await response.json()
      detail = data?.detail ?? data
    } catch {
      // not JSON
    }
    throw new ApiError(response.status, detail)
  }
  return response
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function apiBlob(path: string, options: RequestOptions = {}): Promise<Response> {
  return send(path, options)
}

export function query(params: Record<string, string | number | boolean | null | undefined>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}
