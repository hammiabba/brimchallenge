"""Short title and plain-English help for every flag code, for the UI.

    from app.controls.flag_help import FLAG_HELP, help_for
    help_for("BANK_CHANGE_UNVERIFIED")
    # {"code": "BANK_CHANGE_UNVERIFIED", "severity": "block", "title": "Bank change not verified",
    #  "help": "..."}

The flag's own `message` says what was found on *this* bill (amounts, ids). This file says what the code means in
general and what to do about it, so the UI can show it as a tooltip or help panel. Severity always comes from
FLAG_CODES in schemas.py. A test fails if a code in FLAG_CODES has no entry here.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.shared.schemas import FLAG_CODES


@dataclass(frozen=True)
class FlagHelp:
    title: str   # a few words, for a badge or list row
    help: str    # one sentence: what it means and what to do


FLAG_HELP: dict[str, FlagHelp] = {
    # vendor
    "VENDOR_NOT_FOUND": FlagHelp(
        "Unknown vendor",
        "The vendor isn't in the vendor master, so onboard and approve them before this bill can be paid."),
    "VENDOR_NOT_ACTIVE": FlagHelp(
        "Vendor on hold",
        "The vendor master says not to pay this vendor right now, so check with finance before going further."),
    "VENDOR_LOOKALIKE": FlagHelp(
        "Lookalike vendor",
        "This vendor looks like another existing vendor, which is a common fraud pattern, so call the real vendor "
        "on a number you already have before approving."),
    "GST_NUMBER_MISMATCH": FlagHelp(
        "GST number differs",
        "The GST/HST number on the invoice doesn't match the vendor master, so check for a typo or a fake invoice "
        "with the vendor."),
    "BANK_DETAILS_MISMATCH": FlagHelp(
        "Bank details differ",
        "The bank account on the invoice isn't the one on file, or didn't exist yet on the invoice's date, so don't "
        "pay until the vendor confirms it by phone on a known number."),
    "BANK_CHANGE_UNVERIFIED": FlagHelp(
        "Bank change not verified",
        "The vendor's bank account was changed recently without a callback check, so hold payment until someone "
        "verifies it by phone."),
    "VENDOR_PENDING_REVIEW": FlagHelp(
        "Vendor pending review",
        "The vendor hasn't finished onboarding review, so a finance manager approval is added to the route."),
    "GST_NUMBER_MISSING": FlagHelp(
        "No GST number",
        "The vendor has no GST/HST number on file or on the invoice, so confirm it's a small supplier (under $30k a "
        "year) before paying, and if it charged GST/HST anyway, that tax can't be claimed back and may mean a fake "
        "invoice."),
    "SENDER_DOMAIN_MISMATCH": FlagHelp(
        "Unexpected sender",
        "The email came from a different domain than the vendor's usual contact, so confirm with the vendor that "
        "they really sent it."),
    # tax / arithmetic
    "TAX_WRONG_FOR_PROVINCE": FlagHelp(
        "Wrong tax for province",
        "The tax charged doesn't match the province the goods or services were delivered to, so the bill is held "
        "until the vendor sends a corrected invoice."),
    "TAX_MISSING": FlagHelp(
        "Tax missing",
        "Tax that should apply for the delivery province isn't charged, so the bill is held until the vendor sends "
        "a corrected invoice."),
    "PST_ON_SERVICES": FlagHelp(
        "PST on services",
        "BC PST was charged on services, but it only applies to goods, so ask the vendor for a corrected invoice."),
    "LINE_MATH_ERROR": FlagHelp(
        "Line math wrong",
        "A line's quantity times unit price doesn't equal its amount, so the bill is held until the vendor corrects "
        "it."),
    "SUBTOTAL_MISMATCH": FlagHelp(
        "Subtotal wrong",
        "The lines don't add up to the subtotal printed on the invoice, so the bill is held until the missing line "
        "or typo is fixed."),
    "TOTAL_MISMATCH": FlagHelp(
        "Total wrong",
        "The subtotal plus taxes doesn't equal the total printed on the invoice, so the bill is held until the "
        "vendor corrects it."),
    # contract / PO
    "OVER_CONTRACT_RATE": FlagHelp(
        "Above contract price",
        "A fee, rate, overage or one-off charge doesn't match the contract, so confirm it was agreed before "
        "approving."),
    "OVER_FUEL_SURCHARGE_CAP": FlagHelp(
        "Fuel surcharge too high",
        "The fuel surcharge is above the cap in the vendor's contract, so ask the vendor to bill at the capped "
        "rate."),
    "OVER_CONTRACT_NTE": FlagHelp(
        "Over monthly limit",
        "This bill takes the vendor's billing for the month over the contract's not-to-exceed amount, so get "
        "approval for the extra spend."),
    "CONTRACT_EXPIRED": FlagHelp(
        "Contract expired",
        "The invoice is dated after the vendor's contract ended, so confirm the work was authorized or renew the "
        "contract."),
    "PO_REQUIRED_MISSING": FlagHelp(
        "PO missing",
        "This vendor requires a purchase order and the invoice has none, so hold it until a PO is attached."),
    "PO_OVER_BALANCE": FlagHelp(
        "Over PO balance",
        "The bill is more than what's left on its purchase order, so a finance manager approval is added."),
    "PO_CLOSED_OR_WRONG_VENDOR": FlagHelp(
        "PO closed or wrong vendor",
        "The purchase order is closed or belongs to another vendor, so attach the right PO before paying."),
    "PO_NOT_FOUND": FlagHelp(
        "PO not found",
        "The PO number on the invoice doesn't exist, so get the correct PO number from the requester or vendor."),
    # duplicates / fraud
    "DUPLICATE_EXACT": FlagHelp(
        "Duplicate invoice",
        "This invoice number was already billed by this vendor, so don't pay it again unless the earlier one was "
        "rejected."),
    "DUPLICATE_LIKELY": FlagHelp(
        "Possible duplicate",
        "A very similar bill from this vendor already exists, so compare the two before approving."),
    "ALREADY_PAID_BY_CARD": FlagHelp(
        "Already paid by card",
        "A card charge matches this bill, so check it wasn't already paid before paying it again by EFT."),
    "POSSIBLE_SPLIT": FlagHelp(
        "Possible split invoice",
        "Several bills from this vendor close together add up to more than the approval limit, so approve them as "
        "one combined amount."),
    # misc
    "CREDIT_NOTE": FlagHelp(
        "Credit note",
        "This is a credit, not a bill to pay, so apply it against an open invoice from the same vendor."),
    "FOREIGN_CURRENCY": FlagHelp(
        "Foreign currency",
        "The bill isn't in CAD, so check the exchange rate and the CAD amount shown before approving."),
    "CURRENCY_UNSUPPORTED": FlagHelp(
        "No exchange rate",
        "There's no reliable exchange rate for this currency and date, so convert it to CAD manually before "
        "approving."),
    "DATE_ANOMALY": FlagHelp(
        "Odd date",
        "The invoice date is in the future or very old, or the due date comes before it, so check the date and "
        "that it wasn't already paid."),
    "LOW_EXTRACTION_CONFIDENCE": FlagHelp(
        "Check extracted data",
        "Some fields were hard to read from the document, so compare them with the original before approving."),
    "REQUESTER_TERMINATED": FlagHelp(
        "Requester has left",
        "The person who requested this no longer works here, so confirm with their manager that it's still needed."),
}


def help_for(code: str) -> dict:
    """Title, help and severity for a flag code, as a dict for the API. Unknown codes get a generic entry."""
    h = FLAG_HELP.get(code, FlagHelp(code.replace("_", " ").capitalize(), "See the flag's message for details."))
    return {"code": code, "severity": FLAG_CODES.get(code), "title": h.title, "help": h.help}
