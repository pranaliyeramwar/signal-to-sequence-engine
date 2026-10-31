"""A. Company ICP qualification (spec section A)."""

import re
from dataclasses import dataclass, field
from datetime import date

from . import rules


@dataclass
class CriterionResult:
    status: str
    points: int
    potential: int
    reason: str
    flags: list = field(default_factory=list)


@dataclass
class IcpResult:
    criteria: dict
    icp_score: int
    potential_score: int
    outcome: str
    outcome_reason: str
    size_indication: str
    flags: list


def contains_term(text, term):
    """Case-insensitive whole-word/phrase match."""
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE) is not None


def contains_any(text, terms):
    return any(contains_term(text, term) for term in terms)


def parse_count(value):
    value = (value or "").strip()
    return int(value) if re.fullmatch(r"\d+", value) else None


def parse_date(value):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def is_recent(signal_date, as_of):
    return (as_of - signal_date).days <= rules.RECENCY_DAYS


def in_range(count):
    return rules.ICP_MIN_EMPLOYEES <= count <= rules.ICP_MAX_EMPLOYEES


def assess_saas_fit(row):
    maximum = rules.MAX_POINTS["saas_fit"]
    description = (row.get("description") or "").strip()
    if not description:
        return CriterionResult("unknown", 0, maximum, "No description, so B2B SaaS fit is unknown.",
                               ["SAAS_FIT_UNKNOWN", "DESCRIPTION_MISSING"])
    software = contains_any(description, rules.SOFTWARE_TERMS)
    customer = contains_any(description, rules.BUSINESS_CUSTOMER_TERMS)
    non_saas = contains_any(description, rules.NON_SAAS_TERMS)
    if non_saas and not software:
        return CriterionResult("not_saas", 0, 0, "Description describes a non-SaaS business.", ["SAAS_NOT_FIT"])
    if software and customer and not non_saas:
        return CriterionResult("confirmed", maximum, 0, "Description shows B2B software for business customers.")
    return CriterionResult("unclear", 0, maximum, "Description does not clearly establish a B2B SaaS business.",
                           ["SAAS_FIT_UNCLEAR"])


def assess_size(row):
    maximum = rules.MAX_POINTS["size"]
    sources = [parse_count(row.get(column)) for column in ("employee_count_source_a", "employee_count_source_b")]
    counts = [count for count in sources if count is not None]
    shown = " / ".join(str(count) for count in counts)

    if not counts:
        return CriterionResult("unknown", 0, maximum, "No employee count available; size is unknown.",
                               ["SIZE_UNKNOWN"]), ""
    if len(counts) == 1:
        indication = "likely_in_range" if in_range(counts[0]) else "likely_out_of_range"
        return CriterionResult("single_source", 0, maximum,
                               f"Only one employee source ({shown}); size is unresolved.",
                               ["SIZE_SINGLE_SOURCE"]), indication
    if all(in_range(count) for count in counts):
        return CriterionResult("confirmed_in_range", maximum, 0,
                               f"Both employee sources ({shown}) are within 50-500."), ""
    if all(count < rules.ICP_MIN_EMPLOYEES for count in counts) or \
            all(count > rules.ICP_MAX_EMPLOYEES for count in counts):
        return CriterionResult("confirmed_out_of_range", 0, 0,
                               f"Both employee sources ({shown}) are outside 50-500 on the same side.",
                               ["SIZE_OUT_OF_RANGE"]), ""
    return CriterionResult("conflict", 0, maximum,
                           f"Employee sources conflict ({shown}) and do not agree on the ICP range.",
                           ["SIZE_CONFLICT"]), ""


def assess_sales_function(row):
    maximum = rules.MAX_POINTS["sales_function"]
    description = (row.get("description") or "").strip()
    if not description:
        return CriterionResult("unknown", 0, maximum, "No description, so the sales function is unknown.",
                               ["SALES_FUNCTION_UNKNOWN", "DESCRIPTION_MISSING"])
    own_sales = contains_any(description, rules.OWN_SALES_PHRASES)
    no_sales = contains_any(description, rules.NO_SALES_PHRASES)
    if own_sales and not no_sales:
        return CriterionResult("present", maximum, 0, "Description mentions the company's own sales team.")
    if no_sales and not own_sales:
        return CriterionResult("confirmed_absent", 0, 0, "Description states the company has no sales function.")
    return CriterionResult("unknown", 0, maximum, "Description does not establish whether a sales function exists.",
                           ["SALES_FUNCTION_UNKNOWN"])


def is_relevant_title(title):
    return any(re.search(pattern, title, re.IGNORECASE) for pattern in rules.RELEVANT_ROLE_PATTERNS)


def assess_hiring(row, as_of):
    maximum = rules.MAX_POINTS["hiring"]
    roles_value = (row.get("open_sales_roles") or "").strip()
    roles = parse_count(roles_value)
    titles = [title.strip() for title in (row.get("sales_role_titles") or "").split("|") if title.strip()]
    notes = (row.get("hiring_role_notes") or "").strip()

    if roles is None:
        return CriterionResult("unknown", 0, maximum, "Sales hiring has not been researched.", ["HIRING_UNKNOWN"])
    if roles == 0:
        return CriterionResult("confirmed_none", 0, 0, "Researched: no open sales roles.")
    if not titles:
        return CriterionResult("titles_missing", 0, maximum,
                               f"{roles} open sales role(s) reported but titles are missing.",
                               ["HIRING_TITLES_MISSING"])

    relevant = [title for title in titles if is_relevant_title(title)]
    if not relevant:
        consultants = [title for title in titles if re.search(rules.SOLUTIONS_CONSULTANT_PATTERN, title, re.IGNORECASE)]
        if not consultants:
            return CriterionResult("confirmed_none", 0, 0,
                                   f"Open roles ({', '.join(titles)}) are not relevant sales roles.")
        if not notes:
            return CriterionResult("role_unverified", 0, maximum,
                                   "Solutions Consultant role has no notes to confirm sales responsibility.",
                                   ["HIRING_ROLE_UNVERIFIED"])
        if not contains_any(notes, rules.SALES_RESPONSIBILITY_TERMS):
            return CriterionResult("confirmed_none", 0, 0,
                                   "Solutions Consultant notes show no pipeline or revenue responsibility.")
        relevant = consultants

    signal_date = parse_date(row.get("hiring_signal_last_seen"))
    listed = ", ".join(relevant)
    if signal_date is None:
        return CriterionResult("date_missing", 0, maximum, f"Relevant roles ({listed}) have no signal date.",
                               ["HIRING_DATE_MISSING"])
    if not is_recent(signal_date, as_of):
        return CriterionResult("stale", 0, maximum,
                               f"Relevant roles ({listed}) last seen {signal_date.isoformat()}, over 90 days ago.",
                               ["HIRING_STALE"])
    return CriterionResult("current", maximum, 0,
                           f"Relevant roles ({listed}) seen {signal_date.isoformat()}.")


def assess_outbound(row):
    maximum = rules.MAX_POINTS["outbound"]
    level = (row.get("outbound_evidence_level") or "").strip().lower()
    if level in rules.OUTBOUND_POINTS:
        return CriterionResult(level, rules.OUTBOUND_POINTS[level], 0, f"Outbound evidence is {level}.")
    if level == "unknown":
        return CriterionResult("unknown", 0, maximum, "Outbound evidence has not been researched.",
                               ["OUTBOUND_UNKNOWN"])
    return CriterionResult("unknown", 0, maximum, f"Outbound evidence value {level!r} is invalid; treated as unknown.",
                           ["OUTBOUND_UNKNOWN", "DATA_INVALID_OUTBOUND"])


def classify(criteria, icp_score, potential_score, flags):
    """Spec A.8: first matching step wins."""
    if criteria["size"].status == "confirmed_out_of_range":
        return "Disqualified", "SIZE_OUT_OF_RANGE"
    if criteria["saas_fit"].status == "not_saas":
        return "Disqualified", "SAAS_NOT_FIT"
    blocked = bool(rules.BLOCKING_FLAGS.intersection(flags))
    if icp_score >= rules.QUALIFIED_MIN and not blocked:
        return "Qualified", ""
    if icp_score >= rules.REVIEW_MIN:
        return "Review", "BLOCKED_FROM_QUALIFIED" if icp_score >= rules.QUALIFIED_MIN else ""
    if potential_score >= rules.QUALIFIED_MIN:
        return "Review", "INSUFFICIENT_DATA"
    return "Disqualified", "LOW_SCORE"


def assess_icp(row, as_of):
    size, size_indication = assess_size(row)
    criteria = {
        "saas_fit": assess_saas_fit(row),
        "size": size,
        "sales_function": assess_sales_function(row),
        "hiring": assess_hiring(row, as_of),
        "outbound": assess_outbound(row),
    }
    icp_score = sum(result.points for result in criteria.values())
    potential_score = icp_score + sum(result.potential for result in criteria.values())

    flags = []
    for result in criteria.values():
        flags.extend(flag for flag in result.flags if flag not in flags)
    outcome, outcome_reason = classify(criteria, icp_score, potential_score, flags)
    if outcome_reason and outcome_reason not in flags:
        flags.append(outcome_reason)
    return IcpResult(criteria, icp_score, potential_score, outcome, outcome_reason, size_indication, flags)
