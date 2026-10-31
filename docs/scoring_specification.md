# Scoring Specification

**Status:** APPROVED v3.1
**Date:** 2026-10-31
**Change from v3:** sources on opposite sides of the range (e.g. 30 / 600) are `SIZE_CONFLICT`, not confirmed out of range. This was open question Q1.

The engine produces three separate assessments for each company record. Each one has its own inputs and outputs:

| Assessment | Question | Outcome values |
|------------|----------|----------------|
| **A. Company ICP qualification** | Does this company fit our ideal customer profile? | Qualified / Review / Disqualified |
| **B. Contact readiness** | Can we reach the right person? | Ready / Needs Attention / Not Ready |
| **C. Campaign readiness** | Should this record enter a sequence now? | Ready to Sequence / Hold: Trigger Research / Hold: Contact / Hold: ICP Review / Excluded |

- **ICP fit is not buying intent.** A lack of buying signals never disqualifies a company in A. Buying triggers are assessed only in C.
- **Email verification** affects B and C only. It never affects the ICP score.
- **`test_scenario`** is removed before any assessment runs. It is used only to label test reports.

---

## A. Company ICP qualification

### A.1 Criteria

| # | Criterion | Max | Inputs |
|---|-----------|-----|--------|
| 1 | B2B SaaS fit | 30 | `description` |
| 2 | Employee count 50–500 inclusive | 20 | `employee_count_source_a`, `employee_count_source_b` |
| 3 | Sales function in company description | 20 | `description` |
| 4 | Relevant sales hiring | 20 | `open_sales_roles`, `sales_role_titles`, `hiring_role_notes`, `hiring_signal_last_seen` |
| 5 | Outbound prospecting confidence | 10 | `outbound_evidence_level` |
|   | **Total** | **100** | |

Each criterion produces a status, `points`, `potential` (unresolved points), flags and a reason sentence.

### A.2 Scores, and the no-double-counting rule

- **`points`** counts **confirmed evidence only**.
- **`potential`** counts **unresolved evidence only**. These are the points the criterion would earn if its open question resolved in the company's favour.

For each criterion, the status sets **exactly one** of three cases:

- confirmed positive: `points = max`, `potential = 0`
- confirmed negative: `points = 0`, `potential = 0`
- unresolved: `points = 0`, `potential = max`

A criterion can never have both `points > 0` and `potential > 0`. Outbound `weak`/`moderate` are confirmed partial values (`potential = 0`).

```
icp_score       = Σ points                     (confirmed only, 0–100)
potential_score = icp_score + Σ potential      (best case if all unresolved items resolve favourably, 0–100)
```

**Invariants** (checked by tests on every record):

- `points_i + potential_i ≤ max_i` for every criterion
- `potential_score ≤ 100`
- each criterion adds to the potential score at most once

A missing description affects criteria 1 and 3. These are two separate criteria with their own maximums, so this is not double counting.

**Provisional size indication (display only):** a single employee-count source is shown as `size_indication = likely_in_range | likely_out_of_range`. It never feeds `icp_score`, `potential_score` or classification.

### A.3 Criterion 1: B2B SaaS fit (30)

The engine judges `description` against configurable keyword lists:

- **Software** indicators: *software, platform, SaaS, cloud, automation, engine, CRM, ERP, system, builder*
- **Business-customer** indicators: *teams, companies, employers, businesses, clinics, insurers, schools, fleets, manufacturers, developers, forwarders, industries*
- **Non-SaaS** indicators: *services company, agency, consulting services, repair, on-site, consumers, shoppers*

| Status | Condition | Points | Potential | Flags |
|--------|-----------|--------|-----------|-------|
| `confirmed` | Software and business-customer indicators, no non-SaaS indicator | 30 | 0 | — |
| `not_saas` | Non-SaaS indicator and **no** software indicator | 0 | 0 | `SAAS_NOT_FIT` → **Disqualified** |
| `unclear` | Description present, anything else (including mixed signals) | 0 | 30 | `SAAS_FIT_UNCLEAR` (blocks Qualified) |
| `unknown` | Description missing | 0 | 30 | `SAAS_FIT_UNKNOWN`, `DESCRIPTION_MISSING` (blocks Qualified) |

A description that is unclear or missing is never treated as non-SaaS.

### A.4 Criterion 2: Employee count (20)

ICP range: **50–500 inclusive**. Only valid non-negative integers count as a source.

| Status | Condition | Points | Potential | Flags | Effect |
|--------|-----------|--------|-----------|-------|--------|
| `confirmed_in_range` | 2 sources, both in range | 20 | 0 | — | — |
| `confirmed_out_of_range` | 2 sources, **both below 50** or **both above 500** | 0 | 0 | `SIZE_OUT_OF_RANGE` | **Disqualified** |
| `conflict` | 2 sources, one in range and one outside, **or** one below 50 and one above 500 | 0 | 20 | `SIZE_CONFLICT` (critical) | Blocks Qualified; normal classification applies, no automatic Disqualify |
| `single_source` | 1 source (in or out of range) | 0 | 20 | `SIZE_SINGLE_SOURCE` | Blocks Qualified |
| `unknown` | No valid source | 0 | 20 | `SIZE_UNKNOWN` | Blocks Qualified |

- **Confirmed out of range** needs both sources to agree on the same side of the range. One source, or two sources that disagree, can never cause a size disqualification.
- **Same-side differences** (e.g. 95/110, 750/1200) are not conflicts.

### A.5 Criterion 3: Sales function in description (20)

Evidence must be about the **company's own** sales function, not its customers'.

- "Sold through a direct sales team" counts.
- "CRM for field sales teams" does not.

| Status | Condition | Points | Potential | Flags |
|--------|-----------|--------|-----------|-------|
| `present` | Own-sales phrase, e.g. *sold through a direct sales team*, *its inside sales team*, *enterprise sales team* | 20 | 0 | — |
| `confirmed_absent` | Explicit absence, e.g. *no sales team*, *self-serve only*, *sold online with no sales team* | 0 | 0 | — |
| `unknown` | Description present but establishes neither | 0 | 20 | `SALES_FUNCTION_UNKNOWN` |
| `unknown` | Description missing | 0 | 20 | `SALES_FUNCTION_UNKNOWN`, `DESCRIPTION_MISSING` |

`SALES_FUNCTION_UNKNOWN` does **not** block Qualified. Most product descriptions never mention a sales team, so blocking on it would hold back almost every record.

### A.6 Criterion 4: Relevant sales hiring (20)

**Relevant titles** (case-insensitive):

- SDR / Sales Development Representative
- BDR / Business Development Representative
- Account Executive, including Enterprise and Mid-Market variants
- Sales Engineer
- Sales Development Manager

**Solutions Consultant** counts only when `hiring_role_notes` shows pipeline, prospecting or revenue responsibility (e.g. *pipeline, prospecting, quota, new business, revenue target*).

**Not relevant:** Customer Success and RevOps titles.

**Recency:** a signal counts as current when it is ≤ 90 days before the run's `as_of_date`, which defaults to today. Tests pin `as_of_date` to 2026-10-30.

**Researched or not** is decided by `open_sales_roles`:

- **Empty**: not researched.
- **`0`**: researched, and there are no open sales roles.
- **`> 0`**: researched, and the titles decide relevance.

| Status | Condition | Points | Potential | Flags |
|--------|-----------|--------|-----------|-------|
| `current` | ≥1 relevant title, signal ≤90 days old | 20 | 0 | — |
| `stale` | ≥1 relevant title, signal >90 days old | 0 | 20 | `HIRING_STALE` |
| `date_missing` | ≥1 relevant title, no signal date | 0 | 20 | `HIRING_DATE_MISSING` |
| `role_unverified` | Only candidate is a Solutions Consultant with empty notes | 0 | 20 | `HIRING_ROLE_UNVERIFIED` |
| `confirmed_none` | `open_sales_roles = 0`; or titles present and none relevant (including a Solutions Consultant whose notes show no sales responsibility) | 0 | 0 | — |
| `titles_missing` | `open_sales_roles > 0`, titles empty | 0 | 20 | `HIRING_TITLES_MISSING` |
| `unknown` | `open_sales_roles` empty | 0 | 20 | `HIRING_UNKNOWN` |

### A.7 Criterion 5: Outbound prospecting confidence (10)

| Value | Points | Potential | Flags |
|-------|--------|-----------|-------|
| `strong` | 10 | 0 | — |
| `moderate` | 7 | 0 | — |
| `weak` | 3 | 0 | — |
| `none` | 0 | 0 | — |
| `unknown` | 0 | 10 | `OUTBOUND_UNKNOWN` |
| empty or invalid | 0 | 10 | `OUTBOUND_UNKNOWN`, `DATA_INVALID_OUTBOUND` |

Outbound confidence describes how the company sells. **It is not a buying signal** and never counts as a campaign trigger.

### A.8 Classification

The engine applies these rules in order. The first rule that matches decides the outcome:

| Step | Rule | Outcome | Reason code |
|------|------|---------|-------------|
| 1 | Size `confirmed_out_of_range` | **Disqualified** | `SIZE_OUT_OF_RANGE` |
| 2 | B2B SaaS fit `not_saas` | **Disqualified** | `SAAS_NOT_FIT` |
| 3 | `icp_score ≥ 70` and no blocking flag | **Qualified** | — |
| 4 | `icp_score ≥ 40` | **Review** | `BLOCKED_FROM_QUALIFIED` if score ≥ 70 |
| 5 | `icp_score < 40` and `potential_score ≥ 70` | **Review** | `INSUFFICIENT_DATA` |
| 6 | Otherwise | **Disqualified** | `LOW_SCORE` |

**Blocking flags:**

- Size: `SIZE_CONFLICT`, `SIZE_SINGLE_SOURCE`, `SIZE_UNKNOWN`
- B2B SaaS fit: `SAAS_FIT_UNCLEAR`, `SAAS_FIT_UNKNOWN`

**Conflicting sizes:**

- If the rest of the evidence reaches 40, the record goes to **Review** (step 4).
- If it scores below 40, it goes to **Review** only when resolving everything could still reach 70 (step 5). Otherwise it stays **Disqualified** (step 6).

**Why the rescue uses 70:** step 5 rescues a record only when it could actually qualify in the best case. Missing data never disqualifies a record that could still qualify.

### A.9 Outputs

- Scores and outcome: `icp_score`, `potential_score`, `icp_outcome`
- Size display: `size_indication`
- Per criterion: `<criterion>_status`, `<criterion>_points`, `<criterion>_potential`
- `icp_flags`, `icp_reasons`

---

## B. Contact readiness

Contact readiness is independent of A.

**Target persona:** the title contains *Sales, Revenue, CRO, Business Development, Growth, Sales Development, Founder, Co-founder* or *CEO*.

| Check | Result | Flag |
|-------|--------|------|
| No contact name and no email | Not Ready | `CONTACT_MISSING` |
| Email missing | Not Ready | `EMAIL_MISSING` |
| `invalid` | Not Ready | `EMAIL_INVALID` |
| `risky` | Not Ready | `EMAIL_RISKY` |
| `catch_all` | Needs Attention | `EMAIL_CATCH_ALL` |
| `unverified`, or status empty with email present | Needs Attention | `EMAIL_UNVERIFIED` |
| Title missing or not a target persona | Needs Attention | `PERSONA_MISMATCH` |
| `verified` and target persona | Ready | — |

The final outcome is the worst result across all checks: Not Ready, then Needs Attention, then Ready.

**Outputs:** `contact_readiness`, `contact_flags`, `contact_reasons`.

---

## C. Campaign readiness

Campaign readiness combines A and B with a trigger check. It never changes A or B.

**Campaign trigger:** a documented, current reason to reach out now. The record has a current trigger when either of these is true:

- **Relevant hiring is current.** The hiring status from A.6 is `current`.
- **Another documented trigger is current.** `campaign_trigger` is filled in and `campaign_trigger_date` is ≤ 90 days before `as_of_date`. Examples: a funding round, a new sales leader, or entering a new market.

Outbound confidence, firmographic fit and contact quality are **never** triggers.

Relevant hiring is used twice: as a scoring criterion in A, and as a trigger in C. Those are separate questions — "is this a fit company?" and "is now the time?" — so using it in both places is not double counting.

| Step | Rule | Campaign readiness |
|------|------|--------------------|
| 1 | ICP Disqualified | **Excluded** |
| 2 | ICP Review | **Hold: ICP Review** |
| 3 | ICP Qualified, contact not Ready | **Hold: Contact** |
| 4 | ICP Qualified, contact Ready, no current trigger | **Hold: Trigger Research** |
| 5 | ICP Qualified, contact Ready, current trigger | **Ready to Sequence** |

The outcome shows the first blocker. `campaign_reasons` lists every outstanding blocker, so a record held for its contact also shows that it lacks a trigger.

**Synthetic data guard:**

- Every output row carries `is_synthetic`.
- Campaign readiness is calculated as normal, so tests can exercise every path.
- Any export or sequencing step refuses rows where `is_synthetic = true`.

**Outputs:** `campaign_readiness`, `campaign_trigger_status` (`hiring` | `documented` | `none` | `stale`), `campaign_reasons`.

---

## D. Dataset changes required

The current `sample_companies.csv` cannot test several of these rules. The proposed changes:

- **New columns:**
  - `hiring_role_notes`: free text, responsibilities of the open roles
  - `campaign_trigger`: free text
  - `campaign_trigger_date`: `YYYY-MM-DD`
- **Description edits** so that the B2B SaaS and sales-function rules have clear positive, negative and unknown cases.
- **Row edits**, listed in the "Proposed change" column of §E.

The dataset stays at 25 rows. `data_dictionary.md` will be updated to match.

---

## E. Test plan: the 25 sample records

All results assume `as_of_date = 2026-10-30` and the proposed changes.

**How to read the table:**

- The Score column shows confirmed / potential.
- Points are listed in the order fit / size / sales function / hiring / outbound.
- "u" means unresolved: the criterion adds its full value to the potential score.

| ID | Proposed change | Points (fit/size/sales/hire/out) | Score | A. ICP | B. Contact | C. Campaign | Rules tested |
|----|-----------------|----------------------------------|-------|--------|------------|-------------|--------------|
| 001 | Desc adds "Sold through a direct sales team." | 30/20/20/20/10 | 100 / 100 | Qualified | Ready | **Ready to Sequence** | Full-confirmation path; hiring as trigger |
| 002 | Desc adds "Sold by its inside sales team." | 30/u/20/20/7 | 77 / 97 | Review | Ready | Hold: ICP Review | Single in-range source scores 0 confirmed; blocked at ≥70 |
| 003 | Desc → "Shipment visibility software for freight forwarders."; only role Solutions Consultant, notes "post-sale implementation" | 30/20/u/0/10 | 60 / 80 | Review | Needs Attention | Hold: ICP Review | Same-side difference 95/110 is not a conflict; Solutions Consultant without sales duties = `confirmed_none`; catch_all |
| 004 | — | — | 0 / — | Disqualified | Ready | Excluded | Both sources below 50 → hard disqualify; contact quality is irrelevant |
| 005 | Email status → `risky` | — | — | Disqualified | Not Ready | Excluded | Both below 50; `risky` email |
| 006 | — | 30/0/u/20/10 | 60 / — | Disqualified | Ready | Excluded | Both above 500 → disqualified despite strong signals |
| 007 | Hiring date removed | 30/0/u/u/7 | — | Disqualified | Ready | Excluded | Same-side difference 750/1200 still confirms out of range; `date_missing` |
| 008 | Desc adds "software" | 30/u/u/20/10 | 60 / 100 | Review | Ready | Hold: ICP Review | Conflict 45/210 across the lower boundary; "Head of Growth" persona |
| 009 | Desc → self-serve, "no sales team"; hiring 0; outbound `weak` | 30/u/0/0/3 | 33 / 53 | Disqualified | Ready | Excluded | Conflict 480/620 with weak other evidence stays Disqualified; `confirmed_absent` sales function |
| 010 | Desc adds "Sold through a direct sales team." | 30/u/20/20/7 | 77 / 97 | Review | Ready | Hold: ICP Review | Unknown size blocks Qualified at ≥70 |
| 011 | — | u/20/u/20/10 | 50 / 100 | Review | Ready | Hold: ICP Review | Missing desc → fit and sales function unknown, not negative |
| 012 | Hiring → 1 Solutions Consultant, empty notes | 30/20/u/u/10 | 60 / 100 | Review | Ready | Hold: ICP Review | "for field sales teams" is not own-sales evidence; `role_unverified` |
| 013 | Desc adds "Sold through an enterprise sales team."; email → `verified`; trigger "Series B funding announced", 2026-10-06 | 30/20/20/u/7 | 77 / 97 | Qualified | Ready | **Ready to Sequence** | Stale hiring (2026-03-10) gives 0 points but doesn't block; documented trigger |
| 014 | `open_sales_roles` → empty | 30/20/u/u/0 | 50 / 90 | Review | Not Ready | Hold: ICP Review | Hiring not researched ≠ no hiring; invalid email plus persona mismatch |
| 015 | — | u/20/u/20/3 | 43 / 93 | Review | Not Ready | Hold: ICP Review | Unclear SaaS fit (no customer term) is unknown, not non-SaaS; missing email |
| 016 | Desc → self-serve, "sold online with no sales team." | 30/20/0/0/0 | 50 / 50 | Review | Needs Attention | Hold: ICP Review | Customer Success role alone = `confirmed_none`; no buying signals ≠ Disqualified (Q4); persona mismatch |
| 017 | Desc → fleet repair services company with a direct sales team; industry → "Fleet Services" | 0/20/20/20/10 | 70 / 70 | Disqualified | Not Ready | Excluded | Confirmed non-SaaS disqualifies even at score 70 |
| 018 | Desc adds customer term and "inside sales team"; only role "Sales Development Manager" | 30/20/20/20/7 | 97 / 97 | Qualified | Ready | **Ready to Sequence** | Sales Development Manager counts on its own |
| 019 | Desc adds "platform" | 30/20/u/20/7 | 77 / 97 | Qualified | Needs Attention | Hold: Contact | 50 employees is in range; unknown sales function doesn't block; unverified email |
| 020 | Only role Solutions Consultant, notes "owns new-business pipeline, quota-carrying" | 30/20/u/20/10 | 80 / 100 | Qualified | Needs Attention | Hold: Contact | 500 employees is in range; Solutions Consultant with sales duties counts; catch_all |
| 021 | `open_sales_roles` → 2, titles empty | u/u/u/u/0 | 0 / 90 | Review | Not Ready | Hold: ICP Review | Single source out of range (8) is not disqualified; `titles_missing`; rescued by potential ≥ 70 |
| 022 | — | u/0/u/0/3 | — | Disqualified | Ready | Excluded | Both above 500; no customer term → unclear fit, but size rule decides |
| 023 | Desc adds "software" and "Sold through an enterprise sales team."; outbound → `strong` | 30/20/20/0/10 | 80 / 80 | Qualified | Ready | **Hold: Trigger Research** | No hiring can still be Qualified; strong outbound is not a trigger |
| 024 | — | u/u/u/20/u | 20 / 100 | Review | Ready | Hold: ICP Review | Single in-range source; outbound `unknown`; rescued by potential |
| 025 | — | 30/u/u/20/10 | 60 / 100 | Review | Ready | Hold: ICP Review | Conflict 900/85 across the upper boundary |

**Expected totals:**

| Assessment | Outcome | Count | Records |
|------------|---------|-------|---------|
| A | Qualified | 6 | 001, 013, 018, 019, 020, 023 |
| A | Review | 12 | 002, 003, 008, 010, 011, 012, 014, 015, 016, 021, 024, 025 |
| A | Disqualified | 7 | 004, 005, 006, 007, 009, 017, 022 |
| C | Ready to Sequence | 3 | 001, 013, 018 |
| C | Hold: Trigger Research | 1 | 023 |
| C | Hold: Contact | 2 | 019, 020 |
| C | Hold: ICP Review | 12 | — |
| C | Excluded | 7 | — |

**Not covered by any outcome-level row:**

- opposite-side size conflict
- unclear SaaS fit at score ≥ 70
- stale documented trigger
- invalid outbound value

These will be covered by small unit-test fixtures inside the test suite, not by the sample CSV.
