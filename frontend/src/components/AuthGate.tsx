import { Center, Loader } from '@mantine/core'
import type { ReactNode } from 'react'

import { ApiError, loginUrl } from '../api/client'
import { useMe } from '../api/hooks'

/** Redirect to the Authentik login when the API says we are not authenticated. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { error, isLoading } = useMe()
  if (error instanceof ApiError && error.status === 401) {
    window.location.assign(loginUrl())
    return null
  }
  if (isLoading) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    )
  }
  return <>{children}</>
}
