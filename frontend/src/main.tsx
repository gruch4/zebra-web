import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'
import '@mantine/dropzone/styles.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'

import { AuthGate } from './components/AuthGate'
import { Providers } from './Providers'
import { router } from './router'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Providers>
      <AuthGate>
        <RouterProvider router={router} />
      </AuthGate>
    </Providers>
  </StrictMode>,
)
