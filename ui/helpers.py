"""Plain functions behind the Streamlit app.

No Streamlit import here, so everything is testable with unittest alone. Scoring is
delegated to scoring.assess_record; this module never re-implements a scoring rule.
"""

import csv
import io
from dataclasses import dataclass, field

from scoring import assess_record
from scoring.pipeline import CRITERIA
from scoring.rules import EXCLUDED_INPUT_COLUMNS, MAX_POINTS

from .csv_safety import safe_csv_bytes

# Without these, a whole ICP criterion would silently score as "unknown" for every row.
REQUIRED_COLUMNS = [
    "company_id", "company_name", "description",
    "employee_count_source_a", "employee_count_source_b",
    "open_sales_roles", "sales_role_titles", "hiring_signal_last_seen",
    "outbound_evidence_level",
]
OPTIONAL_COLUMNS = {
    "is_synthetic": "Records cannot be identified as synthetic or genuine; all are treated as UNVERIFIED.",
    "hiring_role_notes": "Solutions Consultant roles cannot be confirmed as sales roles.",
    "campaign_trigger": "No documented campaign triggers; only current hiring can act as a trigger.",
    "campaign_trigger_date": "Documented campaign triggers cannot be dated, so none count as current.",
    "contact_first_name": "Contact names are unavailable.",
    "contact_last_name": "Contact names are unavailable.",
    "contact_title": "Every contact will be flagged PERSONA_MISMATCH.",
    "contact_email": "Every contact will be Not Ready (EMAIL_MISSING).",
    "email_verification_status": "Every email will be treated as unverified.",
    "domain": "Shown for reference only; not used in scoring.",
    "industry": "Shown for reference only; not used in scoring.",
    "hq_country": "Shown for reference only; not used in scoring.",
    "outbound_evidence_notes": "Shown for reference only; not used in scoring.",
}
# Recognised but not warned about when absent: used only by the Sequence Builder export (blank if missing).
SUPPLEMENTARY_COLUMNS = {"contact_linkedin_url"}
KNOWN_COLUMNS = set(REQUIRED_COLUMNS) | set(OPTIONAL_COLUMNS) | SUPPLEMENTARY_COLUMNS | EXCLUDED_INPUT_COLUMNS

ICP_OUTCOMES = ["Qualified", "Review", "Disqualified"]
CONTACT_OUTCOMES = ["Ready", "Needs Attention", "Not Ready"]
CAMPAIGN_OUTCOMES = ["Ready to Sequence", "Hold: Trigger Research", "Hold: Contact", "Hold: ICP Review", "Excluded"]

SYNTHETIC = "SYNTHETIC TEST DATA"
UNVERIFIED = "UNVERIFIED"
MARKED_REAL = "Marked not synthetic"

FILENAME_SYNTHETIC = "scored_companies_SYNTHETIC_TEST_DATA.csv"
FILENAME_UNVERIFIED = "scored_companies_UNVERIFIED.csv"
FILENAME_DEFAULT = "scored_companies.csv"

MAX_REPORTED_ERRORS = 10


@dataclass
class ParsedUpload:
    header: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)


@dataclass
class ColumnCheck:
    missing_required: list
    missing_optional: dict
    unrecognised: list


def parse_csv_bytes(data):
    """Parse an uploaded file. Any error means the file must not be scored."""
    parsed = ParsedUpload()
    if not data or not data.strip():
        parsed.errors.append("The file is empty.")
        return parsed
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        parsed.errors.append("The file is not UTF-8 text. Save it as 'CSV UTF-8' and upload it again.")
        return parsed
    if "\x00" in text:
        parsed.errors.append("The file contains binary data and does not look like a CSV file.")
        return parsed

    try:
        reader = csv.reader(io.StringIO(text, newline=""))
        lines = [(reader.line_num, record) for record in reader if any(cell.strip() for cell in record)]
    except csv.Error as exc:
        parsed.errors.append(f"The file could not be read as CSV: {exc}.")
        return parsed
    if not lines:
        parsed.errors.append("The file has no header row.")
        return parsed

    header = [name.strip() for name in lines[0][1]]
    parsed.header = header
    if any(not name for name in header):
        parsed.errors.append("The header row has blank column names.")
    duplicates = sorted({name for name in header if name and header.count(name) > 1})
    if duplicates:
        parsed.errors.append(f"The header repeats column names: {', '.join(duplicates)}.")
    if len(lines) == 1:
        parsed.errors.append("The file has a header row but no data rows.")

    bad_lines = [(line, len(record)) for line, record in lines[1:] if len(record) != len(header)]
    for line, count in bad_lines[:MAX_REPORTED_ERRORS]:
        parsed.errors.append(f"Line {line} has {count} fields; the header has {len(header)}.")
    if len(bad_lines) > MAX_REPORTED_ERRORS:
        parsed.errors.append(f"... and {len(bad_lines) - MAX_REPORTED_ERRORS} more malformed lines.")

    if not parsed.errors:
        parsed.rows = [dict(zip(header, record)) for _, record in lines[1:]]
    return parsed


def check_columns(header):
    present = set(header)
    return ColumnCheck(
        missing_required=[name for name in REQUIRED_COLUMNS if name not in present],
        missing_optional={name: why for name, why in OPTIONAL_COLUMNS.items() if name not in present},
        unrecognised=[name for name in header if name not in KNOWN_COLUMNS],
    )


def row_warnings(rows):
    """Data problems that do not stop scoring but deserve a visible warning."""
    warnings = []
    ids = [row.get("company_id", "").strip() for row in rows]
    blank = sum(1 for cid in ids if not cid)
    if blank:
        warnings.append(f"{blank} row(s) have no company_id.")
    duplicates = sorted({cid for cid in ids if cid and ids.count(cid) > 1})
    if duplicates:
        warnings.append(f"Duplicate company_id values: {', '.join(duplicates)}.")
    return warnings


def data_status(row):
    """Safety label for a record. Anything not explicitly marked is unverified, never genuine."""
    value = (row.get("is_synthetic") or "").strip().lower()
    if value == "true":
        return SYNTHETIC
    if value == "false":
        return MARKED_REAL
    return UNVERIFIED


def score_rows(rows, as_of):
    """Run the existing engine on each row and attach the data-status label."""
    results = []
    for row in rows:
        result = assess_record(row, as_of)
        results.append({"data_status": data_status(row), **result})
    return results


def count_by(results, field_name, outcomes):
    counts = {outcome: 0 for outcome in outcomes}
    for result in results:
        counts[result[field_name]] = counts.get(result[field_name], 0) + 1
    return counts


def all_flags(results):
    flags = set()
    for result in results:
        for column in ("icp_flags", "contact_flags"):
            flags.update(flag for flag in result[column].split("|") if flag)
    return sorted(flags)


def filter_results(results, search="", icp=None, campaign=None, contact=None, flags=None, data_statuses=None):
    """Empty filter lists mean 'no filter'. Flags match if a record has any selected flag."""
    needle = search.strip().lower()
    selected = []
    for result in results:
        if needle and needle not in result["company_id"].lower() and needle not in result["company_name"].lower():
            continue
        if icp and result["icp_outcome"] not in icp:
            continue
        if campaign and result["campaign_readiness"] not in campaign:
            continue
        if contact and result["contact_readiness"] not in contact:
            continue
        if data_statuses and result["data_status"] not in data_statuses:
            continue
        if flags:
            record_flags = set(result["icp_flags"].split("|")) | set(result["contact_flags"].split("|"))
            if not record_flags.intersection(flags):
                continue
        selected.append(result)
    return selected


def criterion_breakdown(result):
    labels = {"saas_fit": "B2B SaaS fit", "size": "Employee count", "sales_function": "Sales function",
              "hiring": "Relevant sales hiring", "outbound": "Outbound confidence"}
    return [{
        "Criterion": labels[name],
        "Status": result[f"{name}_status"],
        "Confirmed points": result[f"{name}_points"],
        "Unresolved (potential)": result[f"{name}_potential"],
        "Max": MAX_POINTS[name],
    } for name in CRITERIA]


def campaign_display(result):
    """Campaign readiness for display; a 'ready' record is never shown as a real prospect unless marked so."""
    readiness = result["campaign_readiness"]
    if readiness == "Ready to Sequence" and result["data_status"] == SYNTHETIC:
        return f"{readiness} (test data — not a real prospect)"
    if readiness == "Ready to Sequence" and result["data_status"] == UNVERIFIED:
        return f"{readiness} (unverified data — not a confirmed prospect)"
    return readiness


def download_filename(results):
    statuses = {result["data_status"] for result in results}
    if SYNTHETIC in statuses:
        return FILENAME_SYNTHETIC
    if UNVERIFIED in statuses:
        return FILENAME_UNVERIFIED
    return FILENAME_DEFAULT


def results_to_csv_bytes(results):
    """Assessment report: engine columns plus data_status. is_synthetic is preserved as-is.

    Text cells are neutralised against spreadsheet formula injection (see ui/csv_safety.py).
    """
    return safe_csv_bytes(results, list(results[0]))
