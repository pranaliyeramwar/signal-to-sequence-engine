"""Validate the sample dataset and the hand-derived expected results.

This script deliberately does not import the scoring engine. It checks:
  1. sample_companies.csv against the data dictionary (schema, enums, formats,
     cross-field consistency, synthetic-data guarantees);
  2. tests/fixtures/expected_results.csv against the points tables and
     classification order in docs/scoring_specification.md, so the oracle the
     engine tests compare against is itself internally consistent.

Usage: python -I scripts/validate_dataset.py
"""

import csv
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "input" / "sample_companies.csv"
EXPECTED = ROOT / "tests" / "fixtures" / "expected_results.csv"

COLUMNS = [
    "company_id", "company_name", "domain", "industry", "hq_country", "description",
    "employee_count_source_a", "employee_count_source_b", "open_sales_roles",
    "sales_role_titles", "hiring_role_notes", "hiring_signal_last_seen",
    "outbound_evidence_level", "outbound_evidence_notes", "campaign_trigger",
    "campaign_trigger_date", "contact_first_name", "contact_last_name", "contact_title",
    "contact_email", "email_verification_status", "is_synthetic", "test_scenario",
]
REQUIRED = {"company_id", "company_name", "domain", "industry", "hq_country",
            "outbound_evidence_level", "is_synthetic", "test_scenario"}
OUTBOUND_LEVELS = {"strong", "moderate", "weak", "none", "unknown"}
EMAIL_STATUSES = {"verified", "unverified", "catch_all", "risky", "invalid"}

# (points, potential) per status: spec sections A.3 to A.7.
POINTS = {
    "saas_fit_status": {"confirmed": (30, 0), "not_saas": (0, 0), "unclear": (0, 30), "unknown": (0, 30)},
    "size_status": {"confirmed_in_range": (20, 0), "confirmed_out_of_range": (0, 0), "conflict": (0, 20),
                    "single_source": (0, 20), "unknown": (0, 20)},
    "sales_function_status": {"present": (20, 0), "confirmed_absent": (0, 0), "unknown": (0, 20)},
    "hiring_status": {"current": (20, 0), "stale": (0, 20), "date_missing": (0, 20), "role_unverified": (0, 20),
                      "confirmed_none": (0, 0), "titles_missing": (0, 20), "unknown": (0, 20)},
    "outbound_status": {"strong": (10, 0), "moderate": (7, 0), "weak": (3, 0), "none": (0, 0), "unknown": (0, 10)},
}
MAX_POINTS = {"saas_fit_status": 30, "size_status": 20, "sales_function_status": 20,
              "hiring_status": 20, "outbound_status": 10}
BLOCKING_SIZE = {"conflict", "single_source", "unknown"}
BLOCKING_FIT = {"unclear", "unknown"}
CONTACT_OUTCOMES = {"Ready", "Needs Attention", "Not Ready"}
TRIGGER_STATUSES = {"hiring", "documented", "none", "stale"}

errors = []


def error(where, message):
    errors.append(f"{where}: {message}")


def is_int(value):
    return re.fullmatch(r"\d+", value) is not None


def is_date(value):
    try:
        date.fromisoformat(value)
        return re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None
    except ValueError:
        return False


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def validate_dataset():
    header, rows = read_csv(DATASET)
    if header != COLUMNS:
        error("dataset header", f"expected {COLUMNS}, got {header}")
        return {}
    if len(rows) != 25:
        error("dataset", f"expected 25 records, got {len(rows)}")

    seen = set()
    for row in rows:
        cid = row["company_id"]
        where = f"dataset {cid or '<no id>'}"
        if None in row or any(value is None for value in row.values()):
            error(where, "wrong number of fields")
            continue
        for column in REQUIRED:
            if not row[column].strip():
                error(where, f"required column {column} is empty")
        if not re.fullmatch(r"SYN-\d{3}", cid):
            error(where, "company_id must match SYN-NNN")
        if cid in seen:
            error(where, "duplicate company_id")
        seen.add(cid)
        if not re.fullmatch(r"[a-z0-9-]+\.example", row["domain"]):
            error(where, "domain must be a lowercase hostname ending in .example")
        if not re.fullmatch(r"[A-Z]{2}", row["hq_country"]):
            error(where, "hq_country must be ISO alpha-2")
        for column in ("employee_count_source_a", "employee_count_source_b", "open_sales_roles"):
            if row[column] and not is_int(row[column]):
                error(where, f"{column} must be a non-negative integer or empty")
        for column in ("hiring_signal_last_seen", "campaign_trigger_date"):
            if row[column] and not is_date(row[column]):
                error(where, f"{column} must be YYYY-MM-DD")
        if row["outbound_evidence_level"] not in OUTBOUND_LEVELS:
            error(where, "outbound_evidence_level not an allowed value")
        if row["is_synthetic"] != "true":
            error(where, "is_synthetic must be true")

        email, status = row["contact_email"], row["email_verification_status"]
        if email and not email.endswith("@" + row["domain"]):
            error(where, "contact_email must use the company's .example domain")
        if status and status not in EMAIL_STATUSES:
            error(where, "email_verification_status not an allowed value")
        if bool(email) != bool(status):
            error(where, "email_verification_status must be set exactly when contact_email is set")

        roles, titles = row["open_sales_roles"], row["sales_role_titles"]
        title_list = [t for t in titles.split("|") if t.strip()] if titles else []
        if not roles and (titles or row["hiring_signal_last_seen"]):
            error(where, "hiring not researched (open_sales_roles empty) but titles or date present")
        if roles == "0" and (titles or row["hiring_signal_last_seen"]):
            error(where, "open_sales_roles is 0 but titles or date present")
        if title_list and is_int(roles) and int(roles) != len(title_list):
            error(where, f"open_sales_roles={roles} but {len(title_list)} titles listed")
        if row["hiring_role_notes"] and not title_list:
            error(where, "hiring_role_notes present without titles")
        if bool(row["campaign_trigger"]) != bool(row["campaign_trigger_date"]):
            error(where, "campaign_trigger and campaign_trigger_date must be set together")
    return {row["company_id"]: row for row in rows}


def expected_icp_outcome(row, icp_score, potential_score):
    """Classification order from spec A.8."""
    if row["size_status"] == "confirmed_out_of_range":
        return "Disqualified"
    if row["saas_fit_status"] == "not_saas":
        return "Disqualified"
    blocked = row["size_status"] in BLOCKING_SIZE or row["saas_fit_status"] in BLOCKING_FIT
    if icp_score >= 70 and not blocked:
        return "Qualified"
    if icp_score >= 40:
        return "Review"
    if potential_score >= 70:
        return "Review"
    return "Disqualified"


def expected_campaign(icp, contact, trigger):
    """Campaign readiness order from spec C."""
    if icp == "Disqualified":
        return "Excluded"
    if icp == "Review":
        return "Hold: ICP Review"
    if contact != "Ready":
        return "Hold: Contact"
    if trigger not in {"hiring", "documented"}:
        return "Hold: Trigger Research"
    return "Ready to Sequence"


def validate_expected(dataset):
    _, rows = read_csv(EXPECTED)
    ids = [row["company_id"] for row in rows]
    if sorted(ids) != sorted(dataset):
        error("expected", "company_ids do not match the dataset one-to-one")

    for row in rows:
        where = f"expected {row['company_id']}"
        score = potential = 0
        for column, table in POINTS.items():
            if row[column] not in table:
                error(where, f"{column}={row[column]!r} is not a status in the spec")
                break
            points, unresolved = table[row[column]]
            if points and unresolved:
                error(where, f"{column} has both confirmed and unresolved points")
            if points + unresolved > MAX_POINTS[column]:
                error(where, f"{column} exceeds its maximum")
            score += points
            potential += unresolved
        else:
            potential += score
            if int(row["icp_score"]) != score:
                error(where, f"icp_score {row['icp_score']} != sum of confirmed points {score}")
            if int(row["potential_score"]) != potential:
                error(where, f"potential_score {row['potential_score']} != {potential}")
            if potential > 100:
                error(where, "potential_score exceeds 100")
            outcome = expected_icp_outcome(row, score, potential)
            if row["icp_outcome"] != outcome:
                error(where, f"icp_outcome {row['icp_outcome']} but spec order gives {outcome}")
        if row["contact_readiness"] not in CONTACT_OUTCOMES:
            error(where, "contact_readiness not an allowed value")
        if row["campaign_trigger_status"] not in TRIGGER_STATUSES:
            error(where, "campaign_trigger_status not an allowed value")
        if row["hiring_status"] == "current" and row["campaign_trigger_status"] != "hiring":
            error(where, "current hiring must make the trigger status 'hiring'")
        campaign = expected_campaign(row["icp_outcome"], row["contact_readiness"], row["campaign_trigger_status"])
        if row["campaign_readiness"] != campaign:
            error(where, f"campaign_readiness {row['campaign_readiness']} but spec order gives {campaign}")
    return rows


def main():
    dataset = validate_dataset()
    expected = validate_expected(dataset) if dataset else []
    if errors:
        print(f"FAILED with {len(errors)} error(s):")
        for message in errors:
            print("  -", message)
        return 1
    print(f"OK: {len(dataset)} dataset records and {len(expected)} expected results are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
