/**
 * The sidebar: every screen, and which of them each role sees, in the order of the work they come to do.
 *
 * This decides only what the navigation shows. It is not a permission check: every route exists for every
 * signed-in user, and the server enforces roles, department scope and the approval/payment rules on each request
 * (backend/app/auth/deps.py, require_role; the full matrix is backend/tests/api/matrix.py). A screen opened by
 * someone whose role can't use it shows the server's 403.
 *
 * Screens and endpoints come from the frontend discovery plan (screen inventory per role). Each one is a placeholder
 * page until its chunk is built: the page shows `placeholder` (one line); `description` and `endpoints` are the plan
 * for whoever builds it.
 */
import {
  IconBuildingBank,
  IconBuildingStore,
  IconCalendarUser,
  IconCash,
  IconChartBar,
  IconChecks,
  IconClipboardCheck,
  IconFileInvoice,
  IconFiles,
  IconHistory,
  IconInbox,
  IconShieldCheck,
  IconUpload,
  IconUserQuestion,
  IconUserShare,
  IconUsers,
  type TablerIcon,
} from '@tabler/icons-react'

import type { Role } from '../api/types'

export type NavKey =
  | 'submit'
  | 'submissions'
  | 'inbox'
  | 'review'
  | 'approvals'
  | 'unassigned'
  | 'bills'
  | 'payments'
  | 'vendors'
  | 'bankChanges'
  | 'spend'
  | 'audit'
  | 'users'
  | 'policies'
  | 'absences'
  | 'delegation'

export interface NavItem {
  key: NavKey
  /** The route. Unique, and no path is a prefix of another (so only one item is highlighted). */
  path: string
  label: string
  /** The sidebar icon (Tabler, drawn through <Icon>). */
  icon: TablerIcon
  /** The placeholder page's one line: what is missing and what comes next. */
  placeholder: string
  /** What the screen will do, in full: the plan for whoever builds it (not shown in the UI). */
  description: string
  /** The API operations behind it (for whoever builds it; not shown in the UI). */
  endpoints: readonly string[]
}

export const NAV_ITEMS: Record<NavKey, NavItem> = {
  submit: {
    key: 'submit',
    path: '/submit',
    label: 'Submit invoice',
    icon: IconUpload,
    placeholder: 'Invoice upload is not built yet. It will send a PDF or image to AP for review.',
    description:
      'Upload an invoice PDF or image for your department. It is read, coded and checked automatically, then waits ' +
      'in the AP review queue.',
    endpoints: ['POST /submissions'],
  },
  submissions: {
    key: 'submissions',
    path: '/submissions',
    label: 'My submissions',
    icon: IconFiles,
    placeholder: 'Your submissions list is not built yet. It will show each file\'s status and the bill it became.',
    description:
      'Every file you submitted with its status (queued, processing, done or failed) and a link to the bill it ' +
      'became.',
    endpoints: ['GET /submissions'],
  },
  inbox: {
    key: 'inbox',
    path: '/inbox',
    label: 'Inbox',
    icon: IconInbox,
    placeholder: 'The AP inbox is not built yet. It will run the mailbox and show what happened to each email.',
    description:
      'Run the AP inbox and follow the job as it works. Every email is listed with its class (invoice, statement, ' +
      'marketing, missing attachment) and the reason, so nothing is dropped silently; failed items can be retried.',
    endpoints: ['POST /intake/inbox/jobs', 'GET /intake/inbox/jobs/{job_id}', 'GET /intake/emails', 'GET /intake/items'],
  },
  review: {
    key: 'review',
    path: '/review',
    label: 'Review queue',
    icon: IconClipboardCheck,
    placeholder: 'The review queue is not built yet. It will list the bills waiting for AP, oldest first.',
    description:
      'Bills waiting for AP (needs review and on hold), oldest first, with block and warn counts and the top flag. ' +
      'Opening one shows the extracted values next to any corrections, the line coding with its reasons and the ' +
      'flags with what to do about each; from there AP edits, resolves flags, submits for approval or voids.',
    endpoints: [
      'GET /bills?status=needs_review&status=on_hold',
      'GET /bills/{bill_id}',
      'PATCH /bills/{bill_id}',
      'PATCH /bills/{bill_id}/lines/{line_no}',
      'POST /bills/{bill_id}/flags/{flag_id}/resolve',
      'POST /bills/{bill_id}/submit',
      'POST /bills/{bill_id}/void',
    ],
  },
  approvals: {
    key: 'approvals',
    path: '/approvals',
    label: 'My approvals',
    icon: IconChecks,
    placeholder: 'Your approval queue is not built yet. It will list the bills waiting for your decision.',
    description:
      'Bills whose current approval step is yours, including steps you sign as someone\'s delegate: the amount ' +
      'against your limit, why the bill was routed to you and its open flags. Approve, or reject with a comment.',
    endpoints: ['GET /approvals/queue', 'GET /bills/{bill_id}', 'POST /bills/{bill_id}/approve',
      'POST /bills/{bill_id}/reject'],
  },
  unassigned: {
    key: 'unassigned',
    path: '/unassigned-steps',
    label: 'Unassigned steps',
    icon: IconUserQuestion,
    placeholder: 'Unassigned steps are not built yet. They will list approval steps that need someone to sign.',
    description:
      'Approval steps that found nobody eligible to sign (for example, when the only approver is the requester or ' +
      'away). Assign someone who may sign.',
    endpoints: ['GET /bills (no unassigned-step filter yet)', 'POST /bills/{bill_id}/route/{step_no}/assign'],
  },
  bills: {
    key: 'bills',
    path: '/bills',
    label: 'Bills',
    icon: IconFileInvoice,
    placeholder: 'The bill list is not built yet. It will list the bills you may see and open each one in full.',
    description:
      'Every bill you may see (your department for employees and approvers; all bills for AP, finance, the ' +
      'controller and auditors), filtered by status, vendor or department. Each opens the one-screen bill detail: ' +
      'invoice, coding, flags, approval route and decisions, payments and the audit trail.',
    endpoints: ['GET /bills', 'GET /bills/{bill_id}', 'GET /reference/flag-help'],
  },
  payments: {
    key: 'payments',
    path: '/payments',
    label: 'Payments',
    icon: IconCash,
    placeholder: 'Payment scheduling and release are not built yet. They will list payments by date.',
    description:
      'The payments dashboard (totals by status, due in the next 7 days, overdue) and payments by date. AP ' +
      'schedules approved bills and cancels payments; finance and the controller release them, and a payment that ' +
      'can\'t be released shows the server\'s reason (for example, you approved the bill yourself).',
    endpoints: [
      'GET /payments/summary',
      'GET /payments',
      'GET /payments/{payment_id}',
      'POST /bills/{bill_id}/payments',
      'POST /payments/{payment_id}/release',
      'POST /payments/{payment_id}/cancel',
    ],
  },
  vendors: {
    key: 'vendors',
    path: '/vendors',
    label: 'Vendors',
    icon: IconBuildingStore,
    placeholder: 'The vendor list is not built yet. It will show vendor details, onboarding and holds.',
    description:
      'The vendor master: status, payment terms, tax numbers and the bank account (last 4 digits unless your role ' +
      'may see more). AP onboards vendors and puts them on hold; finance and the controller approve new vendors.',
    endpoints: ['GET /vendors', 'GET /vendors/{vendor_id}', 'POST /vendors', 'POST /vendors/{vendor_id}/approve',
      'POST /vendors/{vendor_id}/hold'],
  },
  bankChanges: {
    key: 'bankChanges',
    path: '/bank-changes',
    label: 'Bank changes',
    icon: IconBuildingBank,
    placeholder: 'Bank change requests are not built yet. They will list requests to verify or reject.',
    description:
      'Requests to change a vendor\'s bank details: old and new account (last 4), the channel the request came in ' +
      'by, who asked and when. AP requests a change from the vendor page; finance or the controller verifies it ' +
      'after calling the vendor on a number already on file, or rejects it. Nobody can verify their own request.',
    endpoints: ['GET /bank-changes', 'POST /vendors/{vendor_id}/bank-changes', 'POST /bank-changes/{change_id}/verify',
      'POST /bank-changes/{change_id}/reject'],
  },
  spend: {
    key: 'spend',
    path: '/spend',
    label: 'Spend',
    icon: IconChartBar,
    placeholder: 'The spend report is not built yet. It will total spend by vendor, GL account or department.',
    description: 'Spend by vendor, GL account or department over a date range; approvers see their own department.',
    endpoints: ['GET /spend'],
  },
  audit: {
    key: 'audit',
    path: '/audit',
    label: 'Audit log',
    icon: IconHistory,
    placeholder: 'The audit log is not built yet. It will list every recorded action, with filters and CSV export.',
    description:
      'The full audit trail: filter by entity, person, action and dates, page through it, expand an event to see ' +
      'what changed, and export the current filter as CSV. Each bill, vendor and payment also has its own history.',
    endpoints: ['GET /audit', 'GET /audit/{entity_type}/{entity_id}', 'GET /audit/export'],
  },
  users: {
    key: 'users',
    path: '/admin/users',
    label: 'Users',
    icon: IconUsers,
    placeholder: 'User administration is not built yet. It will list people, their roles and approval limits.',
    description:
      'People, their roles, departments, status and approval limits. The controller can change them; auditors read.',
    endpoints: ['GET /admin/users', 'PATCH /admin/users/{user_id}'],
  },
  policies: {
    key: 'policies',
    path: '/admin/policies',
    label: 'Policies',
    icon: IconShieldCheck,
    placeholder: 'Policy administration is not built yet. It will list approval and payment policies.',
    description:
      'The approval and payment policies with their thresholds. The controller can edit them; auditors read.',
    endpoints: ['GET /admin/policies', 'PATCH /admin/policies/{rule_id}'],
  },
  absences: {
    key: 'absences',
    path: '/admin/absences',
    label: 'Absences',
    icon: IconCalendarUser,
    placeholder: 'Absences are not built yet. They will list who is away and who signs in their place.',
    description: 'Who is away, from when to when, and who signs in their place. The controller can add absences.',
    endpoints: ['GET /admin/absences', 'POST /admin/absences'],
  },
  delegation: {
    key: 'delegation',
    path: '/out-of-office',
    label: 'Out of office',
    icon: IconUserShare,
    placeholder: 'Out of office is not built yet. It will let you name a delegate for a date range.',
    description:
      'Name a delegate who may approve for you while you are away, with start and end dates. While it is active the ' +
      'delegate sees a banner and your approvals, and their decisions are recorded as on your behalf.',
    endpoints: ['PUT /me/delegation'],
  },
}

/** Each role's sidebar, in order. The first item is the role's home page. */
export const NAV_BY_ROLE: Record<Role, readonly NavKey[]> = {
  employee: ['submit', 'submissions', 'bills'],
  ap_clerk: ['inbox', 'review', 'bills', 'payments', 'vendors', 'bankChanges'],
  approver: ['approvals', 'bills', 'spend', 'delegation'],
  finance_manager: ['approvals', 'payments', 'bills', 'vendors', 'bankChanges', 'unassigned', 'spend', 'delegation'],
  controller_admin: ['approvals', 'payments', 'bills', 'vendors', 'bankChanges', 'unassigned', 'spend', 'audit',
    'users', 'policies', 'absences', 'delegation'],
  auditor: ['audit', 'bills', 'payments', 'vendors', 'bankChanges', 'spend', 'users', 'policies', 'absences'],
}

/** Every screen, for building the routes. */
export const ALL_NAV_ITEMS: readonly NavItem[] = Object.values(NAV_ITEMS)

/** The sidebar items for `role`, in order. */
export function navItemsFor(role: Role): NavItem[] {
  return NAV_BY_ROLE[role].map((key) => NAV_ITEMS[key])
}

/** Where `role` lands after signing in: their first sidebar item. */
export function homePathFor(role: Role): string {
  const first = NAV_BY_ROLE[role][0]
  return first ? NAV_ITEMS[first].path : '/bills'
}

/** True when `key` is in `role`'s sidebar. */
export function isInNavigation(role: Role, key: NavKey): boolean {
  return NAV_BY_ROLE[role].includes(key)
}
