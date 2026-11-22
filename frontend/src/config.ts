/** The product name, shown in the header, the sign-in page and the browser tab. Change it here only. */
export const APP_NAME = 'AP Automation'

/**
 * One demo person per role, for one-click sign-in, in this order: employee, AP clerk, approver, finance manager,
 * controller / admin, auditor. Only the user ids live here; names, titles, departments and roles come from
 * GET /auth/users, and a person that list doesn't include is skipped.
 */
export const DEMO_PERSONAS: readonly string[] = ['U013', 'U004', 'U007', 'U003', 'U001', 'U006']
