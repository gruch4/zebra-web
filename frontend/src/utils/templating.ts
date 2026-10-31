import type { VariableDef } from '../api/types'

export const BUILTIN_VARIABLES = ['date', 'time', 'datetime', 'year'] as const

const VARIABLE_RE = /\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}/g

/** Ordered unique variable names found in the texts, excluding built-ins. */
export function extractVariables(...texts: (string | null | undefined)[]): string[] {
  const names = new Set<string>()
  for (const text of texts) {
    for (const match of (text ?? '').matchAll(VARIABLE_RE)) {
      const name = match[1]
      if (!(BUILTIN_VARIABLES as readonly string[]).includes(name)) names.add(name)
    }
  }
  return [...names]
}

export function defaultVariable(name: string): VariableDef {
  return { name, label: '', default: '', required: true, type: 'text', help: '' }
}

/** Keep metadata for variables that still exist and add defaults for new ones. */
export function mergeVariables(names: string[], existing: VariableDef[]): VariableDef[] {
  const byName = new Map(existing.map((v) => [v.name, v]))
  return names.map((name) => byName.get(name) ?? defaultVariable(name))
}

/** A real calendar date written as YYYY-MM-DD (same rule as the server). */
export function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return (
    date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
  )
}

/**
 * Check a variable value. ^ and ~ are allowed: in field data the server writes them as hex
 * codes, and it refuses them where they would start ZPL commands.
 */
export function validateValue(definition: VariableDef, value: string): string | null {
  if (!value) return definition.required ? 'is required' : null
  if (definition.type === 'number' && Number.isNaN(Number(value.replace(',', '.')))) {
    return 'must be a number'
  }
  if (definition.type === 'date' && !isIsoDate(value)) {
    return 'must be a date (YYYY-MM-DD)'
  }
  return null
}

export function initialValues(definitions: VariableDef[]): Record<string, string> {
  return Object.fromEntries(definitions.map((d) => [d.name, d.default ?? '']))
}

export function variableErrors(
  definitions: VariableDef[],
  values: Record<string, string>,
): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const definition of definitions) {
    const error = validateValue(definition, values[definition.name] || definition.default || '')
    if (error) errors[definition.name] = error
  }
  return errors
}
