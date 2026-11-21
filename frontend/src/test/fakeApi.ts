/**
 * A fake backend for component tests: stubs global fetch and answers by "METHOD /path" (without the /api prefix).
 * Anything not listed gets a 404 in the API's error envelope. No network is ever used.
 */
import { vi } from 'vitest'

import type { Me, PickerUser } from '../api/types'

export interface FakeReply {
  status?: number
  body?: unknown
  headers?: Record<string, string>
}
export type FakeRoute = FakeReply | ((request: Request) => FakeReply | Promise<FakeReply>)

/** The API's error body, as backend/app/api/errors.py builds it. */
export function envelope(code: string, message: string, requestId = 'req-test-0001', details: unknown = null) {
  return { error: { code, message, details }, request_id: requestId }
}

/** A Response with a JSON body (or no body for 204). */
function toResponse(reply: FakeReply): Response {
  const status = reply.status ?? 200
  if (status === 204) return new Response(null, { status })
  return new Response(JSON.stringify(reply.body ?? null), {
    status,
    headers: { 'content-type': 'application/json', ...reply.headers },
  })
}

/**
 * Installs the fake. `routes` can be changed after installing (the object is read on every call). Returns the
 * routes object and the list of "METHOD /path" keys called, in order.
 */
export function installFakeApi(routes: Record<string, FakeRoute>) {
  const calls: string[] = []
  vi.stubGlobal('fetch', async (input: Request | string | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init)
    const url = new URL(request.url)
    const key = `${request.method} ${url.pathname.replace(/^\/api/, '')}`
    calls.push(key)
    const route = routes[key]
    if (route === undefined) return toResponse({ status: 404, body: envelope('http.404', 'Not Found') })
    return toResponse(typeof route === 'function' ? await route(request) : route)
  })
  return { routes, calls }
}

/** A /auth/me answer for a given role, with sensible defaults. */
export function makeMe(overrides: Partial<Me> = {}): Me {
  return {
    user_id: 'U005',
    full_name: 'Jordan Okafor',
    title: 'AP Specialist',
    role: 'ap_clerk',
    department_id: 'D02',
    status: 'active',
    approval_limit_cad: null,
    release_limit_cad: '0.00',
    acting_for: [],
    ...overrides,
  }
}

/** The people in the sign-in picker for tests: one or two per role, one of them on leave. */
export const PICKER_USERS: PickerUser[] = [
  { user_id: 'U013', full_name: 'Avery Chen', title: 'Operations Analyst', role: 'employee', department_id: 'D01', status: 'active' },
  { user_id: 'U005', full_name: 'Jordan Okafor', title: 'AP Specialist', role: 'ap_clerk', department_id: 'D02', status: 'active' },
  { user_id: 'U012', full_name: 'Sam Rivera', title: 'Facilities Manager', role: 'approver', department_id: 'D04', status: 'on_leave' },
  { user_id: 'U001', full_name: 'Morgan Lee', title: 'Operations Director', role: 'approver', department_id: 'D01', status: 'active' },
  { user_id: 'U003', full_name: 'Priya Natarajan', title: 'Finance Manager', role: 'finance_manager', department_id: 'D02', status: 'active' },
  { user_id: 'U002', full_name: 'Elena Duarte', title: 'Controller', role: 'controller_admin', department_id: 'D02', status: 'active' },
  { user_id: 'U015', full_name: 'Kai Thompson', title: 'Audit Lead', role: 'auditor', department_id: 'D02', status: 'active' },
]

export const DEPARTMENTS = [
  { department_id: 'D01', name: 'Operations', cost_centre: 'CC-100', manager_user_id: 'U001' },
  { department_id: 'D02', name: 'Finance', cost_centre: 'CC-200', manager_user_id: 'U002' },
]
