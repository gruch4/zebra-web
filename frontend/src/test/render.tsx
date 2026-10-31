import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router'

import { Providers } from '../Providers'
import { createQueryClient } from '../queryClient'
import { routes } from '../router'

/** Render the whole app at the given URL. */
export function renderRoute(path: string) {
  const client = createQueryClient()
  client.setDefaultOptions({ queries: { retry: false, refetchOnWindowFocus: false } })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const user = userEvent.setup()
  const result = render(
    <Providers client={client}>
      <RouterProvider router={router} />
    </Providers>,
  )
  return { ...result, user, router }
}
