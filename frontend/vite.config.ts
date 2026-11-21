/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The FastAPI backend, started from backend/ with `uvicorn app.main:app --port 8000`.
const API_TARGET = 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Open the app at http://localhost:5173, not http://127.0.0.1:5173. The two are different sites to the browser:
    // the session cookie set through localhost is not sent to 127.0.0.1, and the backend's origin check (CSRF) only
    // accepts the origins in FRONTEND_ORIGINS, which defaults to http://localhost:5173.
    port: 5173,
    strictPort: true,
    proxy: {
      // /api/auth/me -> http://127.0.0.1:8000/auth/me. The prefix keeps API paths (/bills, /payments) from
      // clashing with UI routes of the same name, and makes every API call same-origin, so the cookie just works.
      // The browser's Origin header (http://localhost:5173) is forwarded unchanged for the origin check.
      '/api': {
        target: API_TARGET,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // A time zone west of UTC, so a date-only string parsed as UTC midnight would show the previous day and fail.
    env: { TZ: 'America/Toronto' },
    // Process only the CSS under src/styles/, so src/design.test.ts can read its text (?raw). Everything else stays
    // unprocessed; components don't import CSS (main.tsx does).
    css: { include: [/\/src\/styles\//] },
  },
})
