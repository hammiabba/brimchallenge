/**
 * Real API responses, recorded from the backend on a fresh seed + backfill + scripts/demo_scenario.py database (the
 * same bill and user ids as docs/DEMO_SCENARIO.md), so frontend tests use exactly what the server sends rather than
 * hand-written fields. Re-record after an API change to these responses:
 *
 * - delegatedStep: GET /bills/AP-00433 as U003, signing step 1 as U012's delegate (P08).
 * - lastStep: GET /bills/AP-00434 as U003, step 2 of 2 (finance manager).
 * - readyToSubmit: GET /bills/AP-00435 as U004 after U003 overrode its blocking flag.
 * - submitted: POST /bills/AP-00435/submit as U004.
 */
import type { BillDetail } from '../../api/types'
import recorded from './bills.json'

const bills = recorded as unknown as Record<'delegated_step' | 'last_step' | 'ready_to_submit' | 'submitted', BillDetail>

export const RECORDED = {
  delegatedStep: bills.delegated_step,
  lastStep: bills.last_step,
  readyToSubmit: bills.ready_to_submit,
  submitted: bills.submitted,
}
