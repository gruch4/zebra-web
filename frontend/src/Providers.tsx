import { MantineProvider } from '@mantine/core'
import { ModalsProvider } from '@mantine/modals'
import { Notifications } from '@mantine/notifications'
import { type QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode, useState } from 'react'

import { PrinterProvider } from './components/PrinterProvider'
import { createQueryClient } from './queryClient'
import { theme } from './theme'

export function Providers({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? createQueryClient())
  return (
    <QueryClientProvider client={queryClient}>
      <MantineProvider theme={theme} defaultColorScheme="auto">
        <ModalsProvider>
          <Notifications position="top-right" />
          <PrinterProvider>{children}</PrinterProvider>
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>
  )
}
