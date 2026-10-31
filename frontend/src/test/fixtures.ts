import type { LabelSummary, Printer, VariableDef } from '../api/types'

export const printer: Printer = {
  id: 1,
  name: 'ZD420t',
  host: '192.168.1.50',
  port: 9100,
  dpi: 203,
  model: 'ZD420t-203dpi',
  firmware: 'V84',
  is_default: true,
  label_settings: {
    media: 'label',
    darkness_speed: 'label',
    position: 'label',
    print_mode: 'printer',
  },
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

export function variable(name: string, extra: Partial<VariableDef> = {}): VariableDef {
  return { name, label: '', default: '', required: true, type: 'text', help: '', ...extra }
}

export function label(extra: Partial<LabelSummary> = {}): LabelSummary {
  return {
    id: 7,
    name: 'Price tag',
    description: '',
    kind: 'zpl',
    width_mm: 50,
    height_mm: 25,
    dpi: 203,
    tags: [],
    variables: [],
    created_by: 'me',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    ...extra,
  }
}
