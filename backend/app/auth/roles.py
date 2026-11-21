"""Role names (users.role) and the groups the routes and services refer to.

Keeping the groups here means a role rule is changed in one place, and the permission-matrix test reads the same
constants the routes use.
"""
from __future__ import annotations

EMPLOYEE = "employee"
AP_CLERK = "ap_clerk"
APPROVER = "approver"
FINANCE_MANAGER = "finance_manager"
CONTROLLER_ADMIN = "controller_admin"
AUDITOR = "auditor"

ALL_ROLES = (EMPLOYEE, AP_CLERK, APPROVER, FINANCE_MANAGER, CONTROLLER_ADMIN, AUDITOR)

# Roles that see every bill, payment and vendor (no department scoping).
SEE_ALL = (AP_CLERK, FINANCE_MANAGER, CONTROLLER_ADMIN, AUDITOR)
# Roles that sign approval steps.
SIGNERS = (APPROVER, FINANCE_MANAGER, CONTROLLER_ADMIN)
# Roles that work the AP back office (payments, intake, bank changes) read-side.
BACK_OFFICE_READ = (AP_CLERK, FINANCE_MANAGER, CONTROLLER_ADMIN, AUDITOR)
# Roles that may release payments; the amount rules (P09/P10) and P11 live in controls.can_release.
RELEASERS = (FINANCE_MANAGER, CONTROLLER_ADMIN)
# Roles that approve vendor changes (onboarding, bank details).
VENDOR_APPROVERS = (FINANCE_MANAGER, CONTROLLER_ADMIN)
# Roles that read the full audit log and the admin tables.
AUDIT_READERS = (CONTROLLER_ADMIN, AUDITOR)
# Roles that see full bank account numbers. Everyone else gets the last 4 digits.
FULL_BANK_DETAILS = (AP_CLERK, FINANCE_MANAGER, CONTROLLER_ADMIN)
