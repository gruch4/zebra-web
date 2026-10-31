export function formatDateTime(value: string | null | undefined): string {
  if (!value) return ''
  return new Date(value).toLocaleString()
}

/** The last second of a calendar day (YYYY-MM-DD) in the user's time zone, as an ISO timestamp. */
export function endOfLocalDay(date: string): string {
  return new Date(`${date}T23:59:59`).toISOString()
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
