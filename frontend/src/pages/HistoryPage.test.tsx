import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { HistoryItem, PrintJob } from '../api/types'
import { renderRoute } from '../test/render'
import { png, server } from '../test/server'

function job(id: number, extra: Partial<PrintJob> = {}): PrintJob {
  return {
    id,
    printer_id: 1,
    printer_name: 'ZD420t',
    printer_host: '192.168.1.50:9100',
    dpi: 203,
    label_id: null,
    label_name: 'Shipping',
    source: 'raw',
    zpl: '^XA^XZ',
    variables: {},
    copies: 1,
    status: 'sent',
    error: null,
    duration_ms: 5,
    batch_id: null,
    batch_row: null,
    created_by: 'me',
    created_at: '2026-01-01T10:00:00Z',
    ...extra,
  }
}

describe('Print history', () => {
  it('shows single jobs and expandable batches, and reprints', async () => {
    const items: HistoryItem[] = [
      {
        kind: 'job',
        created_at: '2026-01-02T00:00:00Z',
        job: job(1, { status: 'failed', error: 'Offline' }),
        batch: null,
      },
      {
        kind: 'batch',
        created_at: '2026-01-01T00:00:00Z',
        job: null,
        batch: {
          id: 5,
          label_id: 7,
          label_name: 'Price tag',
          printer_id: 1,
          printer_name: 'ZD420t',
          data_filename: 'prices.csv',
          total: 2,
          sent: 2,
          failed: 0,
          status: 'done',
          error: null,
          created_by: 'me',
          created_at: '2026-01-01T00:00:00Z',
          finished_at: null,
        },
      },
    ]
    const reprints: unknown[] = []
    server.use(
      http.get('/api/history', () => HttpResponse.json({ items, total: 2 })),
      http.get('/api/jobs', ({ request }) => {
        expect(new URL(request.url).searchParams.get('batch_id')).toBe('5')
        const offset = Number(new URL(request.url).searchParams.get('offset'))
        return HttpResponse.json({
          items: [
            job(10 + offset, {
              batch_id: 5,
              batch_row: offset,
              source: 'batch',
              label_name: 'Price tag',
            }),
          ],
          total: 250,
        })
      }),
      http.get('/api/jobs/:id/preview.png', () => png()),
      http.post('/api/jobs/1/reprint', async ({ request }) => {
        reprints.push(await request.json())
        return HttpResponse.json(job(2, { source: 'reprint' }))
      }),
    )
    const { user } = renderRoute('/history')

    expect(await screen.findByText('prices.csv')).toBeInTheDocument()
    expect(screen.getByText('2/2')).toBeInTheDocument()
    expect(screen.getByText('failed')).toBeInTheDocument()

    await user.click(screen.getByText('prices.csv'))
    expect(await screen.findByText('Row 1')).toBeInTheDocument()
    // Large batches are paged instead of being cut off.
    expect(screen.getByText('250 rows')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '3' }))
    expect(await screen.findByText('Row 201')).toBeInTheDocument()

    await user.click(screen.getByText('Shipping'))
    expect(await screen.findByText('Offline')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Reprint on ZD420t/ }))
    await waitFor(() => expect(reprints).toEqual([{ printer_id: 1 }]))
  })
})
