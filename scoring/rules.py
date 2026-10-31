"""Thresholds and keyword lists from docs/scoring_specification.md (approved v3.1).

Everything the scoring rules depend on lives here so a rule change is a
reviewable edit to one file.
"""

ICP_MIN_EMPLOYEES = 50
ICP_MAX_EMPLOYEES = 500
RECENCY_DAYS = 90

QUALIFIED_MIN = 70
REVIEW_MIN = 40

MAX_POINTS = {
    "saas_fit": 30,
    "size": 20,
    "sales_function": 20,
    "hiring": 20,
    "outbound": 10,
}

OUTBOUND_POINTS = {"strong": 10, "moderate": 7, "weak": 3, "none": 0}

# A.3 B2B SaaS fit
SOFTWARE_TERMS = ["software", "platform", "saas", "cloud", "automation", "engine",
                  "crm", "erp", "system", "builder"]
BUSINESS_CUSTOMER_TERMS = ["teams", "companies", "employers", "businesses", "clinics", "insurers",
                           "schools", "fleets", "manufacturers", "developers", "forwarders", "industries"]
NON_SAAS_TERMS = ["services company", "agency", "consulting services", "repair", "on-site",
                  "consumers", "shoppers"]

# A.5 Sales function: the phrase must describe the company's own team.
OWN_SALES_PHRASES = ["direct sales team", "inside sales team", "enterprise sales team",
                     "its sales team", "its own sales team", "our sales team"]
NO_SALES_PHRASES = ["no sales team", "without a sales team", "self-serve only"]

# A.6 Hiring
RELEVANT_ROLE_PATTERNS = [
    r"\bsdr\b",
    r"\bsales development representative\b",
    r"\bbdr\b",
    r"\bbusiness development representative\b",
    r"\baccount executive\b",
    r"\bsales engineer\b",
    r"\bsales development manager\b",
]
SOLUTIONS_CONSULTANT_PATTERN = r"\bsolutions consultant\b"
SALES_RESPONSIBILITY_TERMS = ["pipeline", "prospecting", "quota", "new business", "new-business",
                              "revenue target"]

# B. Contact persona
TARGET_PERSONA_TERMS = ["sales", "revenue", "cro", "business development", "growth",
                        "sales development", "founder", "co-founder", "ceo"]

BLOCKING_FLAGS = {"SIZE_CONFLICT", "SIZE_SINGLE_SOURCE", "SIZE_UNKNOWN",
                  "SAAS_FIT_UNCLEAR", "SAAS_FIT_UNKNOWN"}

# Never used as a scoring input; dropped before assessment.
EXCLUDED_INPUT_COLUMNS = {"test_scenario"}
