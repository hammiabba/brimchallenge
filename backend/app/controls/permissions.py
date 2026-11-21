"""Payment permission rules. Kept as a module because the API guide refers to `controls.permissions`.

The implementation lives in approvals.py; see that module for the rules (P07, P09-P11).
"""
from app.controls.approvals import can_approve, can_release

__all__ = ["can_approve", "can_release"]
