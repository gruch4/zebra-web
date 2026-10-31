import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import type { Draft } from '../api/types'

const KEEPALIVE_LIMIT = 60_000

interface AutosaveState {
  saving: boolean
  savedAt: string | null
}

/**
 * Keep `value` as the user's draft `name`: the query cache is updated on every change (so the
 * page shows the latest state when it is opened again), the server copy shortly after the
 * user stops typing, and immediately when the page is left or the tab is closed.
 *
 * Pass `null` until the saved draft has been restored; the first value after that counts as
 * already saved.
 */
export function useAutosaveDraft<T>(
  name: string,
  value: T | null,
  { enabled = true, delay = 800 }: { enabled?: boolean; delay?: number } = {},
): AutosaveState {
  const client = useQueryClient()
  const [state, setState] = useState<AutosaveState>({ saving: false, savedAt: null })
  const json = value === null ? null : JSON.stringify(value)
  const latest = useRef<string | null>(null)
  const saved = useRef<string | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  // Cache first: navigating back to the page restores exactly this state.
  useEffect(() => {
    if (!enabled || json === null) return
    latest.current = json
    if (saved.current === null) saved.current = json // the restored state is already saved
    client.setQueryData<Draft<T>>(['drafts', name], (old) => ({
      name,
      data: JSON.parse(json) as T,
      updated_at: old?.updated_at ?? null,
    }))
  }, [client, enabled, json, name])

  // Then the server, once typing pauses.
  useEffect(() => {
    if (!enabled || json === null || json === saved.current) return
    const timer = setTimeout(() => {
      saved.current = json
      setState((s) => ({ ...s, saving: true }))
      api<Draft<T>>(`/api/drafts/${name}`, { method: 'PUT', json: { data: JSON.parse(json) } })
        .then((draft) => mounted.current && setState({ saving: false, savedAt: draft.updated_at }))
        .catch(() => {
          saved.current = null // retry with the next change
          if (mounted.current) setState((s) => ({ ...s, saving: false }))
        })
    }, delay)
    return () => clearTimeout(timer)
  }, [delay, enabled, json, name])

  // Leaving the page (or closing the tab) must not drop a pending save.
  useEffect(() => {
    if (!enabled) return
    const flush = (closing: boolean) => {
      const pending = latest.current
      if (pending === null || pending === saved.current) return
      saved.current = pending
      const body = { data: JSON.parse(pending) }
      void api(`/api/drafts/${name}`, {
        method: 'PUT',
        json: body,
        // Browsers only finish small requests (about 64 KB) once the tab is closed.
        keepalive: closing && pending.length < KEEPALIVE_LIMIT,
      }).catch(() => undefined)
    }
    const onPageHide = () => flush(true)
    window.addEventListener('pagehide', onPageHide)
    return () => {
      window.removeEventListener('pagehide', onPageHide)
      flush(false) // navigating within the app: the page stays alive, no limit applies
    }
  }, [enabled, name])

  return state
}
