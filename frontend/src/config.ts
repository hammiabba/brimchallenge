/** The product name, shown in the header, the sign-in page and the browser tab. Change it here only. */
export const APP_NAME = 'AP Automation'

/** One demo persona: who to sign in as, and one line on what that role comes to do. */
export interface DemoPersona {
  userId: string
  hint: string
}

/**
 * One demo person per role, for one-click sign-in, in this order: employee, AP clerk, approver, finance manager,
 * controller / admin, auditor. Only the user ids and hints live here; names, titles, departments and roles come from
 * GET /auth/users, and a person that list doesn't include is skipped.
 */
export const DEMO_PERSONAS: readonly DemoPersona[] = [
  { userId: 'U013', hint: 'Submit an invoice and track it' },
  { userId: 'U004', hint: 'Run the inbox and fix flagged bills' },
  { userId: 'U007', hint: "Approve or reject your department's bills" },
  { userId: 'U003', hint: 'Release payments and approve as a delegate' },
  { userId: 'U001', hint: 'Verify bank changes and edit approval rules' },
  { userId: 'U006', hint: 'Read and export the audit trail' },
]
