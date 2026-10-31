import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import { printer } from './fixtures'

export function png(warnings: string[] = [], labelCount = 1) {
  return new HttpResponse(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), {
    headers: {
      'Content-Type': 'image/png',
      'X-Render-Warnings': JSON.stringify(warnings),
      'X-Label-Count': String(labelCount),
    },
  })
}

export const defaultHandlers = [
  http.get('/api/me', () =>
    HttpResponse.json({ sub: 'local', email: null, name: 'Local user', auth_enabled: false }),
  ),
  http.get('/api/printers', () => HttpResponse.json([printer])),
  http.get('/api/printers/:id/status', () =>
    HttpResponse.json({ online: true, ready: true, problems: [], error: null, details: {} }),
  ),
  http.get('/api/labels/tags', () => HttpResponse.json([])),
  http.post('/api/render', () => png()),
  http.post('/api/zpl/printer-settings', async ({ request }) => {
    const { zpl } = (await request.json()) as { zpl: string }
    return HttpResponse.json({ zpl, removed: [], kept: [] })
  }),
  http.get('/api/drafts/:name', ({ params }) =>
    HttpResponse.json({ name: params.name, data: {}, updated_at: null }),
  ),
  http.put('/api/drafts/:name', async ({ params, request }) => {
    const { data } = (await request.json()) as { data: unknown }
    return HttpResponse.json({ name: params.name, data, updated_at: '2026-10-10T12:00:00Z' })
  }),
  http.get('/api/printers/label-settings', () =>
    HttpResponse.json([
      {
        group: 'media',
        title: 'Media type and tracking',
        commands: ['ML', 'MN', 'MT'],
        default: 'label',
      },
      {
        group: 'print_mode',
        title: 'Print mode (tear-off, peel, cutter) and backfeed',
        commands: ['JS', 'MM', 'XB'],
        default: 'printer',
      },
    ]),
  ),
]

export const server = setupServer(...defaultHandlers)
