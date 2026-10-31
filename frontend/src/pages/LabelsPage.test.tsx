import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { label, variable } from '../test/fixtures'
import { renderRoute } from '../test/render'
import { server } from '../test/server'

describe('Labels archive', () => {
  it('lists labels, filters them and deletes after confirmation', async () => {
    const queries: string[] = []
    const deleted: string[] = []
    server.use(
      http.get('/api/labels', ({ request }) => {
        queries.push(new URL(request.url).search)
        return HttpResponse.json({
          items: [
            label({ id: 1, name: 'Shipping', tags: ['post'] }),
            label({ id: 2, name: 'Price tag', kind: 'design', variables: [variable('price')] }),
          ],
          total: 2,
        })
      }),
      http.delete('/api/labels/:id', ({ params }) => {
        deleted.push(String(params.id))
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { user } = renderRoute('/labels')

    expect(await screen.findByText('Shipping')).toBeInTheDocument()
    expect(screen.getByText('1 variable')).toBeInTheDocument()
    expect(screen.getByAltText('Preview of Shipping')).toHaveAttribute(
      'src',
      expect.stringContaining('/api/labels/1/preview.png'),
    )

    await user.click(screen.getByRole('radio', { name: 'Designs' }))
    await waitFor(() => expect(queries.at(-1)).toContain('kind=design'))

    await user.click(screen.getByRole('button', { name: 'Actions for Shipping' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }))
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(deleted).toEqual(['1']))
  })
})
