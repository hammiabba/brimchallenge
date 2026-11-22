import { describe, expect, it } from 'vitest'

import { ROLES } from '../auth/roles'
import { ALL_NAV_ITEMS, NAV_BY_ROLE, NAV_ITEMS, homePathFor, navItemsFor } from './navigation'

describe('navigation config', () => {
  it('has a non-empty sidebar for each of the six roles', () => {
    expect(Object.keys(NAV_BY_ROLE).sort()).toEqual([...ROLES].sort())
    for (const role of ROLES) {
      expect(navItemsFor(role).length, role).toBeGreaterThan(0)
    }
  })

  it('uses every screen at least once, each at most once per role', () => {
    const used = new Set(Object.values(NAV_BY_ROLE).flat())
    expect([...used].sort()).toEqual(Object.keys(NAV_ITEMS).sort())
    for (const role of ROLES) {
      expect(new Set(NAV_BY_ROLE[role]).size, role).toBe(NAV_BY_ROLE[role].length)
    }
  })

  it('keys each item by its own key', () => {
    for (const [key, item] of Object.entries(NAV_ITEMS)) {
      expect(item.key).toBe(key)
    }
  })

  it('has unique paths, none a prefix of another, so one item is highlighted at a time', () => {
    const paths = ALL_NAV_ITEMS.map((item) => item.path)
    expect(new Set(paths).size).toBe(paths.length)
    for (const a of paths) {
      for (const b of paths) {
        if (a !== b) expect(b.startsWith(`${a}/`), `${a} vs ${b}`).toBe(false)
      }
    }
  })

  it('describes every screen and the API behind it', () => {
    for (const item of ALL_NAV_ITEMS) {
      expect(item.description.length, item.key).toBeGreaterThan(20)
      expect(item.endpoints.length, item.key).toBeGreaterThan(0)
    }
  })

  it('sends each role home to the task they come to do', () => {
    expect(homePathFor('employee')).toBe('/submit')
    expect(homePathFor('ap_clerk')).toBe('/inbox')
    // AP can upload an invoice by hand, as the API allows (POST /submissions: employee and AP clerk).
    expect(NAV_BY_ROLE.ap_clerk).toContain('submit')
    expect(homePathFor('approver')).toBe('/approvals')
    expect(homePathFor('finance_manager')).toBe('/approvals')
    expect(homePathFor('controller_admin')).toBe('/approvals')
    expect(homePathFor('auditor')).toBe('/audit')
  })

  it('gives employees only the pages they can act on: submit and their own submissions', () => {
    expect(NAV_BY_ROLE.employee).toEqual(['submit', 'submissions'])
  })

  it("keeps work queues out of the auditor's read-only sidebar", () => {
    const auditor = new Set(NAV_BY_ROLE.auditor)
    for (const key of ['submit', 'inbox', 'review', 'approvals', 'unassigned', 'delegation'] as const) {
      expect(auditor.has(key), key).toBe(false)
    }
  })
})
