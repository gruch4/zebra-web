import type {
  MediaTracking,
  PrintMethod,
  PrintMode,
  PrinterSetting,
  PrinterSettingsUpdate,
} from '../api/types'
import { MM_PER_INCH, dotsPerMm, dotsToMm, ipsToMmPerSecond, mmToDots } from './units'

export type SettingsForm = {
  [K in keyof Required<PrinterSettingsUpdate>]: PrinterSettingsUpdate[K] | null
}

export const NUMBER_LIMITS: Record<string, { min: number; max: number }> = {
  print_width: { min: 2, max: 1344 },
  label_length: { min: 1, max: 32000 },
  darkness: { min: 0, max: 30 },
  speed: { min: 1, max: 14 },
  tear_off: { min: -120, max: 120 },
  label_top: { min: -120, max: 120 },
  label_shift: { min: -9999, max: 9999 },
}

function toInt(value: string | null): number | null {
  if (value == null) return null
  const parsed = Math.round(parseFloat(value))
  return Number.isNaN(parsed) ? null : parsed
}

function tracking(value: string): MediaTracking | null {
  const v = value.toLowerCase()
  if (v.includes('variable')) return 'variable'
  if (v.includes('continuous')) return 'continuous'
  if (v.includes('mark') || v.includes('bar')) return 'mark'
  if (v.includes('gap') || v.includes('web') || v.includes('notch') || v === 'label') return 'gap'
  return null
}

function method(value: string): PrintMethod | null {
  const v = value.toLowerCase()
  if (v.includes('direct')) return 'direct'
  if (v.includes('trans')) return 'transfer'
  return null
}

function mode(value: string): PrintMode | null {
  const v = value.toLowerCase()
  const modes: [string, PrintMode][] = [
    ['delayed', 'delayed_cut'],
    ['tear', 'tear'],
    ['peel', 'peel'],
    ['rewind', 'rewind'],
    ['cut', 'cutter'],
    ['applicator', 'applicator'],
    ['kiosk', 'kiosk'],
  ]
  return modes.find(([key]) => v.includes(key))?.[1] ?? null
}

/** Convert the printer's reported SGD values into form values. */
export function settingsToForm(settings: PrinterSetting[]): SettingsForm {
  const raw = Object.fromEntries(settings.map((s) => [s.name, s.value]))
  const text = (name: string) => (raw[name] ? String(raw[name]) : '')
  return {
    print_width: toInt(raw.print_width ?? null),
    label_length: toInt(raw.label_length ?? null),
    darkness: toInt(raw.darkness ?? null),
    speed: toInt(raw.speed ?? null),
    media_tracking: text('media_tracking') ? tracking(text('media_tracking')) : null,
    print_method: text('print_method') ? method(text('print_method')) : null,
    print_mode: text('print_mode') ? mode(text('print_mode')) : null,
    tear_off: toInt(raw.tear_off ?? null),
    label_top: toInt(raw.label_top ?? null),
    label_shift: toInt(raw.label_shift ?? null),
    orientation: text('orientation')
      ? text('orientation').toLowerCase().startsWith('inv')
        ? 'inverted'
        : 'normal'
      : null,
  }
}

/** Only the fields that changed and have a value. */
export function changedSettings(
  initial: SettingsForm,
  current: SettingsForm,
): PrinterSettingsUpdate {
  const update: Record<string, unknown> = {}
  for (const key of Object.keys(current) as (keyof SettingsForm)[]) {
    if (current[key] != null && current[key] !== initial[key]) update[key] = current[key]
  }
  return update as PrinterSettingsUpdate
}

export function validateSettings(form: SettingsForm): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const [key, { min, max }] of Object.entries(NUMBER_LIMITS)) {
    const value = form[key as keyof SettingsForm]
    if (typeof value === 'number' && (value < min || value > max || !Number.isInteger(value))) {
      errors[key] = `Must be a whole number between ${min} and ${max}`
    }
  }
  return errors
}

// ---- millimetre display ------------------------------------------------------------------
// The printer works in dots and inches per second; the UI shows millimetres and mm/s.

export const LENGTH_FIELDS = [
  'print_width',
  'label_length',
  'tear_off',
  'label_top',
  'label_shift',
] as const

type LengthField = (typeof LENGTH_FIELDS)[number]

export function isLengthField(key: string): key is LengthField {
  return (LENGTH_FIELDS as readonly string[]).includes(key)
}

/** Dots per unit of a setting: ~TA steps are two dots on 600 dpi printers (p.273). */
function dotsPerStep(key: LengthField, dpi: number): number {
  return key === 'tear_off' && dpi >= 600 ? 2 : 1
}

/** Form values for display: lengths in mm (2 decimals round-trip exactly to dots). */
export function toDisplay(form: SettingsForm, dpi: number): SettingsForm {
  const display = { ...form }
  for (const key of LENGTH_FIELDS) {
    const value = form[key]
    display[key] = value == null ? null : dotsToMm(value * dotsPerStep(key, dpi), dpi, 2)
  }
  return display
}

/** Convert displayed values (lengths in mm) back to the dots the printer uses. */
export function fromDisplay(display: SettingsForm, dpi: number): SettingsForm {
  const form = { ...display }
  for (const key of LENGTH_FIELDS) {
    const mm = display[key]
    form[key] = mm == null ? null : Math.round(mmToDots(mm, dpi) / dotsPerStep(key, dpi))
  }
  return form
}

export function displayLimits(key: string, dpi: number): { min: number; max: number } | undefined {
  const limits = NUMBER_LIMITS[key]
  if (!limits || !isLengthField(key)) return limits
  const step = dotsPerStep(key, dpi)
  return { min: dotsToMm(limits.min * step, dpi, 2), max: dotsToMm(limits.max * step, dpi, 2) }
}

/** Validate displayed values; length errors are reported in millimetres. */
export function validateDisplay(display: SettingsForm, dpi: number): Record<string, string> {
  const errors = validateSettings(fromDisplay(display, dpi))
  for (const key of Object.keys(errors)) {
    if (isLengthField(key)) {
      const { min, max } = displayLimits(key, dpi)!
      errors[key] = `Must be between ${min} and ${max} mm`
    }
  }
  return errors
}

/** "2 to 832" in dots becomes "0.25 – 104.1 mm"; other choices are returned unchanged. */
export function describeChoices(key: string, choices: string | null, dpi: number): string | null {
  if (!choices) return null
  const range = /^\s*(-?\d+(?:\.\d+)?)\s+to\s+(-?\d+(?:\.\d+)?)\s*$/i.exec(choices)
  if (range && isLengthField(key)) {
    return `${dotsToMm(Number(range[1]), dpi, 2)} – ${dotsToMm(Number(range[2]), dpi, 2)} mm`
  }
  if (range && key === 'speed') {
    return `${ipsToMmPerSecond(Number(range[1]))} – ${ipsToMmPerSecond(Number(range[2]))} mm/s`
  }
  return choices
}

/** Print speed choices: the printer takes inches per second, the UI shows mm/s. */
export function speedOptions(choices: string | null): { value: string; label: string }[] {
  const range = /(\d+)\s+to\s+(\d+)/i.exec(choices ?? '')
  const [low, high] = range ? [Number(range[1]), Number(range[2])] : [2, 6]
  const options = []
  for (let ips = low; ips <= high; ips++) {
    // ^PR has no 7 ips: its rates are 2-6 and 8-12 ips (p.245).
    if (ips === 7) continue
    options.push({ value: String(ips), label: `${ipsToMmPerSecond(ips)} mm/s` })
  }
  return options
}

/** Device info shown in metric units. */
export function formatDeviceInfo(key: string, value: string | null): string {
  if (value == null) return '—'
  if (key === 'odometer') {
    const cm = /(\d+)\s*CENTIMETERS/i.exec(value)
    if (cm)
      return `${(Number(cm[1]) / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })} m`
    const inches = /(\d+)\s*INCHES/i.exec(value)
    if (inches) return `${Math.round((Number(inches[1]) * MM_PER_INCH) / 10) / 100} m`
  }
  if (key === 'head_resolution' && /^\d+$/.test(value.trim())) {
    const dpi = Number(value)
    return `${dpi} dpi (${dotsPerMm(dpi)} dots/mm)`
  }
  return value
}
