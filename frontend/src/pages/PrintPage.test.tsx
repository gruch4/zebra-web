import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { label, variable } from '../test/fixtures'
import { png, server } from '../test/server'
import { renderRoute } from '../test/render'

// CodeMirror needs real layout; a textarea is enough to drive the page.
vi.mock('../components/ZplEditor', () => ({
  ZplEditor: ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <textarea aria-label="ZPL code" value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}))

describe('Print ZPL page', () => {
  it('renders a preview of the typed ZPL with filled variables and prints it', async () => {
    const renders: { zpl: string; variables: Record<string, string>; dpi: number }[] = []
    const printed: unknown[] = []
    server.use(
      http.post('/api/render', async ({ request }) => {
        renders.push(
          (await request.json()) as { zpl: string; variables: Record<string, string>; dpi: number },
        )
        return png(['Unsupported command ^QQ ignored'])
      }),
      http.post('/api/print', async ({ request }) => {
        printed.push(await request.json())
        return HttpResponse.json({ status: 'sent', printer_name: 'ZD420t' })
      }),
    )
    const { user } = renderRoute('/')

    const editor = await screen.findByDisplayValue(/Hello from Zebra Web/)
    fireEvent.change(editor, { target: { value: '^XA^FO10,10^FDHello {{name}}^FS^XZ' } })

    const field = await screen.findByLabelText(/name/)
    await user.type(field, 'World')

    await waitFor(() =>
      expect(renders.at(-1)).toMatchObject({
        zpl: '^XA^FO10,10^FDHello {{name}}^FS^XZ',
        variables: { name: 'World' },
        dpi: 203,
      }),
    )
    expect(await screen.findByText('Unsupported command ^QQ ignored')).toBeInTheDocument()
    expect(await screen.findByAltText('Label preview')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Print on ZD420t/ }))
    await waitFor(() => expect(printed).toHaveLength(1))
    expect(printed[0]).toEqual({
      zpl: '^XA^FO10,10^FDHello {{name}}^FS^XZ',
      printer_id: 1,
      variables: { name: 'World' },
      definitions: [variable('name')],
      copies: 1,
      source: 'raw',
      keep_printer_settings: false,
    })
  })

  it('blocks printing until required variables are filled', async () => {
    const print = vi.fn()
    server.use(
      http.post('/api/print', () => {
        print()
        return HttpResponse.json({})
      }),
    )
    const { user } = renderRoute('/')
    fireEvent.change(await screen.findByDisplayValue(/Hello from Zebra Web/), {
      target: { value: '^XA^FD{{sku}}^FS^XZ' },
    })
    await user.click(await screen.findByRole('button', { name: /Print on/ }))
    expect(await screen.findByText('sku is required')).toBeInTheDocument()
    expect(print).not.toHaveBeenCalled()
  })

  it('shows which embedded settings are used and which the printer replaces', async () => {
    const renders: { strip_printer_settings: boolean; printer_id: number | null }[] = []
    const printed: { keep_printer_settings: boolean }[] = []
    server.use(
      http.post('/api/zpl/printer-settings', () =>
        HttpResponse.json({
          zpl: '^XA~SD15^FO0,0^FDa^FS^XZ',
          kept: [{ command: '~SD15', description: 'darkness', group: 'darkness_speed' }],
          removed: [
            { command: '^MMC', description: 'print mode', group: 'print_mode' },
            { command: '^JUS', description: 'save or restore configuration', group: null },
          ],
        }),
      ),
      http.post('/api/render', async ({ request }) => {
        renders.push(
          (await request.json()) as { strip_printer_settings: boolean; printer_id: number | null },
        )
        return png()
      }),
      http.post('/api/print', async ({ request }) => {
        printed.push((await request.json()) as { keep_printer_settings: boolean })
        return HttpResponse.json({ status: 'sent', printer_name: 'ZD420t' })
      }),
    )
    const { user } = renderRoute('/')
    const editor = await screen.findByDisplayValue(/Hello from Zebra Web/)
    fireEvent.change(editor, { target: { value: '^XA~SD15^MMC^FO0,0^FDa^FS^JUS^XZ' } })

    expect(await screen.findByText('Printer settings in this ZPL')).toBeInTheDocument()
    expect(screen.getByText('Used from the label:')).toBeInTheDocument()
    expect(screen.getByText('~SD15')).toBeInTheDocument()
    expect(screen.getByText('Replaced by the printer’s own settings:')).toBeInTheDocument()
    expect(screen.getByText('^MMC')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Choose which settings come from the label' }),
    ).toHaveAttribute('href', '/printers/1')
    await waitFor(() =>
      expect(renders.at(-1)).toMatchObject({ strip_printer_settings: true, printer_id: 1 }),
    )

    await user.click(screen.getByLabelText('Send all settings unchanged'))
    await waitFor(() => expect(renders.at(-1)?.strip_printer_settings).toBe(false))
    await user.click(screen.getByRole('button', { name: /Print on/ }))
    await waitFor(() => expect(printed.at(-1)?.keep_printer_settings).toBe(true))

    await user.click(screen.getByRole('button', { name: 'Remove replaced settings from editor' }))
    expect(screen.getByLabelText('ZPL code')).toHaveValue('^XA~SD15^FO0,0^FDa^FS^XZ')
  })

  it('restores the last ZPL of the user and saves changes', async () => {
    const saved: { zpl: string; width_mm: number | '' }[] = []
    server.use(
      http.get('/api/drafts/print-zpl', () =>
        HttpResponse.json({
          name: 'print-zpl',
          data: { zpl: '^XA^FDmine^FS^XZ', width_mm: 50, height_mm: '', values: {} },
          updated_at: '2026-10-09T10:00:00Z',
        }),
      ),
      http.put('/api/drafts/print-zpl', async ({ request }) => {
        const { data } = (await request.json()) as { data: { zpl: string; width_mm: number | '' } }
        saved.push(data)
        return HttpResponse.json({ name: 'print-zpl', data, updated_at: '2026-10-10T12:00:00Z' })
      }),
    )
    renderRoute('/')
    const editor = await screen.findByDisplayValue('^XA^FDmine^FS^XZ')
    expect(screen.getByLabelText('Width (mm)')).toHaveValue('50')

    fireEvent.change(editor, { target: { value: '^XA^FDchanged^FS^XZ' } })
    await waitFor(
      () => expect(saved.at(-1)).toMatchObject({ zpl: '^XA^FDchanged^FS^XZ', width_mm: 50 }),
      {
        timeout: 3000,
      },
    )
    expect(saved).toHaveLength(1) // restoring alone does not save
    expect(await screen.findByTestId('draft-status')).toHaveTextContent('Saved for you')
  })

  it('does not touch the draft while editing an archived label', async () => {
    const draftRequests: string[] = []
    server.use(
      http.get('/api/labels/7', () =>
        HttpResponse.json({ ...label(), zpl: '^XA^FDarchived^FS^XZ', design: null }),
      ),
      http.all('/api/drafts/:name', ({ request }) => {
        draftRequests.push(request.method)
        return HttpResponse.json({})
      }),
    )
    renderRoute('/?label=7')
    const editor = await screen.findByDisplayValue('^XA^FDarchived^FS^XZ')
    fireEvent.change(editor, { target: { value: '^XA^FDedited^FS^XZ' } })
    await new Promise((resolve) => setTimeout(resolve, 1200))
    expect(draftRequests).toEqual([])
  })

  it('previews and prints an archived label with its variable defaults', async () => {
    const renders: { zpl: string; variables: Record<string, string> }[] = []
    const printed: unknown[] = []
    server.use(
      http.get('/api/labels/7', () =>
        HttpResponse.json({
          ...label({
            variables: [variable('sku', { default: 'A1' }), variable('note', { required: false })],
          }),
          zpl: '^XA^FD{{sku}}{{note}}^FS^XZ',
          design: null,
        }),
      ),
      http.post('/api/render', async ({ request }) => {
        renders.push((await request.json()) as { zpl: string; variables: Record<string, string> })
        return png()
      }),
      http.post('/api/print', async ({ request }) => {
        printed.push(await request.json())
        return HttpResponse.json({ status: 'sent', printer_name: 'ZD420t' })
      }),
    )
    const { user } = renderRoute('/?label=7')
    await screen.findByDisplayValue('^XA^FD{{sku}}{{note}}^FS^XZ')
    await waitFor(() =>
      expect(renders.at(-1)).toMatchObject({
        zpl: '^XA^FD{{sku}}{{note}}^FS^XZ',
        variables: { sku: 'A1' },
      }),
    )

    await user.click(screen.getByRole('button', { name: /Print on ZD420t/ }))
    await waitFor(() => expect(printed).toHaveLength(1))
    expect(printed[0]).toMatchObject({
      zpl: '^XA^FD{{sku}}{{note}}^FS^XZ',
      variables: {},
      definitions: [variable('sku', { default: 'A1' }), variable('note', { required: false })],
    })
  })

  it('removes replaced settings from the ZPL that is in the editor now', async () => {
    server.use(
      http.post('/api/zpl/printer-settings', async ({ request }) => {
        const { zpl } = (await request.json()) as { zpl: string }
        return HttpResponse.json({
          zpl: zpl.replace('^MMC', ''),
          kept: [],
          removed: zpl.includes('^MMC')
            ? [{ command: '^MMC', description: 'print mode', group: 'print_mode' }]
            : [],
        })
      }),
    )
    const { user } = renderRoute('/')
    const editor = await screen.findByDisplayValue(/Hello from Zebra Web/)
    fireEvent.change(editor, { target: { value: '^XA^MMC^FDfirst^FS^XZ' } })
    await screen.findByRole('button', { name: 'Remove replaced settings from editor' })

    // Edit again and click before the (debounced) analysis catches up.
    fireEvent.change(editor, { target: { value: '^XA^MMC^FDsecond^FS^XZ' } })
    await user.click(screen.getByRole('button', { name: 'Remove replaced settings from editor' }))
    await waitFor(() => expect(editor).toHaveValue('^XA^FDsecond^FS^XZ'))
  })

  it('shows the label as it was left after visiting another page', async () => {
    const saved: { zpl: string; copies: number }[] = []
    server.use(
      http.put('/api/drafts/print-zpl', async ({ request }) => {
        const { data } = (await request.json()) as { data: { zpl: string; copies: number } }
        saved.push(data)
        return HttpResponse.json({ name: 'print-zpl', data, updated_at: '2026-10-10T12:00:00Z' })
      }),
    )
    const { user } = renderRoute('/')
    const editor = await screen.findByDisplayValue(/Hello from Zebra Web/)
    fireEvent.change(editor, { target: { value: '^XA^FDleft here^FS^XZ' } })
    fireEvent.change(screen.getByLabelText('Copies'), { target: { value: '4' } })

    // Leave immediately, before the autosave delay, and come back.
    await user.click(screen.getByRole('link', { name: 'Printers' }))
    await screen.findByRole('heading', { name: 'Printers' })
    await waitFor(() =>
      expect(saved.at(-1)).toMatchObject({ zpl: '^XA^FDleft here^FS^XZ', copies: 4 }),
    )
    await user.click(screen.getByRole('link', { name: 'Print ZPL' }))

    expect(await screen.findByDisplayValue('^XA^FDleft here^FS^XZ')).toBeInTheDocument()
    expect(screen.getByLabelText('Copies')).toHaveValue('4')
  })
})
