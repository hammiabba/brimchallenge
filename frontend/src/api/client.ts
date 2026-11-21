/**
 * The typed API client. Every call goes through `api` (openapi-fetch over the generated `paths`) and usually
 * through `unwrap`, which returns the data or throws an ApiError:
 *
 *   const me = await unwrap(api.GET('/auth/me'))
 *   const bill = await unwrap(api.GET('/bills/{bill_id}', { params: { path: { bill_id } } }))
 *
 * Requests go to /api, which the Vite dev server proxies to the backend with the prefix stripped (vite.config.ts),
 * so the session cookie is same-origin. The cookie is httpOnly: JavaScript never reads it; the browser sends it.
 *
 * A 401 from any call except the sign-in itself calls the handler registered with setUnauthorizedHandler (the
 * AuthProvider: it clears the cached user, and the route guard then shows the login page). 403, 404, 409, 422 and
 * 501 are thrown as ApiError for the screen to handle; notifyError shows one as a notification.
 */
import createClient, { type Middleware } from 'openapi-fetch'

import { ApiError } from './errors'
import type { paths } from './schema'

/** Where the API lives, relative to the page. Must match the proxy key in vite.config.ts. */
export const API_PREFIX = '/api'

/**
 * The base URL: API_PREFIX resolved against the page's origin ("http://localhost:5173/api" in the dev server).
 * In the browser that is the same as "/api"; it is spelled out because tests run in Node, whose Request needs an
 * absolute URL.
 */
function baseUrl(): string {
  return new URL(API_PREFIX, window.location.origin).toString()
}

type UnauthorizedHandler = (error: ApiError) => void
let unauthorizedHandler: UnauthorizedHandler | null = null

/** Registers the function called on a 401; returns a function that unregisters it (for a React effect cleanup). */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): () => void {
  unauthorizedHandler = handler
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null
  }
}

/** True for the sign-in request, whose 401 ("This account can't sign in.") is shown on the login form instead. */
function isLoginRequest(request: Request): boolean {
  return new URL(request.url).pathname === `${API_PREFIX}/auth/login`
}

/** Middleware: on a 401, read the envelope from a copy of the response and tell the unauthorized handler. */
const unauthorizedMiddleware: Middleware = {
  async onResponse({ request, response }) {
    if (response.status !== 401 || isLoginRequest(request) || unauthorizedHandler === null) return undefined
    const body: unknown = await response.clone().json().catch(() => null)
    unauthorizedHandler(ApiError.fromResponse(response, body))
    return undefined
  },
}

/** The client. `fetch` is looked up on each call (not captured at import), so tests can stub it. */
export const api = createClient<paths>({
  baseUrl: baseUrl(),
  credentials: 'include',
  fetch: (request) => globalThis.fetch(request),
})
api.use(unauthorizedMiddleware)

/** The shape every openapi-fetch call resolves to (success and error variants). */
interface FetchResult<T> {
  data?: T
  error?: unknown
  response: Response
}

/**
 * Awaits an openapi-fetch call and returns its data, or throws an ApiError: built from the error envelope for a
 * failed response, or ApiError.network when no response came back. An aborted request (a query cancelled by
 * TanStack Query) is rethrown untouched. A 204 resolves to undefined.
 */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>
  try {
    result = await call
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw ApiError.network(cause)
  }
  if (!result.response.ok) {
    throw ApiError.fromResponse(result.response, result.error)
  }
  return result.data as T
}
