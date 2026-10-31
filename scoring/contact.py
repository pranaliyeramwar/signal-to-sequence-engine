"""B. Contact readiness (spec section B). Independent of the ICP score."""

from dataclasses import dataclass

from . import rules
from .icp import contains_any

SEVERITY = {"Ready": 0, "Needs Attention": 1, "Not Ready": 2}

EMAIL_STATUS_RESULTS = {
    "invalid": ("Not Ready", "EMAIL_INVALID", "Email is invalid."),
    "risky": ("Not Ready", "EMAIL_RISKY", "Email is risky."),
    "catch_all": ("Needs Attention", "EMAIL_CATCH_ALL", "Email domain is catch-all; mailbox unconfirmed."),
    "unverified": ("Needs Attention", "EMAIL_UNVERIFIED", "Email has not been verified."),
}


@dataclass
class ContactResult:
    readiness: str
    flags: list
    reasons: list


def assess_contact(row):
    name = " ".join(part for part in ((row.get("contact_first_name") or "").strip(),
                                      (row.get("contact_last_name") or "").strip()) if part)
    email = (row.get("contact_email") or "").strip()
    status = (row.get("email_verification_status") or "").strip().lower()
    title = (row.get("contact_title") or "").strip()

    if not name and not email:
        return ContactResult("Not Ready", ["CONTACT_MISSING"], ["No contact on record."])

    checks = []
    if not email:
        checks.append(("Not Ready", "EMAIL_MISSING", "Contact email is missing."))
    elif status == "verified":
        pass
    elif status in EMAIL_STATUS_RESULTS:
        checks.append(EMAIL_STATUS_RESULTS[status])
    else:
        checks.append(("Needs Attention", "EMAIL_UNVERIFIED", "Email verification status is missing."))

    if not title or not contains_any(title, rules.TARGET_PERSONA_TERMS):
        checks.append(("Needs Attention", "PERSONA_MISMATCH",
                       f"Title {title!r} is not a target persona." if title else "Contact title is missing."))

    if not checks:
        return ContactResult("Ready", [], ["Verified email and target persona."])
    readiness = max((check[0] for check in checks), key=SEVERITY.get)
    return ContactResult(readiness, [check[1] for check in checks], [check[2] for check in checks])
