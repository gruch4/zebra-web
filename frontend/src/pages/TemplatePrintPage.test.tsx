import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { ParseResult } from '../api/types'
import { label, variable } from '../test/fixtures'
import { renderRoute } from '../test/render'
import { png, server } from '../test/server'

const definitions = [
  variable('name', { label: 'Product name' }),
  variable('price', { type: 'number' }),
  variable('best_before', { type: 'date', required: false }),
]

function mockTemplate() {
  const previews: Record<string, string>[] = []
  server.use(
    http.get('/api/labels/7', () =>
      HttpResponse.json({ ...label({ variables: definitions }), zpl: '' }),
    ),
    http.get('/api/labels/7/variables', () => HttpResponse.json(definitions)),
    http.post('/api/templates/7/preview.png', async ({ request }) => {
      previews.push(((await request.json()) as { variables: Record<string, string> }).variables)
      return png()
    }),
  )
  return previews
}

describe('Print from template', () => {
  it('builds the form from the variables and refreshes the preview', async () => {
    const previews = mockTemplate()
    const printed: unknown[] = []
    server.use(
      http.post('/api/print', async ({ request }) => {
        printed.push(await request.json())
        return HttpResponse.json({ status: 'sent', printer_name: 'ZD420t' })
      }),
    )
    const { user } = renderRoute('/templates/7')

    const name = await screen.findByLabelText(/Product name/)
    const price = screen.getByLabelText(/price/)
    const date = screen.getByLabelText(/best_before/)
    expect(date).toHaveAttribute('type', 'date')
    expect(price).toHaveAttribute('inputmode', 'decimal')

    await user.type(name, 'Apples')
    await user.type(price, 'abc')
    expect(await screen.findByText('price must be a number')).toBeInTheDocument()
    await user.clear(price)
    await user.type(price, '2.50')
    await waitFor(() =>
      expect(previews.at(-1)).toEqual({ name: 'Apples', price: '2.50', best_before: '' }),
    )

    await user.click(screen.getByRole('button', { name: /Print on ZD420t/ }))
    await waitFor(() => expect(printed).toHaveLength(1))
    expect(printed[0]).toMatchObject({
      label_id: 7,
      variables: { name: 'Apples', price: '2.50', best_before: '' },
      copies: 1,
      source: 'template',
    })
  })

  it('mass prints the valid rows of pasted data', async () => {
    mockTemplate()
    const parsed: ParseResult = {
      format: 'csv',
      columns: ['Name', 'Price', 'copies'],
      rows: [
        { Name: 'Apple', Price: '1.5', copies: '2' },
        { Name: 'Pear', Price: 'abc', copies: '1' },
        { Name: 'Plum', Price: '3', copies: '1' },
      ],
      mapping: { name: 'Name', price: 'Price', best_before: null },
      copies_column: 'copies',
      preview: [],
      valid_count: 2,
      error_count: 1,
    }
    const uploads: FormData[] = []
    const batches: Record<string, unknown>[] = []
    server.use(
      http.post('/api/batches/parse', async ({ request }) => {
        uploads.push(await request.formData())
        return HttpResponse.json({
          ...parsed,
          preview: [
            { index: 0, values: {}, copies: 2, errors: [] },
            { index: 1, values: {}, copies: 1, errors: ['price must be a number'] },
            { index: 2, values: {}, copies: 1, errors: [] },
          ],
        })
      }),
      http.post('/api/batches', async ({ request }) => {
        batches.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json({ id: 99 }, { status: 201 })
      }),
      http.get('/api/batches/99', () =>
        HttpResponse.json({
          id: 99,
          status: 'done',
          total: 2,
          sent: 2,
          failed: 0,
          error: null,
        }),
      ),
    )
    const { user } = renderRoute('/templates/7')

    await user.click(await screen.findByRole('tab', { name: /Mass print/ }))
    await user.click(screen.getByText('Paste data'))
    await user.type(screen.getByLabelText('Data'), 'Name,Price')
    await user.click(screen.getByRole('button', { name: 'Load data' }))

    await waitFor(() => expect(uploads).toHaveLength(1))
    expect(uploads[0].get('label_id')).toBe('7')
    expect(uploads[0].get('text')).toBe('Name,Price')

    const badRow = await screen.findByTestId('row-1')
    expect(within(badRow).getByText('price must be a number')).toBeInTheDocument()
    expect(within(badRow).getByRole('checkbox')).toBeDisabled()
    expect(screen.getByTestId('batch-summary')).toHaveTextContent('2 labels selected (3 copies)')

    await user.click(within(screen.getByTestId('row-2')).getByRole('checkbox'))
    expect(screen.getByTestId('batch-summary')).toHaveTextContent('1 label selected (2 copies)')

    await user.click(screen.getByRole('button', { name: /Print 1 label on ZD420t/ }))
    await waitFor(() => expect(batches).toHaveLength(1))
    expect(batches[0]).toMatchObject({
      label_id: 7,
      printer_id: 1,
      selected: [0],
      copies_column: 'copies',
      mapping: { name: 'Name', price: 'Price', best_before: null },
    })
    expect(await screen.findByText('2 of 2 labels sent')).toBeInTheDocument()
  })
})
