/**
 * Vitest setup: jest-dom matchers, the browser APIs Mantine needs that jsdom lacks, and cleanup between tests.
 * Tests never reach the network: each one stubs fetch (see src/test/fakeApi.ts).
 */
import '@testing-library/jest-dom/vitest'

import { notifications } from '@mantine/notifications'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Mantine reads media queries and observes element sizes.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverStub
window.HTMLElement.prototype.scrollIntoView = () => {}

afterEach(() => {
  // Notifications live in one store for the whole file; Mantine shows 5 at a time and queues the rest, so one test's
  // notifications could hide the next test's.
  notifications.clean()
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.history.replaceState(null, '', '/')
})
