"""GTM Operations Dashboard calculations.

Plain functions over the engine's assessment results (from helpers.score_rows). Nothing here scores,
reclassifies or changes a record: every value comes from fields the engine already produced, and every
function returns new lists so filtering can never alter the results used by the other tabs or the exports.
"""

from .helpers import CAMPAIGN_OUTCOMES, CONTACT_OUTCOMES, ICP_OUTCOMES, MARKED_REAL, SYNTHETIC, UNVERIFIED, count_by

SCORE_MIN = 0
SCORE_MAX = 100
SCORE_BIN_WIDTH = 10

KPI_LABELS = [
    ("total", "Total Companies Analysed"),
    ("qualified", "Qualified Accounts"),
    ("review", "Accounts Under Review"),
    ("disqualified", "Disqualified Accounts"),
    ("contacts_ready", "Contacts Ready"),
    ("ready_to_sequence", "Campaigns Ready to Sequence"),
]

PRIORITY_COLUMNS = ["Data", "Company", "ICP score", "ICP classification", "Contact readiness", "Campaign readiness"]


def score_of(result):
    """The engine's icp_score as an int, or None if it is missing or malformed (never guessed)."""
    try:
        return int(result.get("icp_score"))
    except (TypeError, ValueError):
        return None


def filter_dashboard(results, icp=None, contact=None, campaign=None, score_range=(SCORE_MIN, SCORE_MAX)):
    """Records matching every filter. Empty lists mean 'no filter'; the score range is inclusive.

    A record without a valid score is excluded only when the range is narrowed from the full 0-100.
    Returns a new list; the result dicts themselves are never modified.
    """
    low, high = score_range
    full_range = (low, high) == (SCORE_MIN, SCORE_MAX)
    selected = []
    for result in results:
        if icp and result.get("icp_outcome") not in icp:
            continue
        if contact and result.get("contact_readiness") not in contact:
            continue
        if campaign and result.get("campaign_readiness") not in campaign:
            continue
        score = score_of(result)
        if not full_range and (score is None or not low <= score <= high):
            continue
        selected.append(result)
    return selected


def kpis(results):
    icp = count_by(results, "icp_outcome", ICP_OUTCOMES)
    return {
        "total": len(results),
        "qualified": icp["Qualified"],
        "review": icp["Review"],
        "disqualified": icp["Disqualified"],
        "contacts_ready": count_by(results, "contact_readiness", CONTACT_OUTCOMES)["Ready"],
        "ready_to_sequence": count_by(results, "campaign_readiness", CAMPAIGN_OUTCOMES)["Ready to Sequence"],
    }


def distribution(results, field, outcomes):
    """Count and share per outcome, in the engine's fixed order, including zero counts.

    Unrecognised values are counted under their own name after the known outcomes, never dropped.
    """
    counts = count_by(results, field, outcomes)
    total = len(results)
    return [{"category": category, "count": count, "share": count / total if total else 0.0}
            for category, count in counts.items()]


def icp_distribution(results):
    return distribution(results, "icp_outcome", ICP_OUTCOMES)


def contact_distribution(results):
    return distribution(results, "contact_readiness", CONTACT_OUTCOMES)


def campaign_distribution(results):
    return distribution(results, "campaign_readiness", CAMPAIGN_OUTCOMES)


def score_histogram(results, bin_width=SCORE_BIN_WIDTH):
    """Counts of ICP scores in fixed bins (0-9, 10-19, ..., 90-100; 100 joins the last bin).

    Records without a valid score are reported separately rather than placed in a bin.
    """
    starts = list(range(SCORE_MIN, SCORE_MAX, bin_width))
    bins = [{"start": start, "end": min(start + bin_width - 1, SCORE_MAX), "count": 0} for start in starts]
    bins[-1]["end"] = SCORE_MAX
    missing = 0
    for result in results:
        score = score_of(result)
        if score is None or not SCORE_MIN <= score <= SCORE_MAX:
            missing += 1
            continue
        bins[min((score - SCORE_MIN) // bin_width, len(bins) - 1)]["count"] += 1
    for item in bins:
        item["label"] = f"{item['start']}-{item['end']}"
    return bins, missing


def prioritised_accounts(results):
    """Accounts ordered for GTM follow-up, using only existing engine outputs.

    Order: campaign readiness in the engine's order (Ready to Sequence first, Excluded last; any
    unrecognised value after those), then ICP score high to low, then company_id.
    """
    rank = {outcome: index for index, outcome in enumerate(CAMPAIGN_OUTCOMES)}

    def key(result):
        score = score_of(result)
        return (rank.get(result.get("campaign_readiness"), len(rank)), -(score if score is not None else -1),
                str(result.get("company_id", "")))

    return [{
        "Data": data_badge(result.get("data_status")),
        "Company": result.get("company_name", ""),
        "ICP score": score_of(result),
        "ICP classification": result.get("icp_outcome", ""),
        "Contact readiness": result.get("contact_readiness", ""),
        "Campaign readiness": result.get("campaign_readiness", ""),
    } for result in sorted(results, key=key)]


def data_badge(status):
    return {SYNTHETIC: "🧪 TEST DATA", UNVERIFIED: "⚠ UNVERIFIED"}.get(status, "")


def dataset_label(results):
    """How to describe the dataset on the dashboard. Anything not marked genuine is never called real."""
    statuses = [result.get("data_status") for result in results]
    if not statuses:
        return "empty", "No records."
    if all(status == SYNTHETIC for status in statuses):
        return "synthetic", "Synthetic demo data: fictional test records, not real prospects."
    if SYNTHETIC in statuses:
        return "mixed", (f"Contains {statuses.count(SYNTHETIC)} synthetic test record(s); they are not real "
                         "prospects.")
    if any(status != MARKED_REAL for status in statuses):
        return "unverified", "Unverified data: some records are not marked is_synthetic=false."
    return "marked_real", "Records are marked is_synthetic=false."
