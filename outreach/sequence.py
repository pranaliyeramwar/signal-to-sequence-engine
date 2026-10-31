"""Sequence Builder workflow: drafts, approval, filters and the two CSV exports.

Reads assessment results produced by the scoring engine; never scores anything itself.
Every live sequencing export passes through scoring.sequencing_export(), the fail-closed guard.
"""

import re
from dataclasses import dataclass, field

from scoring import SyntheticDataError, sequencing_export
from scoring.pipeline import is_explicitly_not_synthetic
from ui.csv_safety import safe_csv_bytes
from ui.helpers import MARKED_REAL, SYNTHETIC

from .first_touch import (BODY_MAX_WORDS, BODY_MIN_WORDS, RESEARCH_NOTE, find_placeholders, generate,
                          word_count)

NEEDS_RESEARCH = "Needs Research"
DRAFT = "Draft"
NEEDS_REVIEW = "Needs Review"
APPROVED = "Approved"
DRAFT_STATUSES = [NEEDS_RESEARCH, DRAFT, NEEDS_REVIEW, APPROVED]

BUILDER_OUTCOMES = ("Qualified",)
REVIEW_OUTCOME = "Review"

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

SEQUENCING_COLUMNS = ["company_name", "contact_name", "job_title", "email", "subject", "email_body",
                      "linkedin_url", "icp_score", "hiring_signal", "campaign_trigger", "personalization_reason"]
REVIEW_LABEL = "REVIEW ONLY - NOT A SEQUENCING IMPORT"
REVIEW_COLUMNS = ["review_only", "data_status", "company_id", "company_name", "contact_name", "contact_title",
                  "contact_email", "icp_score", "icp_outcome", "contact_readiness", "campaign_readiness",
                  "draft_status", "subject", "full_email", "body_word_count", "personalization_reason",
                  "sender_settings_outdated", "approval_blockers", "eligible_for_sequencing", "eligibility_reasons"]
REVIEW_FILENAME_SYNTHETIC = "sequence_drafts_REVIEW_ONLY_SYNTHETIC_TEST_DATA.csv"
REVIEW_FILENAME_UNVERIFIED = "sequence_drafts_REVIEW_ONLY_UNVERIFIED.csv"
REVIEW_FILENAME = "sequence_drafts_REVIEW_ONLY.csv"


@dataclass(frozen=True)
class Record:
    key: str
    row: dict
    result: dict


@dataclass
class Draft:
    key: str
    subject: str
    greeting: str
    body: str
    signature: str
    personalization_reason: str
    evidence: tuple
    status: str
    sender_used: object
    touched: bool = False      # edited, or status set by a person; never regenerated automatically

    @property
    def body_words(self):
        return word_count(self.body)

    def full_email(self):
        return f"{self.greeting}\n\n{self.body}\n\n{self.signature}"


@dataclass
class ExportResult:
    rows: list = field(default_factory=list)
    blocked: list = field(default_factory=list)     # (Record, [reasons])
    guard_error: str = ""


def make_records(rows, results):
    """Pair each input row with its engine result. The key is unique even if company_id repeats."""
    return [Record(f"{index}:{result.get('company_id', '')}", row, result)
            for index, (row, result) in enumerate(zip(rows, results))]


def builder_records(records, include_review=False):
    """Qualified records, plus Review records when asked. Disqualified never enter the workflow."""
    allowed = set(BUILDER_OUTCOMES) | ({REVIEW_OUTCOME} if include_review else set())
    return [record for record in records if record.result.get("icp_outcome") in allowed]


# ---- Drafts ---------------------------------------------------------------------------------

def new_draft(record, sender, as_of):
    generated = generate(record.row, record.result, sender, as_of)
    return Draft(record.key, generated.subject, generated.greeting, generated.body, generated.signature,
                 generated.personalization_reason, generated.evidence,
                 NEEDS_RESEARCH if generated.needs_research else DRAFT, sender.normalised())


def ensure_drafts(drafts, records, sender, as_of):
    """Create drafts for every Qualified and Review record that has none yet."""
    for record in builder_records(records, include_review=True):
        if record.key not in drafts:
            drafts[record.key] = new_draft(record, sender, as_of)
    return drafts


def edit_draft(draft, subject=None, body=None, personalization_reason=None):
    """Apply an edit. Changing an Approved draft sends it back to Needs Review. Returns True if changed."""
    changes = {name: value for name, value in
               (("subject", subject), ("body", body), ("personalization_reason", personalization_reason))
               if value is not None and value != getattr(draft, name)}
    if not changes:
        return False
    for name, value in changes.items():
        setattr(draft, name, value)
    draft.touched = True
    if draft.status == APPROVED:
        draft.status = NEEDS_REVIEW
    return True


def mark_needs_review(draft):
    draft.status = NEEDS_REVIEW
    draft.touched = True


def reset_draft(record, sender, as_of):
    """Discard edits and status; regenerate from evidence and the current sender settings."""
    return new_draft(record, sender, as_of)


def apply_sender_settings(drafts, records, sender, as_of):
    """Regenerate untouched drafts with new sender settings; keep touched drafts and report them as outdated.

    Returns (regenerated_keys, outdated_keys). Edited or human-reviewed drafts are never overwritten.
    """
    sender = sender.normalised()
    by_key = {record.key: record for record in records}
    regenerated, outdated = [], []
    for key, draft in list(drafts.items()):
        if draft.sender_used == sender or key not in by_key:
            continue
        if draft.touched:
            outdated.append(key)
        else:
            drafts[key] = new_draft(by_key[key], sender, as_of)
            regenerated.append(key)
    return regenerated, outdated


def sender_outdated(draft, sender):
    return draft.sender_used != sender.normalised()


# ---- Approval -------------------------------------------------------------------------------

def approval_checks(draft, record):
    """The eight approval conditions as (label, passed, explanation)."""
    result, row = record.result, record.row
    words = draft.body_words
    placeholders = sorted(set(find_placeholders(draft.subject) + find_placeholders(draft.greeting)
                              + find_placeholders(draft.body) + find_placeholders(draft.signature)))
    return [
        ("ICP outcome is Qualified", result.get("icp_outcome") == "Qualified",
         f"ICP outcome is {result.get('icp_outcome') or 'missing'}; only Qualified records can be approved."),
        ("Contact readiness is Ready", result.get("contact_readiness") == "Ready",
         f"Contact readiness is {result.get('contact_readiness') or 'missing'}; it must be Ready."),
        ("Subject is not empty", bool(draft.subject.strip()), "Subject is empty."),
        (f"Body is {BODY_MIN_WORDS}-{BODY_MAX_WORDS} words", BODY_MIN_WORDS <= words <= BODY_MAX_WORDS,
         f"Body has {words} words; it must have {BODY_MIN_WORDS}-{BODY_MAX_WORDS} "
         "(greeting and signature are not counted)."),
        ("No placeholders remain", not placeholders,
         "Replace placeholders: " + ", ".join(placeholders) + "." if placeholders else ""),
        ("Contact first name is available", bool((row.get("contact_first_name") or "").strip()),
         "Contact first name is missing."),
        ("Personalization reason is present", bool(draft.personalization_reason.strip()),
         "Personalization reason is empty."),
        ("Evidence is current and documented", bool(draft.evidence),
         "No current, dated evidence from the input data. " + RESEARCH_NOTE),
    ]


def approval_problems(draft, record):
    return [explanation for _, passed, explanation in approval_checks(draft, record) if not passed]


def approve(draft, record):
    """Human approval. Returns the blocking problems; the status changes only when there are none."""
    problems = approval_problems(draft, record)
    if not problems:
        draft.status = APPROVED
        draft.touched = True
    return problems


# ---- Filtering ------------------------------------------------------------------------------

def filter_builder(records, drafts, search="", icp=None, contact=None, campaign=None, draft_status=None):
    needle = search.strip().lower()
    selected = []
    for record in records:
        result, draft = record.result, drafts.get(record.key)
        contact_name = f"{record.row.get('contact_first_name', '')} {record.row.get('contact_last_name', '')}"
        if needle and not any(needle in value.lower() for value in
                              (result.get("company_id", ""), result.get("company_name", ""), contact_name)):
            continue
        if icp and result.get("icp_outcome") not in icp:
            continue
        if contact and result.get("contact_readiness") not in contact:
            continue
        if campaign and result.get("campaign_readiness") not in campaign:
            continue
        if draft_status and (draft is None or draft.status not in draft_status):
            continue
        selected.append(record)
    return selected


# ---- Live sequencing export -----------------------------------------------------------------

def synthetic_problem(value):
    if is_explicitly_not_synthetic(value):
        return ""
    if isinstance(value, str) and value.strip().lower() == "true":
        return "Synthetic test data (is_synthetic=true)."
    if value is None or (isinstance(value, str) and not value.strip()):
        return "is_synthetic is missing or blank; it must be explicitly false."
    return f"is_synthetic value {value!r} is not recognised; it must be explicitly false."


def live_export_checks(record, draft):
    """The six live-export conditions as (label, passed, explanation). Anything unexpected fails closed."""
    result, row = record.result, record.row
    synthetic = synthetic_problem(row.get("is_synthetic")) or synthetic_problem(result.get("is_synthetic"))
    email = (row.get("contact_email") or "").strip()
    verification = (row.get("email_verification_status") or "").strip().lower()
    if not email:
        email_problem = "Contact email is missing."
    elif not EMAIL_PATTERN.fullmatch(email):
        email_problem = f"Contact email {email!r} is malformed."
    elif verification != "verified":
        email_problem = f"Email verification status is {verification or 'missing'}; it must be verified."
    else:
        email_problem = ""
    if draft is None:
        draft_problem = "No draft exists."
    elif draft.status != APPROVED:
        draft_problem = f"Draft status is {draft.status}; it must be Approved."
    else:
        blockers = approval_problems(draft, record)
        draft_problem = ("Approved draft no longer passes approval checks: " + " ".join(blockers)) if blockers else ""
    return [
        ("is_synthetic is explicitly false", not synthetic, synthetic),
        ("ICP outcome is Qualified", result.get("icp_outcome") == "Qualified",
         f"ICP outcome is {result.get('icp_outcome') or 'missing'}."),
        ("Contact readiness is Ready", result.get("contact_readiness") == "Ready",
         f"Contact readiness is {result.get('contact_readiness') or 'missing'}."),
        ("Campaign readiness is Ready to Sequence", result.get("campaign_readiness") == "Ready to Sequence",
         f"Campaign readiness is {result.get('campaign_readiness') or 'missing'}."),
        ("Draft is Approved", not draft_problem, draft_problem),
        ("Contact email is present and verified", not email_problem, email_problem),
    ]


def live_export_problems(record, draft):
    return [explanation for _, passed, explanation in live_export_checks(record, draft) if not passed]


def evidence_text(draft, kind):
    for evidence in draft.evidence:
        if evidence.kind == kind:
            when = "last seen" if kind == "hiring" else "dated"
            return f"{evidence.summary} ({when} {evidence.date})"
    return ""


def sequencing_row(record, draft):
    row = record.row
    return {
        "company_name": record.result.get("company_name", ""),
        "contact_name": " ".join(part for part in ((row.get("contact_first_name") or "").strip(),
                                                   (row.get("contact_last_name") or "").strip()) if part),
        "job_title": (row.get("contact_title") or "").strip(),
        "email": (row.get("contact_email") or "").strip(),
        "subject": draft.subject.strip(),
        "email_body": draft.full_email(),
        "linkedin_url": (row.get("contact_linkedin_url") or "").strip(),   # supplied value only, never built
        "icp_score": record.result.get("icp_score", ""),
        "hiring_signal": evidence_text(draft, "hiring"),
        "campaign_trigger": evidence_text(draft, "trigger"),
        "personalization_reason": draft.personalization_reason.strip(),
    }


def guarded_rows(candidates, drafts):
    """Pass candidates through the existing fail-closed guard. Any refusal exports nothing."""
    if not candidates:
        return [], ""
    try:
        allowed = sequencing_export([record.result for record in candidates])
    except SyntheticDataError as exc:
        return [], str(exc)
    allowed_ids = {id(result) for result in allowed}
    return [sequencing_row(record, drafts[record.key]) for record in candidates
            if id(record.result) in allowed_ids], ""


def build_sequencing_export(records, drafts, selected_keys):
    export = ExportResult()
    eligible = []
    for record in records:
        if record.key not in selected_keys:
            continue
        problems = live_export_problems(record, drafts.get(record.key))
        if problems:
            export.blocked.append((record, problems))
        else:
            eligible.append(record)
    export.rows, export.guard_error = guarded_rows(eligible, drafts)
    if export.guard_error:
        export.blocked.extend((record, [f"Blocked by the fail-closed export guard: {export.guard_error}"])
                              for record in eligible)
    return export


# ---- Draft Review export --------------------------------------------------------------------

def review_rows(records, drafts, selected_keys, sender):
    rows = []
    for record in records:
        if record.key not in selected_keys:
            continue
        result, row, draft = record.result, record.row, drafts.get(record.key)
        live_problems = live_export_problems(record, draft)
        rows.append({
            "review_only": REVIEW_LABEL,
            "data_status": result.get("data_status") or "UNVERIFIED",
            "company_id": result.get("company_id", ""),
            "company_name": result.get("company_name", ""),
            "contact_name": " ".join(part for part in ((row.get("contact_first_name") or "").strip(),
                                                       (row.get("contact_last_name") or "").strip()) if part),
            "contact_title": (row.get("contact_title") or "").strip(),
            "contact_email": (row.get("contact_email") or "").strip(),
            "icp_score": result.get("icp_score", ""),
            "icp_outcome": result.get("icp_outcome", ""),
            "contact_readiness": result.get("contact_readiness", ""),
            "campaign_readiness": result.get("campaign_readiness", ""),
            "draft_status": draft.status if draft else "",
            "subject": draft.subject if draft else "",
            "full_email": draft.full_email() if draft else "",
            "body_word_count": draft.body_words if draft else 0,
            "personalization_reason": draft.personalization_reason if draft else "",
            "sender_settings_outdated": "yes" if draft and sender_outdated(draft, sender) else "no",
            "approval_blockers": " ".join(approval_problems(draft, record)) if draft else "No draft exists.",
            "eligible_for_sequencing": "no" if live_problems else "yes",
            "eligibility_reasons": " ".join(live_problems),
        })
    return rows


def review_filename(rows):
    statuses = {row["data_status"] for row in rows}
    if SYNTHETIC in statuses:
        return REVIEW_FILENAME_SYNTHETIC
    if statuses - {MARKED_REAL}:
        return REVIEW_FILENAME_UNVERIFIED
    return REVIEW_FILENAME


def rows_to_csv_bytes(rows, columns):
    """Both Sequence Builder exports. Text cells are neutralised against spreadsheet formula injection."""
    return safe_csv_bytes(rows, columns)
