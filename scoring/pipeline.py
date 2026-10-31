"""Load records, run the three assessments, and write results."""

import csv
from datetime import date

from ui.csv_safety import neutralise_row

from . import rules
from .campaign import assess_campaign
from .contact import assess_contact
from .icp import assess_icp

CRITERIA = ("saas_fit", "size", "sales_function", "hiring", "outbound")


class SyntheticDataError(Exception):
    """Raised when synthetic or unverified records reach an export or sequencing step."""


def scoring_input(row):
    """Copy of the row with test-only metadata removed, so it cannot influence scoring."""
    return {key: value for key, value in row.items() if key not in rules.EXCLUDED_INPUT_COLUMNS}


def assess_record(row, as_of):
    record = scoring_input(row)
    icp = assess_icp(record, as_of)
    contact = assess_contact(record)
    campaign = assess_campaign(record, icp, contact, as_of)

    result = {
        "company_id": record.get("company_id", ""),
        "company_name": record.get("company_name", ""),
        "is_synthetic": record.get("is_synthetic", ""),
        "icp_outcome": icp.outcome,
        "icp_score": icp.icp_score,
        "potential_score": icp.potential_score,
        "size_indication": icp.size_indication,
    }
    for name in CRITERIA:
        criterion = icp.criteria[name]
        result[f"{name}_status"] = criterion.status
        result[f"{name}_points"] = criterion.points
        result[f"{name}_potential"] = criterion.potential
    result.update({
        "icp_flags": "|".join(icp.flags),
        "icp_reasons": " ".join(icp.criteria[name].reason for name in CRITERIA),
        "contact_readiness": contact.readiness,
        "contact_flags": "|".join(contact.flags),
        "contact_reasons": " ".join(contact.reasons),
        "campaign_readiness": campaign.readiness,
        "campaign_trigger_status": campaign.trigger_status,
        "campaign_reasons": " ".join(campaign.reasons),
    })
    return result


def load_records(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def score_file(input_path, as_of=None):
    as_of = as_of or date.today()
    return [assess_record(row, as_of) for row in load_records(input_path)]


def write_results(results, output_path):
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        # Neutralise spreadsheet formula injection in the file only; `results` is left unchanged.
        writer.writerows(neutralise_row(result) for result in results)


def is_explicitly_not_synthetic(value):
    """Fail closed: only the string 'false' (case-insensitive, trimmed) counts as genuine data."""
    return isinstance(value, str) and value.strip().lower() == "false"


def sequencing_export(results):
    """Rows eligible to enter a real sequence.

    Fails closed: if any record is synthetic or unverified (is_synthetic missing, blank,
    None, non-string or any value other than 'false'), nothing is exported.
    """
    synthetic, unverified = [], []
    for position, result in enumerate(results, start=1):
        value = result.get("is_synthetic")
        if is_explicitly_not_synthetic(value):
            continue
        label = result.get("company_id") or f"<record {position}>"
        if isinstance(value, str) and value.strip().lower() == "true":
            synthetic.append(label)
        else:
            unverified.append(label)
    if synthetic or unverified:
        problems = []
        if synthetic:
            problems.append(f"{len(synthetic)} synthetic record(s): {', '.join(synthetic)}")
        if unverified:
            problems.append(f"{len(unverified)} record(s) not explicitly marked is_synthetic=false: "
                            f"{', '.join(unverified)}")
        raise SyntheticDataError("Refusing to export " + "; ".join(problems))
    return [result for result in results if result["campaign_readiness"] == "Ready to Sequence"]
