import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { ApiToken } from '../api/types'
import { renderRoute } from '../test/render'
import { server } from '../test/server'

function token(id: number, extra: Partial<ApiToken> = {}): ApiToken {
  return {
    id,
    name: `Token ${id}`,
    prefix: `zw_abcde${id}`,
    owner: 'Local user',
    shared: false,
    status: 'active',
    created_at: '2026-01-01T10:00:00Z',
    expires_at: null,
    last_used_at: null,
    revoked_at: null,
    ...extra,
  }
}

describe('API access', () => {
  it('lists tokens with their status and revokes one after confirmation', async () => {
    const revoked: string[] = []
    server.use(
      http.get('/api/tokens', () =>
        HttpResponse.json([
          token(1, { name: 'Home inventory', last_used_at: '2026-01-02T10:00:00Z' }),
          token(2, { name: 'Old script', status: 'revoked', revoked_at: '2026-01-03T10:00:00Z' }),
          token(3, { name: 'Legacy', shared: true, status: 'expired' }),
        ]),
      ),
      http.delete('/api/tokens/:id', ({ params }) => {
        revoked.push(String(params.id))
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { user } = renderRoute('/integrations')

    expect(await screen.findByText('Home inventory')).toBeInTheDocument()
    expect(screen.getByText('zw_abcde1…')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
    expect(screen.getByText('revoked')).toBeInTheDocument()
    expect(screen.getByText('expired')).toBeInTheDocument()
    expect(screen.getByText('Shared')).toBeInTheDocument()
    expect(screen.getByText('Tokens from before login was enabled')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'API documentation' })).toHaveAttribute(
      'href',
      '/api/v1/docs',
    )
    // A revoked token has nothing left to revoke.
    expect(screen.queryByRole('button', { name: 'Revoke Old script' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Revoke Home inventory' }))
    await user.click(await screen.findByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(revoked).toEqual(['1']))
  })

  it('only warns about shared tokens when there are some', async () => {
    server.use(http.get('/api/tokens', () => HttpResponse.json([token(1)])))
    renderRoute('/integrations')
    expect(await screen.findByText('Token 1')).toBeInTheDocument()
    expect(screen.queryByText('Tokens from before login was enabled')).not.toBeInTheDocument()
  })

  it('creates a token and shows the secret once', async () => {
    const bodies: { name: string; expires_at: string | null }[] = []
    server.use(
      http.get('/api/tokens', () => HttpResponse.json([])),
      http.post('/api/tokens', async ({ request }) => {
        const body = (await request.json()) as { name: string; expires_at: string | null }
        bodies.push(body)
        return HttpResponse.json(
          { ...token(7, { name: body.name }), token: 'zw_the-secret-value' },
          { status: 201 },
        )
      }),
    )
    const { user } = renderRoute('/integrations')

    expect(await screen.findByText('No API tokens yet.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Create token' }))
    const form = await screen.findByRole('dialog', { name: 'Create API token' })
    const create = within(form).getByRole('button', { name: 'Create token' })
    expect(create).toBeDisabled() // a name is required

    await user.type(within(form).getByLabelText(/Name/), 'Home inventory')
    await user.type(within(form).getByLabelText('Expires'), '2099-06-30')
    await user.click(create)

    const secret = await screen.findByRole('dialog', { name: 'Your new API token' })
    expect(within(secret).getByText('zw_the-secret-value')).toBeInTheDocument()
    expect(within(secret).getByText(/shown only once/)).toBeInTheDocument()
    expect(
      within(secret).getByText(/Authorization: Bearer zw_the-secret-value/),
    ).toBeInTheDocument()

    // The expiry is the end of the chosen day, sent with a time zone.
    expect(bodies).toHaveLength(1)
    expect(bodies[0].name).toBe('Home inventory')
    expect(bodies[0].expires_at).toMatch(/Z$/)
    expect(new Date(bodies[0].expires_at!).getTime()).toBe(
      new Date('2099-06-30T23:59:59').getTime(),
    )

    await user.click(within(secret).getByRole('button', { name: 'Done' }))
    await waitFor(() => expect(screen.queryByText('zw_the-secret-value')).not.toBeInTheDocument())
  })

  it('offers manual copying when the browser blocks the clipboard', async () => {
    // Plain http://<lan-ip> is not a secure context, so navigator.clipboard is unavailable.
    const original = Object.getOwnPropertyDescriptor(window, 'isSecureContext')
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    try {
      server.use(
        http.get('/api/tokens', () => HttpResponse.json([])),
        http.post('/api/tokens', () =>
          HttpResponse.json({ ...token(8), token: 'zw_manual-copy' }, { status: 201 }),
        ),
      )
      const { user } = renderRoute('/integrations')
      await user.click(await screen.findByRole('button', { name: 'Create token' }))
      const form = await screen.findByRole('dialog', { name: 'Create API token' })
      await user.type(within(form).getByLabelText(/Name/), 'Script')
      await user.click(within(form).getByRole('button', { name: 'Create token' }))

      const secret = await screen.findByRole('dialog', { name: 'Your new API token' })
      expect(within(secret).getByText('zw_manual-copy')).toBeInTheDocument()
      expect(within(secret).queryByRole('button', { name: 'Copy' })).not.toBeInTheDocument()
      expect(within(secret).getByText(/copy it manually/)).toBeInTheDocument()
    } finally {
      if (original) Object.defineProperty(window, 'isSecureContext', original)
      else Reflect.deleteProperty(window, 'isSecureContext')
    }
  })

  it('is reachable from the navigation', async () => {
    server.use(http.get('/api/tokens', () => HttpResponse.json([])))
    const { user } = renderRoute('/')
    await user.click(await screen.findByRole('link', { name: 'API access' }))
    expect(await screen.findByRole('heading', { name: 'API access' })).toBeInTheDocument()
  })
})
