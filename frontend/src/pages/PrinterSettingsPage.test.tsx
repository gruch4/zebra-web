import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { renderRoute } from '../test/render'
import { server } from '../test/server'

describe('Printer settings', () => {
  it('saves only changed settings and validates ranges', async () => {
    const writes: unknown[] = []
    const actions: string[] = []
    server.use(
      http.get('/api/printers/1/settings', () =>
        HttpResponse.json({
          settings: [
            { name: 'print_width', label: 'Print width', value: '832', choices: '2 to 832' },
            { name: 'darkness', label: 'Darkness', value: '15.0', choices: '0.0 to 30.0' },
            { name: 'speed', label: 'Print speed', value: '4', choices: '2 to 6' },
          ],
          info: { firmware: 'V84', odometer: '1234 INCHES, 3134 CENTIMETERS' },
        }),
      ),
      http.get('/api/printers/actions', () =>
        HttpResponse.json([
          { action: 'calibrate', description: 'Calibrate media and ribbon sensors' },
        ]),
      ),
      http.put('/api/printers/1/settings', async ({ request }) => {
        writes.push(await request.json())
        return HttpResponse.json({ sent: '' })
      }),
      http.post('/api/printers/1/actions/:action', ({ params }) => {
        actions.push(String(params.action))
        return HttpResponse.json({ description: 'ok' })
      }),
    )
    const { user } = renderRoute('/printers/1')

    const darkness = await screen.findByLabelText('Darkness')
    expect(darkness).toHaveValue('15')
    // Lengths are shown in millimetres, speed in mm/s, the odometer in metres.
    const width = screen.getByLabelText('Print width (mm)')
    expect(width).toHaveValue('104')
    expect(screen.getByText(/Allowed: 0.25 – 104 mm/)).toBeInTheDocument()
    expect(screen.getAllByLabelText('Print speed (mm/s)')[0]).toHaveValue('102 mm/s')
    expect(screen.getByText('31.34 m')).toBeInTheDocument()
    const save = screen.getByRole('button', { name: 'Save to printer' })
    expect(save).toBeDisabled()

    await user.clear(darkness)
    await user.type(darkness, '35')
    expect(await screen.findByText(/between 0 and 30/)).toBeInTheDocument()
    expect(save).toBeDisabled()

    await user.clear(darkness)
    await user.type(darkness, '22')
    await user.clear(width)
    await user.type(width, '50')
    await user.click(save)
    // 50 mm at 203 dpi is sent to the printer as 400 dots
    await waitFor(() => expect(writes).toEqual([{ darkness: 22, print_width: 400 }]))

    await user.click(screen.getByRole('button', { name: 'Calibrate media and ribbon sensors' }))
    await waitFor(() => expect(actions).toEqual(['calibrate']))
  })

  it('chooses which embedded label settings the printer replaces', async () => {
    const updates: unknown[] = []
    server.use(
      http.get('/api/printers/1/settings', () => HttpResponse.json({ settings: [], info: {} })),
      http.get('/api/printers/actions', () => HttpResponse.json([])),
      http.put('/api/printers/1/label-settings', async ({ request }) => {
        updates.push(await request.json())
        return HttpResponse.json({})
      }),
    )
    const { user } = renderRoute('/printers/1')
    expect(await screen.findByText('Printer settings inside labels')).toBeInTheDocument()
    expect(await screen.findByText('~JS ^MM ^XB')).toBeInTheDocument()
    const media = screen.getByRole('radiogroup', { name: 'Media type and tracking' })
    await user.click(within(media).getByLabelText('From printer'))
    await waitFor(() => expect(updates).toEqual([{ media: 'printer' }]))
  })

  it('reads the settings from the printer again on refresh', async () => {
    const reads: string[] = []
    server.use(
      http.get('/api/printers/1/settings', ({ request }) => {
        reads.push(new URL(request.url).search)
        return HttpResponse.json({ settings: [], info: {} })
      }),
      http.get('/api/printers/actions', () => HttpResponse.json([])),
    )
    const { user } = renderRoute('/printers/1')
    await waitFor(() => expect(reads).toEqual(['']))
    await user.click(await screen.findByRole('button', { name: 'Refresh settings' }))
    await waitFor(() => expect(reads).toEqual(['', '?refresh=true']))
  })
})
