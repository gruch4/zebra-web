import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'

import { server } from './server'

const { getComputedStyle } = window
window.getComputedStyle = (element) => getComputedStyle(element)
window.HTMLElement.prototype.scrollIntoView = () => {}

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserver

// Mantine's autosize textarea listens for font loading.
Object.defineProperty(document, 'fonts', {
  value: { addEventListener: () => {}, removeEventListener: () => {}, ready: Promise.resolve() },
})

// Leaving a page saves its pending draft (useAutosaveDraft), so `cleanup()` can start requests.
// Let them finish before the handlers are reset, or the next test's handlers answer them.
const inFlight = new Set<string>()
server.events.on('request:start', ({ requestId }) => inFlight.add(requestId))
server.events.on('request:end', ({ requestId }) => inFlight.delete(requestId))

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(async () => {
  cleanup()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vi.waitFor(() => {
    if (inFlight.size > 0) throw new Error(`${inFlight.size} request(s) still in flight`)
  })
  server.resetHandlers()
  localStorage.clear()
})
afterAll(() => server.close())
