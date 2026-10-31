# Data Dictionary: `sample_companies.csv` (v2)

> **Synthetic data only.** Every company, domain, person and email address in this file is made up for development and testing. Domains use the reserved `.example` top-level domain (RFC 2606), so they can't match a real company or receive mail. These records are **not** leads and must never be presented as verified prospects.

The scoring rules that use these columns are defined in [`docs/scoring_specification.md`](../../docs/scoring_specification.md).

The original v1 file is kept at [`backup/sample_companies_v1_original.csv`](backup/sample_companies_v1_original.csv).

## File format

- **Encoding:** UTF-8
- **Delimiter:** comma
- **Header row:** yes
- **Rows:** one per company, with at most one contact per company
- **Missing values:** an empty field. Empty means *unknown or not provided*, never zero, and never "confirmed none" unless a column says so below.
- **Multi-value fields:** pipe-separated (`|`)
- **Dates:** ISO 8601, `YYYY-MM-DD`
- **Booleans:** lowercase `true` / `false`

## Columns

| # | Column | Type | Required | Format / allowed values | Description |
|---|--------|------|----------|-------------------------|-------------|
| 1 | `company_id` | string | yes | `SYN-NNN`, unique | Synthetic identifier. |
| 2 | `company_name` | string | yes | Free text | Fictional company name. |
| 3 | `domain` | string | yes | Lowercase hostname ending in `.example` | Fictional website domain. |
| 4 | `industry` | string | yes | Free text | Category label. Shown in reasons, but **earns no points** on its own. |
| 5 | `hq_country` | string | yes | ISO 3166-1 alpha-2 | Headquarters country. |
| 6 | `description` | string | no | Free text | Product description. Used for **B2B SaaS fit** and **sales function evidence**. Empty means both are unknown. |
| 7 | `employee_count_source_a` | integer | no | Non-negative integer | Headcount from illustrative Source A. |
| 8 | `employee_count_source_b` | integer | no | Non-negative integer | Headcount from illustrative Source B. It may disagree with Source A. |
| 9 | `open_sales_roles` | integer | no | Non-negative integer, or empty | **Empty** means hiring was not researched. **`0`** means researched, with no open sales roles. **`> 0`** means researched, and the titles decide whether a role is relevant. |
| 10 | `sales_role_titles` | string | no | Pipe-separated titles | Open role titles. Empty with `open_sales_roles > 0` means the titles are missing. |
| 11 | `hiring_role_notes` | string | no | Free text | Job-description excerpt for the open roles. A Solutions Consultant counts as relevant hiring only when this shows pipeline, prospecting or revenue responsibility. |
| 12 | `hiring_signal_last_seen` | date | no | `YYYY-MM-DD` | When the hiring signal was last seen. A signal older than 90 days before the run's `as_of_date` is stale. |
| 13 | `outbound_evidence_level` | enum | yes | `strong` \| `moderate` \| `weak` \| `none` \| `unknown` | How confident we are that the company does outbound prospecting. `unknown` means not researched, which is different from `none`. This is **not** a buying signal. |
| 14 | `outbound_evidence_notes` | string | no | Free text | Supporting note for the outbound level. |
| 15 | `campaign_trigger` | string | no | Free text | A documented reason to reach out now other than hiring, such as a funding round or a new sales leader. Used only for campaign readiness. |
| 16 | `campaign_trigger_date` | date | no | `YYYY-MM-DD` | Date of `campaign_trigger`. The trigger is current when this is no more than 90 days before `as_of_date`. |
| 17 | `contact_first_name` | string | no | Free text | Fictional contact's first name. |
| 18 | `contact_last_name` | string | no | Free text | Fictional contact's last name. |
| 19 | `contact_title` | string | no | Free text | Contact's job title. Checked against the target persona list. |
| 20 | `contact_email` | string | no | `local@domain.example` | Fictional email address. |
| 21 | `email_verification_status` | enum | no | `verified` \| `unverified` \| `catch_all` \| `risky` \| `invalid` | Simulated verification result. Empty when the email is empty. Affects contact readiness only, **never the ICP score**. |
| 22 | `is_synthetic` | boolean | yes | `true` | Always `true` here. Export and sequencing steps must refuse these rows. |
| 23 | `test_scenario` | string | yes | Free text | What the row is designed to test. **Test metadata only. The engine drops this column before any scoring.** |

### Optional upload-only column

This column is **not** in `sample_companies.csv`. It is recognised when present in an uploaded file, and its absence causes no warning.

| Column | Type | Required | Format | Description |
|--------|------|----------|--------|-------------|
| `contact_linkedin_url` | string | no | A profile URL exactly as supplied by your data source | Copied unchanged into the `linkedin_url` column of the Sequence Builder's Sequencing CSV, and blank when missing. Never used in scoring or email drafting. The app never builds, guesses or fills in LinkedIn URLs, and the synthetic sample deliberately has none, because a made-up profile path could match a real person. |

### `email_verification_status` values

| Value | Simulated meaning | Contact readiness effect |
|-------|-------------------|--------------------------|
| `verified` | Mailbox confirmed deliverable | Passes |
| `unverified` | Not yet checked | Needs Attention |
| `catch_all` | Domain accepts all addresses | Needs Attention |
| `risky` | Likely to bounce or be flagged | Not Ready |
| `invalid` | Mailbox does not exist | Not Ready |

## Changes from v1

- **Added columns:** `hiring_role_notes`, `campaign_trigger`, `campaign_trigger_date`.
- **`open_sales_roles`** may now be empty, meaning hiring was not researched.
- **Rows edited** as listed in §E of the scoring specification:
  - Descriptions: SYN-001, 002, 003, 008, 009, 010, 016, 017, 018, 019, 023
  - Hiring fields: SYN-003, 007, 008 (`open_sales_roles` 3 → 2 to match its two titles), 009, 012, 014, 018, 020, 021
  - Outbound: SYN-003 (notes only), 009, 023
  - Email status: SYN-005, 013
  - Industry: SYN-017
  - Trigger: SYN-013
  - All `test_scenario` labels
