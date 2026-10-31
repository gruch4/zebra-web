import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, query } from './client'
import type {
  ApiToken,
  ApiTokenCreated,
  Batch,
  ConnectionTestResult,
  Draft,
  HistoryItem,
  Label,
  LabelInput,
  LabelSettingsGroup,
  LabelSummary,
  LabelUpdate,
  Page,
  PrintJob,
  PrintRequest,
  Printer,
  PrinterAction,
  PrinterInput,
  PrinterSettingsInZpl,
  PrinterSettingsResponse,
  PrinterSettingsUpdate,
  PrinterStatus,
  RawSetting,
  SettingSource,
  User,
  VariableDef,
} from './types'

// ---- auth ---------------------------------------------------------------------------------

export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: () => api<User>('/api/me'), retry: false })
}

// ---- API tokens ---------------------------------------------------------------------------

export function useApiTokens() {
  return useQuery({ queryKey: ['api-tokens'], queryFn: () => api<ApiToken[]>('/api/tokens') })
}

export function useCreateApiToken() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; expires_at?: string | null }) =>
      api<ApiTokenCreated>('/api/tokens', { json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['api-tokens'] }),
  })
}

export function useRevokeApiToken() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/tokens/${id}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['api-tokens'] }),
  })
}

// ---- printers -----------------------------------------------------------------------------

export function usePrinters() {
  return useQuery({ queryKey: ['printers'], queryFn: () => api<Printer[]>('/api/printers') })
}

export function usePrinterStatus(id: number | null | undefined, refetchInterval = 10_000) {
  return useQuery({
    queryKey: ['printers', id, 'status'],
    queryFn: () => api<PrinterStatus>(`/api/printers/${id}/status`),
    enabled: id != null,
    refetchInterval,
  })
}

export function usePrinterSettings(id: number, enabled = true) {
  return useQuery({
    queryKey: ['printers', id, 'settings'],
    queryFn: () => api<PrinterSettingsResponse>(`/api/printers/${id}/settings`),
    retry: false,
    enabled,
  })
}

/** Read the settings from the printer again instead of the server's short-lived cache. */
export function useRefreshPrinterSettings(id: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<PrinterSettingsResponse>(`/api/printers/${id}/settings?refresh=true`),
    onSuccess: (data) => {
      client.setQueryData(['printers', id, 'settings'], data)
      client.invalidateQueries({ queryKey: ['printers', id, 'settings', 'raw'] })
    },
  })
}

export function useRawSettings(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ['printers', id, 'settings', 'raw'],
    queryFn: () => api<RawSetting[]>(`/api/printers/${id}/settings/raw`),
    enabled,
    retry: false,
  })
}

export function usePrinterActions() {
  return useQuery({
    queryKey: ['printer-actions'],
    queryFn: () => api<PrinterAction[]>('/api/printers/actions'),
    staleTime: Infinity,
  })
}

export function useSavePrinter() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: PrinterInput & { id?: number }) =>
      api<Printer>(id ? `/api/printers/${id}` : '/api/printers', {
        method: id ? 'PUT' : 'POST',
        json: body,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['printers'] }),
  })
}

export function useDeletePrinter() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/printers/${id}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['printers'] }),
  })
}

export function useLabelSettingsGroups() {
  return useQuery({
    queryKey: ['label-settings-groups'],
    queryFn: () => api<LabelSettingsGroup[]>('/api/printers/label-settings'),
    staleTime: Infinity,
  })
}

export function useUpdateLabelSettings(id: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, SettingSource>) =>
      api<Printer>(`/api/printers/${id}/label-settings`, { method: 'PUT', json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['printers'] }),
  })
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (body: { host: string; port: number }) =>
      api<ConnectionTestResult>('/api/printers/test', { json: body }),
  })
}

export function useWriteSettings(id: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: PrinterSettingsUpdate) =>
      api<{ sent: string }>(`/api/printers/${id}/settings`, { method: 'PUT', json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['printers', id, 'settings'] }),
  })
}

export function useRunAction(id: number) {
  return useMutation({
    mutationFn: (action: string) =>
      api<{ description: string }>(`/api/printers/${id}/actions/${action}`, { method: 'POST' }),
  })
}

// ---- printing -----------------------------------------------------------------------------

export function usePrint() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: PrintRequest) => api<PrintJob>('/api/print', { json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['history'] }),
  })
}

/** Printer settings embedded in ZPL and whether each is used or replaced on this printer. */
export function usePrinterSettingsInZpl(zpl: string, printerId: number | null | undefined) {
  return useQuery({
    queryKey: ['zpl-printer-settings', zpl, printerId],
    queryFn: () =>
      api<PrinterSettingsInZpl>('/api/zpl/printer-settings', {
        json: { zpl, printer_id: printerId ?? null },
      }),
    enabled: zpl.trim() !== '',
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  })
}

// ---- drafts -------------------------------------------------------------------------------

/** The current user's saved work in progress, stored on the server. */
export function useDraft<T>(name: string, enabled = true) {
  return useQuery({
    queryKey: ['drafts', name],
    queryFn: () => api<Draft<T>>(`/api/drafts/${name}`),
    enabled,
    staleTime: Infinity,
    retry: false,
  })
}

// ---- labels -------------------------------------------------------------------------------

export interface LabelFilters {
  q?: string
  tag?: string | null
  kind?: string | null
  has_variables?: boolean
  limit?: number
  offset?: number
}

export function useLabels(filters: LabelFilters) {
  return useQuery({
    queryKey: ['labels', filters],
    queryFn: () => api<Page<LabelSummary>>(`/api/labels${query({ ...filters })}`),
    placeholderData: keepPreviousData,
  })
}

export function useLabel(id: number | null | undefined) {
  return useQuery({
    queryKey: ['labels', id],
    queryFn: () => api<Label>(`/api/labels/${id}`),
    enabled: id != null,
  })
}

export function useLabelTags() {
  return useQuery({
    queryKey: ['labels', 'tags'],
    queryFn: () => api<string[]>('/api/labels/tags'),
  })
}

export function useLabelVariables(id: number | null | undefined) {
  return useQuery({
    queryKey: ['labels', id, 'variables'],
    queryFn: () => api<VariableDef[]>(`/api/labels/${id}/variables`),
    enabled: id != null,
  })
}

export function useSaveLabel() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: LabelInput | LabelUpdate }) =>
      api<Label>(id ? `/api/labels/${id}` : '/api/labels', {
        method: id ? 'PUT' : 'POST',
        json: body,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['labels'] }),
  })
}

export function useDeleteLabel() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/labels/${id}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['labels'] }),
  })
}

export function useDuplicateLabel() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<Label>(`/api/labels/${id}/duplicate`, { method: 'POST' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['labels'] }),
  })
}

export function useImportLabels() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (files: File[]) => {
      const form = new FormData()
      files.forEach((file) => form.append('files', file))
      return api<Label[]>('/api/labels/import', { form })
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ['labels'] }),
  })
}

// ---- history ------------------------------------------------------------------------------

export interface HistoryFilters {
  printer_id?: number | null
  status?: string | null
  source?: string | null
  q?: string
  date_from?: string | null
  date_to?: string | null
  limit: number
  offset: number
}

export function useHistory(filters: HistoryFilters) {
  return useQuery({
    queryKey: ['history', filters],
    queryFn: () => api<Page<HistoryItem>>(`/api/history${query({ ...filters })}`),
    placeholderData: keepPreviousData,
    refetchInterval: (q) =>
      q.state.data?.items.some(
        (item) => item.batch && ['queued', 'running'].includes(item.batch.status),
      )
        ? 2000
        : false,
  })
}

export const BATCH_JOBS_PAGE_SIZE = 100

export function useBatchJobs(batchId: number | null, page = 1) {
  return useQuery({
    queryKey: ['history', 'batch', batchId, 'jobs', page],
    queryFn: () =>
      api<Page<PrintJob>>(
        `/api/jobs${query({
          batch_id: batchId,
          limit: BATCH_JOBS_PAGE_SIZE,
          offset: (page - 1) * BATCH_JOBS_PAGE_SIZE,
        })}`,
      ),
    enabled: batchId != null,
    placeholderData: keepPreviousData,
  })
}

export function useBatch(id: number | null) {
  return useQuery({
    queryKey: ['batches', id],
    queryFn: () => api<Batch>(`/api/batches/${id}`),
    enabled: id != null,
    refetchInterval: (q) =>
      q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 1000 : false,
  })
}

export function useReprint() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      copies,
      printer_id,
    }: {
      id: number
      copies?: number
      printer_id?: number | null
    }) => api<PrintJob>(`/api/jobs/${id}/reprint`, { json: { copies, printer_id } }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['history'] }),
  })
}

export function useSaveJobAsLabel() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name }: { id: number; name?: string }) =>
      api<Label>(`/api/jobs/${id}/save-as-label`, { json: { name } }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['labels'] }),
  })
}
