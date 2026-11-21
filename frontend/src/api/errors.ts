/**
 * The API's one error format, as a JavaScript error.
 *
 * Every error response from the backend has the shape built by `envelope()` in backend/app/api/errors.py (and by
 * `_send_error()` in backend/app/api/middleware.py for the origin check and body-size limit):
 *
 *   { "error": { "code": "auth.forbidden_role", "message": "Your role (employee) can't do this.", "details": null },
 *     "request_id": "3f2c..." }
 *
 * `code` is a stable dotted id ("bill.not_found", "conflict.stale", "request.invalid", "not_implemented"),
 * `message` is safe to show the user, `details` is free-form (validation errors are a list of {loc, msg, type}),
 * and `request_id` is also sent as the X-Request-ID header. Errors raised as FastAPI HTTPException additionally carry
 * a top-level "detail"; the envelope fields are what the UI reads.
 */
import type { ErrorEnvelope } from './types'

/** An HTTP error from the API, or a failure to reach it (status 0). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown
  readonly request_id: string | null

  /** Builds an ApiError; `message` is the user-facing text from the envelope. */
  constructor(status: number, code: string, message: string, details: unknown = null, request_id: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.request_id = request_id
  }

  /**
   * The ApiError for a failed response. `body` is whatever the client read from it: the parsed envelope, a string
   * (a body that wasn't JSON, e.g. the dev proxy's error page when the backend is down) or nothing.
   */
  static fromResponse(response: Response, body: unknown): ApiError {
    const parsed = typeof body === 'string' ? tryParseJson(body) : body
    const headerId = response.headers.get('x-request-id')
    if (isErrorEnvelope(parsed)) {
      const { code, message, details } = parsed.error
      return new ApiError(response.status, code, message, details ?? null, parsed.request_id ?? headerId)
    }
    return new ApiError(response.status, `http.${response.status}`, fallbackMessage(response.status), null, headerId)
  }

  /** The ApiError for a request that never got a response (server down, network off, CORS). */
  static network(cause: unknown): ApiError {
    const error = new ApiError(0, 'network.unreachable',
      "Can't reach the server. Check that the backend is running on port 8000.")
    error.cause = cause
    return error
  }
}

/** True when `value` is an ApiError. */
export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}

/** True when `body` has the envelope shape: an `error` object with string `code` and `message`. */
export function isErrorEnvelope(body: unknown): body is ErrorEnvelope {
  if (typeof body !== 'object' || body === null || !('error' in body)) return false
  const error = (body as { error: unknown }).error
  return typeof error === 'object' && error !== null &&
    typeof (error as { code?: unknown }).code === 'string' &&
    typeof (error as { message?: unknown }).message === 'string'
}

/** JSON.parse that returns the original string when it isn't JSON. */
function tryParseJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

/** A message for a failed response that didn't carry the envelope (normally only proxy or gateway errors). */
function fallbackMessage(status: number): string {
  if (status === 502 || status === 503 || status === 504) {
    return "The server isn't responding. Check that the backend is running on port 8000."
  }
  return `The server returned an unexpected response (HTTP ${status}).`
}
