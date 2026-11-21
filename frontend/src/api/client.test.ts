import { describe, expect, it, vi } from 'vitest'

import { envelope, installFakeApi, makeMe } from '../test/fakeApi'
import { api, setUnauthorizedHandler, unwrap } from './client'
import { ApiError, isErrorEnvelope } from './errors'

describe('ApiError.fromResponse', () => {
  it('reads every field of the envelope', () => {
    const body = envelope('auth.forbidden_role', "Your role (employee) can't do this.", 'abc123def', { x: 1 })
    const error = ApiError.fromResponse(new Response(null, { status: 403 }), body)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 403,
      code: 'auth.forbidden_role',
      message: "Your role (employee) can't do this.",
      details: { x: 1 },
      request_id: 'abc123def',
    })
  })

  it('reads an HTTPException envelope, which also carries a top-level detail', () => {
    const body = { ...envelope('http.404', 'Not Found', 'rid-0000001'), detail: 'Not Found' }
    expect(ApiError.fromResponse(new Response(null, { status: 404 }), body)).toMatchObject({
      status: 404,
      code: 'http.404',
      message: 'Not Found',
      request_id: 'rid-0000001',
    })
  })

  it('parses an envelope that arrives as text', () => {
    const text = JSON.stringify(envelope('conflict.stale', 'Someone else changed this record.'))
    expect(ApiError.fromResponse(new Response(null, { status: 409 }), text).code).toBe('conflict.stale')
  })

  it('falls back for a body that is not the envelope, keeping the request id header', () => {
    const response = new Response(null, { status: 502, headers: { 'x-request-id': 'hdr-12345678' } })
    const error = ApiError.fromResponse(response, '<html>Bad gateway</html>')
    expect(error).toMatchObject({ status: 502, code: 'http.502', details: null, request_id: 'hdr-12345678' })
    expect(error.message).toContain('port 8000')
  })

  it('recognises the envelope shape', () => {
    expect(isErrorEnvelope(envelope('a.b', 'c'))).toBe(true)
    expect(isErrorEnvelope({ error: 'nope' })).toBe(false)
    expect(isErrorEnvelope({ detail: 'Not Found' })).toBe(false)
    expect(isErrorEnvelope(null)).toBe(false)
  })
})

describe('unwrap', () => {
  it('returns the data of a successful call', async () => {
    installFakeApi({ 'GET /auth/me': { body: makeMe() } })
    await expect(unwrap(api.GET('/auth/me'))).resolves.toMatchObject({ user_id: 'U005', role: 'ap_clerk' })
  })

  it('sends requests to /api with the cookie', async () => {
    let seen: Request | undefined
    installFakeApi({
      'GET /auth/me': (request) => {
        seen = request
        return { body: makeMe() }
      },
    })
    await unwrap(api.GET('/auth/me'))
    expect(new URL(seen!.url).pathname).toBe('/api/auth/me')
    expect(seen!.credentials).toBe('include')
  })

  it('throws an ApiError built from the envelope', async () => {
    installFakeApi({
      'GET /bills/AP-99999': { status: 404, body: envelope('bill.not_found', 'No bill AP-99999.', 'rid-abcdefgh') },
    })
    const call = unwrap(api.GET('/bills/{bill_id}', { params: { path: { bill_id: 'AP-99999' } } }))
    await expect(call).rejects.toMatchObject({ status: 404, code: 'bill.not_found', request_id: 'rid-abcdefgh' })
  })

  it('surfaces 403, 409 and 501 as ApiError for the screen', async () => {
    installFakeApi({
      'GET /audit': { status: 403, body: envelope('auth.forbidden_role', "Your role (employee) can't do this.") },
      'POST /bills/AP-00001/submit': { status: 409, body: envelope('conflict.stale', 'Someone else changed it.') },
      'GET /payments/summary': { status: 501, body: envelope('not_implemented', 'Payments is not implemented yet.') },
    })
    await expect(unwrap(api.GET('/audit'))).rejects.toMatchObject({ status: 403 })
    await expect(unwrap(api.POST('/bills/{bill_id}/submit', {
      params: { path: { bill_id: 'AP-00001' } }, body: { row_version: 1 },
    }))).rejects.toMatchObject({ status: 409, code: 'conflict.stale' })
    await expect(unwrap(api.GET('/payments/summary'))).rejects.toMatchObject({ status: 501 })
  })

  it('resolves a 204 to undefined', async () => {
    installFakeApi({ 'POST /auth/logout': { status: 204 } })
    await expect(unwrap(api.POST('/auth/logout'))).resolves.toBeUndefined()
  })

  it('turns a failed fetch into a network ApiError', async () => {
    vi.stubGlobal('fetch', async () => {
      throw new TypeError('Failed to fetch')
    })
    await expect(unwrap(api.GET('/auth/me'))).rejects.toMatchObject({ status: 0, code: 'network.unreachable' })
  })
})

describe('401 handling', () => {
  it('calls the unauthorized handler for a 401 from any call', async () => {
    installFakeApi({ 'GET /bills': { status: 401, body: envelope('auth.required', 'Sign in to continue.') } })
    const handler = vi.fn()
    const unregister = setUnauthorizedHandler(handler)
    await expect(unwrap(api.GET('/bills'))).rejects.toMatchObject({ status: 401 })
    unregister()
    expect(handler).toHaveBeenCalledTimes(1)
    expect(handler.mock.calls[0]?.[0]).toMatchObject({ code: 'auth.required' })
  })

  it('leaves a failed sign-in to the login form', async () => {
    installFakeApi({ 'POST /auth/login': { status: 401, body: envelope('auth.invalid_user', "This account can't sign in.") } })
    const handler = vi.fn()
    const unregister = setUnauthorizedHandler(handler)
    await expect(unwrap(api.POST('/auth/login', { body: { user_id: 'U999' } }))).rejects.toMatchObject({ status: 401 })
    unregister()
    expect(handler).not.toHaveBeenCalled()
  })
})
