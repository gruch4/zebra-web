import { describe, expect, it } from 'vitest'

import type { PrinterSetting } from '../api/types'
import { variable } from '../test/fixtures'
import { autoMap, buildRows } from './batch'
import {
  changedSettings,
  describeChoices,
  displayLimits,
  formatDeviceInfo,
  fromDisplay,
  settingsToForm,
  speedOptions,
  toDisplay,
  validateDisplay,
  validateSettings,
} from './printerSettings'
import {
  extractVariables,
  initialValues,
  mergeVariables,
  validateValue,
  variableErrors,
} from './templating'
import { endOfLocalDay } from './format'
import { dotsToMm, mmToDots } from './units'

describe('endOfLocalDay', () => {
  it('is the last second of that day in local time, with an explicit offset', () => {
    const iso = endOfLocalDay('2026-10-20')
    expect(iso).toMatch(/Z$/)
    const date = new Date(iso)
    expect([date.getFullYear(), date.getMonth(), date.getDate()]).toEqual([2026, 9, 20])
    expect([date.getHours(), date.getMinutes(), date.getSeconds()]).toEqual([23, 59, 59])
  })
})

describe('templating', () => {
  it('extracts unique variables without built-ins', () => {
    expect(extractVariables('{{ a }} {{b}} {{a}} {{date}}', null, '{{c.d}}')).toEqual([
      'a',
      'b',
      'c.d',
    ])
  })

  it('merges metadata and validates values', () => {
    const merged = mergeVariables(['a', 'b'], [variable('a', { label: 'A' }), variable('gone')])
    expect(merged.map((v) => [v.name, v.label])).toEqual([
      ['a', 'A'],
      ['b', ''],
    ])
    expect(validateValue(variable('x'), '')).toBe('is required')
    expect(validateValue(variable('x', { required: false }), '')).toBeNull()
    // ^ and ~ are written as hex codes in field data (the server checks where they go).
    expect(validateValue(variable('x'), 'a^b')).toBeNull()
    expect(validateValue(variable('x', { type: 'number' }), '1,5')).toBeNull()
    expect(validateValue(variable('x', { type: 'number' }), 'abc')).toBe('must be a number')
    expect(validateValue(variable('x', { type: 'date' }), '01.02.2026')).toMatch(/date/)
    // Same rules as the server: a real calendar date in YYYY-MM-DD form.
    for (const bad of ['2024-13-45', '2023-02-29', '20240101', '2024-1-2']) {
      expect(validateValue(variable('x', { type: 'date' }), bad)).toMatch(/date/)
    }
    expect(validateValue(variable('x', { type: 'date' }), '2024-02-29')).toBeNull()
  })

  it('reports errors using defaults', () => {
    const defs = [variable('a', { default: 'x' }), variable('b')]
    expect(initialValues(defs)).toEqual({ a: 'x', b: '' })
    expect(variableErrors(defs, {})).toEqual({ b: 'is required' })
  })
})

describe('batch rows', () => {
  it('auto-maps columns by normalized name', () => {
    expect(autoMap(['Product Name', 'SKU'], ['product_name', 'sku', 'price'])).toEqual({
      product_name: 'Product Name',
      sku: 'SKU',
      price: null,
    })
  })

  it('builds and validates rows with constants, defaults and copies', () => {
    const defs = [
      variable('name'),
      variable('price', { type: 'number' }),
      variable('shop', { default: 'Main' }),
    ]
    const rows = buildRows(
      [
        { n: 'A', p: '1', c: '3' },
        { n: '', p: 'x', c: '0' },
      ],
      defs,
      { name: 'n', price: 'p', shop: null },
      { shop: '' },
      'c',
    )
    expect(rows[0]).toEqual({
      index: 0,
      values: { name: 'A', price: '1', shop: 'Main' },
      copies: 3,
      errors: [],
    })
    expect(rows[1].errors).toEqual([
      'name is required',
      'price must be a number',
      'copies must be a whole number between 1 and 1000',
    ])
  })
})

describe('printer settings', () => {
  const settings: PrinterSetting[] = [
    { name: 'print_width', label: '', value: '832', choices: null },
    { name: 'darkness', label: '', value: '15.0', choices: null },
    { name: 'media_tracking', label: '', value: 'gap/notch', choices: null },
    { name: 'print_method', label: '', value: 'thermal trans', choices: null },
    { name: 'print_mode', label: '', value: 'tear off', choices: null },
    { name: 'orientation', label: '', value: 'invert', choices: null },
    { name: 'speed', label: '', value: null, choices: null },
  ]

  it('converts printer values into form values', () => {
    const form = settingsToForm(settings)
    expect(form).toMatchObject({
      print_width: 832,
      darkness: 15,
      media_tracking: 'gap',
      print_method: 'transfer',
      print_mode: 'tear',
      orientation: 'inverted',
      speed: null,
    })
  })

  it('sends only changed values and validates ranges', () => {
    const initial = settingsToForm(settings)
    expect(changedSettings(initial, { ...initial, darkness: 20, speed: null })).toEqual({
      darkness: 20,
    })
    expect(validateSettings({ ...initial, darkness: 31 })).toHaveProperty('darkness')
    expect(validateSettings(initial)).toEqual({})
  })
})

describe('printer settings in millimetres', () => {
  const form = settingsToForm([
    { name: 'print_width', label: '', value: '832', choices: null },
    { name: 'label_length', label: '', value: '1218', choices: null },
    { name: 'tear_off', label: '', value: '-12', choices: null },
    { name: 'darkness', label: '', value: '15.0', choices: null },
  ])

  it('round-trips lengths through millimetres without changing the dots', () => {
    for (const dpi of [203, 300, 600]) {
      const display = toDisplay(form, dpi)
      expect(changedSettings(form, fromDisplay(display, dpi))).toEqual({})
    }
    expect(toDisplay(form, 203)).toMatchObject({
      // 8 dots/mm: an 832-dot printhead is 104 mm wide
      print_width: 104,
      label_length: 152.25,
      tear_off: -1.5,
      darkness: 15,
    })
    expect(fromDisplay({ ...toDisplay(form, 300), print_width: 100 }, 300).print_width).toBe(1200)
  })

  it('reports length errors and ranges in millimetres, speed in mm/s', () => {
    const display = { ...toDisplay(form, 203), print_width: 500 }
    expect(validateDisplay(display, 203)).toEqual({
      print_width: 'Must be between 0.25 and 168 mm',
    })
    expect(describeChoices('label_length', '1 to 32000', 203)).toBe('0.13 – 4000 mm')
    expect(describeChoices('darkness', '0.0 to 30.0', 203)).toBe('0.0 to 30.0')
    expect(describeChoices('speed', '2 to 6', 203)).toBe('51 – 152 mm/s')
    expect(speedOptions('2 to 4')).toEqual([
      { value: '2', label: '51 mm/s' },
      { value: '3', label: '76 mm/s' },
      { value: '4', label: '102 mm/s' },
    ])
    // ^PR has no 7 ips.
    expect(speedOptions('6 to 8').map((o) => o.value)).toEqual(['6', '8'])
  })

  it('doubles the tear-off step on 600 dpi printers', () => {
    // ~TA -12 is 12 dots at 203 dpi (1.5 mm) but 24 dots at 600 dpi (1 mm).
    expect(toDisplay(form, 600).tear_off).toBe(-1)
    expect(fromDisplay({ ...toDisplay(form, 600), tear_off: 2 }, 600).tear_off).toBe(24)
    expect(displayLimits('tear_off', 600)).toEqual({ min: -10, max: 10 })
  })

  it('formats device information in metric units', () => {
    expect(formatDeviceInfo('odometer', '1234 INCHES, 3134 CENTIMETERS')).toBe('31.34 m')
    expect(formatDeviceInfo('odometer', '100 INCHES')).toBe('2.54 m')
    expect(formatDeviceInfo('head_resolution', '300')).toBe('300 dpi (12 dots/mm)')
    expect(formatDeviceInfo('firmware', null)).toBe('—')
  })
})

describe('units', () => {
  it('converts between mm and dots', () => {
    // Printheads are 8, 12 or 24 dots/mm, not exactly 203, 300 or 600 dots per inch.
    expect(mmToDots(25.4, 203)).toBe(203)
    expect(mmToDots(100, 300)).toBe(1200)
    expect(mmToDots(100, 600)).toBe(2400)
    expect(dotsToMm(812, 203)).toBe(101.5)
  })
})
