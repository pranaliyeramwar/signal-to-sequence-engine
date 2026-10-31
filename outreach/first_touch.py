"""Deterministic, evidence-based first-touch email drafts.

Only current, dated, traceable evidence is used:
  - hiring: the engine's hiring_status must be "current"; only titles the engine recognises as
    relevant are named, with the hiring_signal_last_seen date;
  - documented trigger: campaign_trigger text with a campaign_trigger_date that the engine's own
    recency rule (scoring.icp.is_recent) accepts.

Nothing is inferred: no hiring activity, buying intent, priorities or pain points. Without evidence
the draft is "Needs Research" and no opener is generated.
"""

import re
from dataclasses import dataclass

from scoring.icp import is_recent, is_relevant_title, parse_date
from scoring.rules import SOLUTIONS_CONSULTANT_PATTERN

BODY_MIN_WORDS = 50
BODY_MAX_WORDS = 80

PLACEHOLDER_FIRST_NAME = "{first name}"
PLACEHOLDER_SENDER = "{sender name}"
PLACEHOLDER_VALUE = "{value proposition}"
PLACEHOLDER_CTA = "{call to action}"
PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]*\}|\[[^\[\]]*\]")

RESEARCH_NOTE = ("No current, dated hiring signal or documented campaign trigger. Research the account "
                 "and record evidence in the input data; do not invent an opener.")

# Acronyms whose first letter is pronounced with a vowel sound ("an SDR", "a BDR").
VOWEL_SOUND_LETTERS = set("AEFHILMNORSX")


@dataclass(frozen=True)
class SenderSettings:
    sender_name: str = ""
    value_proposition: str = ""
    call_to_action: str = ""

    def normalised(self):
        return SenderSettings(self.sender_name.strip(), self.value_proposition.strip(), self.call_to_action.strip())

    def is_complete(self):
        settings = self.normalised()
        return all((settings.sender_name, settings.value_proposition, settings.call_to_action))


@dataclass(frozen=True)
class Evidence:
    kind: str            # "hiring" or "trigger"
    summary: str         # the fact used, e.g. "SDR, Account Executive"
    source_fields: tuple
    date: str            # ISO date of the evidence
    age_days: int        # days before the as-of date
    basis: str           # why the evidence counts as current

    def reason(self, as_of):
        label = "Hiring" if self.kind == "hiring" else "Documented trigger"
        when = "last seen" if self.kind == "hiring" else "dated"
        return f"{label}: {self.summary} ({when} {self.date}, {self.age_days} days before {as_of.isoformat()})"


@dataclass(frozen=True)
class GeneratedDraft:
    subject: str
    greeting: str
    body: str
    signature: str
    personalization_reason: str
    evidence: tuple
    needs_research: bool


def word_count(text):
    """Words separated by whitespace. Applied to the body only, never greeting or signature."""
    return len((text or "").split())


def find_placeholders(text):
    return PLACEHOLDER_PATTERN.findall(text or "")


def join_titles(titles):
    return titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + " and " + titles[-1]


def article(phrase):
    first = phrase.split()[0]
    if first.isupper() and len(first) <= 5:
        return "an" if first[0] in VOWEL_SOUND_LETTERS else "a"
    return "an" if first[0].lower() in "aeiou" else "a"


def human_date(value):
    return f"{value.day} {value.strftime('%B')} {value.year}"


def hiring_evidence(row, result, as_of):
    if result.get("hiring_status") != "current":
        return None
    titles = [title.strip() for title in (row.get("sales_role_titles") or "").split("|") if title.strip()]
    relevant = [title for title in titles if is_relevant_title(title)]
    if not relevant:
        # The engine counts a Solutions Consultant only when its notes show sales responsibility.
        relevant = [title for title in titles if re.search(SOLUTIONS_CONSULTANT_PATTERN, title, re.IGNORECASE)]
    signal_date = parse_date(row.get("hiring_signal_last_seen"))
    if not relevant or signal_date is None or signal_date > as_of:
        return None
    return Evidence("hiring", ", ".join(relevant),
                    ("sales_role_titles", "hiring_signal_last_seen", "hiring_status"),
                    signal_date.isoformat(), (as_of - signal_date).days,
                    "Scoring engine hiring_status is 'current' (relevant role seen within 90 days).")


def trigger_evidence(row, as_of):
    trigger = (row.get("campaign_trigger") or "").strip()
    trigger_date = parse_date(row.get("campaign_trigger_date"))
    if not trigger or trigger_date is None or trigger_date > as_of or not is_recent(trigger_date, as_of):
        return None
    return Evidence("trigger", trigger.rstrip("."), ("campaign_trigger", "campaign_trigger_date"),
                    trigger_date.isoformat(), (as_of - trigger_date).days,
                    "campaign_trigger_date is within 90 days of the as-of date (engine recency rule).")


def collect_evidence(row, result, as_of):
    return tuple(evidence for evidence in (hiring_evidence(row, result, as_of), trigger_evidence(row, as_of))
                 if evidence is not None)


def opener_and_subject(company, evidence, row):
    if evidence.kind == "hiring":
        titles = evidence.summary.split(", ")
        if len(titles) == 1:
            opener = f"I noticed {company} has {article(titles[0])} {titles[0]} role open."
        else:
            opener = f"I noticed {company} is hiring for {join_titles(titles)} roles."
        return opener, f"Sales hiring at {company}"
    trigger_date = parse_date(row.get("campaign_trigger_date"))
    return (f"I saw {company}'s update from {human_date(trigger_date)}: {evidence.summary}.",
            f"{company}'s recent update")


def generate(row, result, sender, as_of):
    """Build a draft from current evidence only. Deterministic: same inputs, same draft."""
    sender = sender.normalised()
    first_name = (row.get("contact_first_name") or "").strip()
    greeting = f"Hi {first_name or PLACEHOLDER_FIRST_NAME},"
    signature = f"Best,\n{sender.sender_name or PLACEHOLDER_SENDER}"
    company = (row.get("company_name") or result.get("company_name") or "").strip()

    evidence = collect_evidence(row, result, as_of) if company else ()
    if not evidence:
        return GeneratedDraft("", greeting, "", signature, "", (), needs_research=True)

    opener, subject = opener_and_subject(company, evidence[0], row)
    body = "\n\n".join((opener, sender.value_proposition or PLACEHOLDER_VALUE,
                        sender.call_to_action or PLACEHOLDER_CTA))
    reason = "; ".join(item.reason(as_of) for item in evidence)
    return GeneratedDraft(subject, greeting, body, signature, reason, evidence, needs_research=False)
