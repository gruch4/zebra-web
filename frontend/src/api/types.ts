import type { Design } from '../designer/types'

export interface Page<T> {
  items: T[]
  total: number
}

export interface User {
  sub: string
  email: string | null
  name: string | null
  auth_enabled: boolean
}

export interface Printer {
  id: number
  name: string
  host: string
  port: number
  dpi: number
  model: string | null
  firmware: string | null
  is_default: boolean
  label_settings: Record<string, SettingSource>
  created_at: string
  updated_at: string
}

/** Whether a group of printer settings embedded in labels comes from the label or the printer. */
export type SettingSource = 'label' | 'printer'

export interface LabelSettingsGroup {
  group: string
  title: string
  commands: string[]
  default: SettingSource
}

export type PrinterInput = Pick<Printer, 'name' | 'host' | 'port' | 'dpi' | 'is_default'> & {
  model?: string | null
  firmware?: string | null
}

export interface ConnectionTestResult {
  ok: boolean
  model: string | null
  firmware: string | null
  dpi: number | null
  error: string | null
}

export interface PrinterStatus {
  online: boolean
  ready: boolean
  problems: string[]
  error: string | null
  details: Record<string, unknown> | null
}

export interface PrinterSetting {
  name: string
  label: string
  value: string | null
  choices: string | null
}

export interface PrinterSettingsResponse {
  settings: PrinterSetting[]
  info: Record<string, string | null>
}

export interface RawSetting {
  key: string
  value: string
  choices: string | null
}

export interface PrinterAction {
  action: string
  description: string
}

export type MediaTracking = 'continuous' | 'gap' | 'mark' | 'variable'
export type PrintMethod = 'direct' | 'transfer'
export type PrintMode =
  'tear' | 'peel' | 'rewind' | 'cutter' | 'applicator' | 'delayed_cut' | 'kiosk'

export interface PrinterSettingsUpdate {
  print_width?: number
  label_length?: number
  darkness?: number
  speed?: number
  media_tracking?: MediaTracking
  print_method?: PrintMethod
  print_mode?: PrintMode
  tear_off?: number
  label_top?: number
  label_shift?: number
  orientation?: 'normal' | 'inverted'
}

export type VariableType = 'text' | 'number' | 'date'

export interface VariableDef {
  name: string
  label: string
  default: string
  required: boolean
  type: VariableType
  help: string
}

export type LabelKind = 'zpl' | 'design'

export interface LabelSummary {
  id: number
  name: string
  description: string
  kind: LabelKind
  width_mm: number | null
  height_mm: number | null
  dpi: number
  tags: string[]
  variables: VariableDef[]
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface Label extends LabelSummary {
  zpl: string
  design: Design | null
}

export interface LabelInput {
  name: string
  description?: string
  kind: LabelKind
  zpl?: string
  design?: Design
  width_mm?: number | null
  height_mm?: number | null
  dpi?: number
  tags?: string[]
  variables?: VariableDef[]
}

export type LabelUpdate = Partial<Omit<LabelInput, 'kind'>>

export type JobSource = 'raw' | 'designer' | 'archive' | 'reprint' | 'template' | 'batch' | 'api'

export type ApiTokenStatus = 'active' | 'expired' | 'revoked'

export interface ApiToken {
  id: number
  name: string
  prefix: string
  owner: string
  /** Made before login was enabled; every logged-in user can manage it. */
  shared: boolean
  status: ApiTokenStatus
  created_at: string
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiTokenCreated extends ApiToken {
  /** The secret; the server shows it only once. */
  token: string
}

export interface PrintJob {
  id: number
  printer_id: number | null
  printer_name: string
  printer_host: string
  dpi: number
  label_id: number | null
  label_name: string | null
  source: JobSource
  zpl: string
  variables: Record<string, string>
  copies: number
  status: 'sent' | 'failed'
  error: string | null
  duration_ms: number | null
  batch_id: number | null
  batch_row: number | null
  created_by: string | null
  created_at: string
}

export interface PrintRequest {
  printer_id?: number | null
  zpl?: string
  label_id?: number
  design?: Design
  variables?: Record<string, string>
  /** Metadata of the zpl or design variables; labels use their stored definitions. */
  definitions?: VariableDef[]
  copies?: number
  source?: JobSource
  keep_printer_settings?: boolean
}

export type BatchStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface Batch {
  id: number
  label_id: number | null
  label_name: string
  printer_id: number | null
  printer_name: string
  data_filename: string
  total: number
  sent: number
  failed: number
  status: BatchStatus
  error: string | null
  created_by: string | null
  created_at: string
  finished_at: string | null
}

export interface HistoryItem {
  kind: 'job' | 'batch'
  created_at: string
  job: PrintJob | null
  batch: Batch | null
}

export interface ParsedRow {
  index: number
  values: Record<string, string>
  copies: number
  errors: string[]
}

export interface ParseResult {
  format: string
  columns: string[]
  rows: Record<string, string>[]
  mapping: Record<string, string | null>
  copies_column: string | null
  preview: ParsedRow[]
  valid_count: number
  error_count: number
}

export interface BatchRequest {
  label_id: number
  printer_id?: number | null
  rows: Record<string, string>[]
  mapping: Record<string, string | null>
  constants: Record<string, string>
  copies_column: string | null
  selected?: number[] | null
  data_filename?: string
}

export interface DryRunResult {
  zpl: string
  count: number
  skipped: ParsedRow[]
}

export interface RenderInfo {
  image: string
  width: number
  height: number
  label_count: number
  warnings: string[]
}

export interface ElementPreview {
  image: string | null
  width: number
  height: number
  offset_x: number
  offset_y: number
  /** The field as the printer places it at ^FO (rotated), which can be larger than the ink. */
  field_width: number
  field_height: number
  warnings: string[]
}

export interface GraphicResult {
  width: number
  height: number
  bytes_per_row: number
  data: string
  zpl: string
  preview: string
}

export interface EmbeddedSetting {
  command: string
  description: string
  group: string | null
}

export interface PrinterSettingsInZpl {
  zpl: string // as it will be sent
  removed: EmbeddedSetting[] // replaced by the printer's own settings
  kept: EmbeddedSetting[] // used from the label
}

export interface Draft<T> {
  name: string
  data: Partial<T>
  updated_at: string | null
}
