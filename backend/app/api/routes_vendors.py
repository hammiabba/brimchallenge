"""Vendor master, onboarding, approval/hold, and controlled bank-detail changes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.common import READ_ERRORS, WRITE_ERRORS, Limit, Offset
from app.api.errors import not_implemented
from app.api.schemas_api import (
    BankChangeIn,
    BankChangeOut,
    CommentIn,
    Page,
    VendorDetail,
    VendorIn,
    VendorStatus,
    VendorSummary,
)
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import ALL_ROLES, AP_CLERK, BACK_OFFICE_READ, CONTROLLER_ADMIN, FINANCE_MANAGER, VENDOR_APPROVERS

router = APIRouter(tags=["vendors"])


@router.get("/vendors", response_model=Page[VendorSummary], responses=READ_ERRORS)
def list_vendors(user: CurrentUser = Depends(require_role(*ALL_ROLES)),
                 status: Annotated[list[VendorStatus] | None, Query()] = None,
                 q: Annotated[str | None, Query(max_length=100)] = None, limit: Limit = 100, offset: Offset = 0):
    raise not_implemented("Vendor list")


@router.get("/vendors/{vendor_id}", response_model=VendorDetail, responses=READ_ERRORS)
def get_vendor(vendor_id: str, user: CurrentUser = Depends(require_role(*ALL_ROLES))):
    raise not_implemented("Vendor detail")


@router.post("/vendors", response_model=VendorDetail, status_code=201, responses=WRITE_ERRORS)
def onboard_vendor(body: VendorIn, user: CurrentUser = Depends(require_role(AP_CLERK))):
    raise not_implemented("Vendor onboarding")


@router.post("/vendors/{vendor_id}/approve", response_model=VendorDetail, responses=WRITE_ERRORS)
def approve_vendor(vendor_id: str, body: CommentIn, user: CurrentUser = Depends(require_role(*VENDOR_APPROVERS))):
    raise not_implemented("Vendor approval")


@router.post("/vendors/{vendor_id}/hold", response_model=VendorDetail, responses=WRITE_ERRORS)
def hold_vendor(vendor_id: str, body: CommentIn,
                user: CurrentUser = Depends(require_role(AP_CLERK, FINANCE_MANAGER, CONTROLLER_ADMIN))):
    raise not_implemented("Vendor hold")


@router.post("/vendors/{vendor_id}/bank-changes", response_model=BankChangeOut, status_code=201,
             responses=WRITE_ERRORS)
def request_bank_change(vendor_id: str, body: BankChangeIn, user: CurrentUser = Depends(require_role(AP_CLERK))):
    raise not_implemented("Bank change request")


@router.get("/bank-changes", response_model=list[BankChangeOut], responses=READ_ERRORS)
def list_bank_changes(user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ)), status: str | None = None):
    raise not_implemented("Bank change list")


@router.post("/bank-changes/{change_id}/verify", response_model=BankChangeOut, responses=WRITE_ERRORS)
def verify_bank_change(change_id: str, body: CommentIn,
                       user: CurrentUser = Depends(require_role(*VENDOR_APPROVERS))):
    raise not_implemented("Bank change verification")


@router.post("/bank-changes/{change_id}/reject", response_model=BankChangeOut, responses=WRITE_ERRORS)
def reject_bank_change(change_id: str, body: CommentIn,
                       user: CurrentUser = Depends(require_role(*VENDOR_APPROVERS))):
    raise not_implemented("Bank change rejection")
