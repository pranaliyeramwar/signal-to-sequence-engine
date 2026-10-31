"""C. Campaign readiness (spec section C). Reads A and B; never changes them."""

from dataclasses import dataclass

from .icp import is_recent, parse_date


@dataclass
class CampaignResult:
    readiness: str
    trigger_status: str
    reasons: list


def trigger_status(row, hiring_status, as_of):
    """hiring | documented | stale | none. Outbound confidence is never a trigger."""
    if hiring_status == "current":
        return "hiring"
    trigger = (row.get("campaign_trigger") or "").strip()
    trigger_date = parse_date(row.get("campaign_trigger_date"))
    if trigger and trigger_date and is_recent(trigger_date, as_of):
        return "documented"
    if hiring_status == "stale" or trigger:
        return "stale"
    return "none"


def assess_campaign(row, icp, contact, as_of):
    status = trigger_status(row, icp.criteria["hiring"].status, as_of)

    blockers = []
    if icp.outcome == "Disqualified":
        blockers.append(("Excluded", "Company is ICP Disqualified."))
    elif icp.outcome == "Review":
        blockers.append(("Hold: ICP Review", "Company ICP needs manual review."))
    if contact.readiness != "Ready":
        blockers.append(("Hold: Contact", f"Contact is {contact.readiness}."))
    if status not in ("hiring", "documented"):
        detail = "only stale triggers found" if status == "stale" else "no documented trigger"
        blockers.append(("Hold: Trigger Research", f"No current campaign trigger ({detail})."))

    if not blockers:
        trigger_reason = "current relevant hiring" if status == "hiring" else "current documented trigger"
        return CampaignResult("Ready to Sequence", status, [f"Qualified, contact ready, {trigger_reason}."])
    return CampaignResult(blockers[0][0], status, [reason for _, reason in blockers])
