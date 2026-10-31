import type { ParsedRow, VariableDef } from '../api/types'
import { mergeVariables, validateValue } from './templating'

export const MAX_COPIES = 1000

function normalize(name: string): string {
  return name.replace(/[\s_\-.]+/g, '').toLowerCase()
}

/** Map variables to columns with the same normalized name (mirrors the backend). */
export function autoMap(columns: string[], variables: string[]): Record<string, string | null> {
  const byNorm = new Map<string, string>()
  for (const column of columns) {
    if (!byNorm.has(normalize(column))) byNorm.set(normalize(column), column)
  }
  return Object.fromEntries(variables.map((name) => [name, byNorm.get(normalize(name)) ?? null]))
}

/** Resolve and validate every data row (the server validates again when printing). */
export function buildRows(
  rows: Record<string, string>[],
  definitions: VariableDef[],
  mapping: Record<string, string | null>,
  constants: Record<string, string>,
  copiesColumn: string | null,
): ParsedRow[] {
  const defs = mergeVariables(
    definitions.map((d) => d.name),
    definitions,
  )
  return rows.map((row, index) => {
    const values: Record<string, string> = {}
    const errors: string[] = []
    for (const definition of defs) {
      const column = mapping[definition.name]
      let value = constants[definition.name] || (column ? (row[column] ?? '') : '')
      value = value || definition.default
      const error = validateValue(definition, value)
      if (error) errors.push(`${definition.name} ${error}`)
      values[definition.name] = value
    }
    let copies = 1
    const rawCopies = copiesColumn ? (row[copiesColumn] ?? '').trim() : ''
    if (rawCopies) {
      const parsed = Math.trunc(Number(rawCopies))
      if (Number.isNaN(parsed) || parsed < 1 || parsed > MAX_COPIES) {
        errors.push(`copies must be a whole number between 1 and ${MAX_COPIES}`)
      } else {
        copies = parsed
      }
    }
    return { index, values, copies, errors }
  })
}
