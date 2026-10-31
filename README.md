# Signal-to-Sequence Engine

Scores B2B SaaS companies and their contacts, then decides whether each record is ready to enter an outbound sequence.

Each record gets three separate assessments:

| Assessment | Question | Outcomes |
|------------|----------|----------|
| **A. Company ICP qualification** | Does the company fit the ideal customer profile? | Qualified / Review / Disqualified |
| **B. Contact readiness** | Can we reach the right person? | Ready / Needs Attention / Not Ready |
| **C. Campaign readiness** | Should this record be sequenced now? | Ready to Sequence / Hold: Trigger Research / Hold: Contact / Hold: ICP Review / Excluded |

ICP fit is kept separate from buying intent. Email quality never affects the ICP score, and outbound activity never counts as a campaign trigger. The full rules are in [`docs/scoring_specification.md`](docs/scoring_specification.md) (approved v3.1).

> **Synthetic data warning.** The sample dataset is entirely fictional. All of its domains use the reserved `.example` TLD, and every row has `is_synthetic=true`. These records are not leads.

## Sequencing export guard

`scoring.sequencing_export(results)` is the only path from scored results to a real sequence. It **fails closed**: a record passes only when its `is_synthetic` value is the string `false` (case-insensitive, surrounding spaces ignored).

| `is_synthetic` value | Result |
|----------------------|--------|
| `false`, `FALSE`, ` false ` | allowed |
| `true` (any case) | blocked as synthetic |
| missing, blank, whitespace, `None` | blocked as unverified |
| any other value (`yes`, `no`, `0`, `1`, `null`, `n/a`, …) or a non-string such as Python `False` | blocked as unverified |

If **any** record in the batch is blocked, nothing is exported. The function raises `SyntheticDataError`, and the error message lists the synthetic and unverified record IDs separately. When every record passes, it returns only the records whose campaign readiness is **Ready to Sequence**.

## Requirements

- Python 3.10+ (developed and tested on 3.15.1)
- **The engine, CLI and tests:** no third-party packages. Tests use the standard-library `unittest`.
- **The web interface only:** Streamlit, listed in [`requirements.txt`](requirements.txt). Install it into a project virtual environment rather than your global Python (see below).

## Usage

Run all commands from the project root.

```bash
# Score the sample dataset (writes data/output/scored_companies.csv)
python -m scoring --as-of 2026-10-30

# Score another file
python -m scoring --input path/to/companies.csv --output path/to/results.csv

# Validate the dataset and the expected-results fixture (does not use the engine)
python -I scripts/validate_dataset.py

# Run the test suite
python -m unittest discover -s tests -t .
```

`--as-of` sets the reference date for the 90-day recency checks on hiring signals and campaign triggers. It defaults to today. The tests pin it to `2026-10-30`, which is the date the sample data was written for.

## Web interface (Streamlit)

One-time setup, from the project root (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Launch the app:

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

It runs at <http://127.0.0.1:8501>. Stop it with `Ctrl+C`.

**Localhost only.** [`.streamlit/config.toml`](.streamlit/config.toml) sets `server.address = "127.0.0.1"`, so the app listens on this computer's loopback interface and can't be reached from your network. It also turns off Streamlit usage statistics. Streamlit's XSRF and CORS protections stay at their enabled defaults. Streamlit reads this file only when launched **from the project root**. If you launch it from elsewhere, add `--server.address 127.0.0.1`. To confirm the binding, check that the startup message shows a single `http://127.0.0.1:8501` URL and no "Network URL".

The app has two tabs.

**ICP & Account Intelligence**

- upload a company CSV, or load the synthetic sample dataset
- preview the data
- run the scoring engine
- see ICP, campaign and contact metrics
- search and filter the results
- inspect one company's score breakdown, flags and reasons, and its first-touch email preview
- download the scored CSV

**Sequence Builder**

- review, edit and approve first-touch email drafts
- export a Draft Review CSV or an import-ready Sequencing CSV

See [Sequence Builder](#sequence-builder) below.

**Safeguards:**

- **No sending.** The app never sends email, launches campaigns or connects to a sending platform. Its only outputs are CSV downloads.
- **Same engine.** Every result comes from `scoring.assess_record`. The UI adds only a `data_status` label.
- **Upload checks before scoring:**
  - Empty, binary, non-UTF-8 and malformed files are refused, with line numbers for ragged rows.
  - A file missing any required column is refused.
  - Missing optional columns produce a warning that explains the effect on scoring.
- **Data labels.** Every record is marked one of:
  - `SYNTHETIC TEST DATA` (`is_synthetic=true`)
  - `Marked not synthetic` (`is_synthetic=false`)
  - `UNVERIFIED` (column missing, blank or any other value). Unlabelled data is never assumed to be genuine.
- **Display of test data:**
  - Synthetic records sit under a red TEST DATA banner.
  - In the detail panel, a "Ready to Sequence" synthetic record is shown as *"(test data — not a real prospect)"*.
- **Downloads** keep `is_synthetic` and add `data_status`. The filename shows what the file contains:
  - `scored_companies_SYNTHETIC_TEST_DATA.csv` if any record is synthetic
  - `scored_companies_UNVERIFIED.csv` if any record is unverified
  - `scored_companies.csv` otherwise

## Sequence Builder

The second tab turns assessment results into **first-touch email drafts for human review**.

- **Which records appear:**
  - **Qualified** companies are shown by default.
  - **Include Review records** adds Review companies. These can be drafted and edited for research, but never approved or exported.
  - **Disqualified** companies never enter the workflow.
- **Labels in the table:**
  - Synthetic rows carry a 🧪 TEST DATA label.
  - Records that aren't campaign-ready are marked "⚠ … not campaign-ready".

### Sender settings (sidebar)

**Sender name**, **value proposition** and **call to action** are held in the browser session only. They're never written to disk, and refreshing the tab clears them. Until all three are filled in, drafts show `{placeholders}` and can't be approved.

If you change them, drafts nobody has touched are regenerated. Drafts you've edited, approved or marked for review are **never overwritten**; they're kept as they are and flagged *"sender settings outdated"*.

### How drafts are generated ([`outreach/first_touch.py`](outreach/first_touch.py))

Drafts come from deterministic templates. No AI service is called. They use only **current, dated, traceable evidence**:

| Evidence | Requirement | Opener |
|----------|-------------|--------|
| Sales hiring | The engine's `hiring_status` is `current`. The email names only the titles the engine recognises as relevant (`scoring.icp.is_relevant_title`), and the evidence records the `hiring_signal_last_seen` date. | "I noticed {company} is hiring for SDR and Account Executive roles." |
| Documented trigger | `campaign_trigger` text, with a `campaign_trigger_date` within 90 days (the engine's `is_recent` rule) and not in the future. | "I saw {company}'s update from 6 October 2026: Series B funding announced." |

- **Body:** the evidence opener, then your value proposition, then your call to action.
- **Never used:** the description, outbound evidence, or any inferred priorities, pain points or buying intent.
- **No evidence:** the draft is **Needs Research** and no opener is generated.
- **On screen:** each draft shows its evidence (fact, date, days before the as-of date, source fields, why it counts) and a one-line personalization reason.

### Editing and approval

- **Saving edits:** subject, body and personalization reason are editable, and edits are saved for the session. Editing an **Approved** draft sends it back to **Needs Review**.
- **Statuses:** `Needs Research`, `Draft`, `Needs Review`, `Approved`.
- **Approval** is a human click, and is allowed only when **all eight** conditions hold. The app shows each as a ✅/❌ checklist:
  1. ICP outcome is Qualified
  2. Contact readiness is Ready
  3. Subject is not empty
  4. Body is **50–80 words**. The greeting ("Hi {first name},") and the signature are added automatically and not counted.
  5. No placeholders remain (`{…}` or `[…]`)
  6. The contact's first name is available
  7. A personalization reason is present
  8. Current, documented evidence supports the draft
- **Drafts written by hand** for Needs Research records can be prepared but not approved. The evidence has to be added to the input data and the file re-scored first.
- **Copying:** each draft has a copy box containing its subject and full email.

### Exports (selected records)

Select records with the table checkboxes or **Select all shown**. Two downloads are available:

| | A. Draft Review CSV | B. Sequencing CSV |
|---|---|---|
| Purpose | **REVIEW ONLY.** Never an import file. | The only import-ready file, for later manual import into an outbound tool |
| Records | Every selected record, including synthetic and unverified | Only records that meet all six conditions below |
| Labelling | `review_only` column on every row; `data_status`, `draft_status`, `approval_blockers`, `eligibility_reasons`. Column names deliberately differ from the import format, e.g. `contact_email`, not `email`. | `company_name, contact_name, job_title, email, subject, email_body, linkedin_url, icp_score, hiring_signal, campaign_trigger, personalization_reason` |
| Filename | `sequence_drafts_REVIEW_ONLY_SYNTHETIC_TEST_DATA.csv` (any synthetic), `sequence_drafts_REVIEW_ONLY_UNVERIFIED.csv` (any unverified), otherwise `sequence_drafts_REVIEW_ONLY.csv` | `sequencing_import_<as-of date>.csv` |

**A record is included in the Sequencing CSV only if all six of these hold.** Any missing, blank, malformed or ambiguous value fails, and each blocked record is listed with all of its reasons.

1. `is_synthetic` is explicitly `false`, in both the input row and the result
2. ICP outcome is exactly `Qualified`
3. Contact readiness is exactly `Ready`
4. Campaign readiness is exactly `Ready to Sequence`
5. The draft is `Approved` and still passes every approval check
6. The contact email is present, well-formed and `verified`

The eligible records then go through `scoring.sequencing_export()`, the fail-closed guard. If it refuses, nothing is exported.

- **With the synthetic sample**, the Sequencing CSV is always empty and its download button is disabled.
- **`linkedin_url`** is copied from the optional `contact_linkedin_url` input column, exactly as supplied, and is blank when missing. URLs are never built or guessed.

### CSV formula-injection protection

Uploaded data is untrusted. A cell such as `=HYPERLINK(...)` could run as a formula when a CSV file is opened in Excel, LibreOffice or Google Sheets.

**Where it applies:** every CSV file the project writes.

- the CLI output (`python -m scoring` → `data/output/scored_companies.csv`)
- the scored CSV download (Tab 1)
- the Draft Review CSV
- the Sequencing CSV

All four use the same implementation in [`ui/csv_safety.py`](ui/csv_safety.py). The CLI's writer passes each row through `neutralise_row()` and otherwise works exactly as before: same columns and `\r\n` line endings, and output with no dangerous cells is byte-for-byte unchanged.

**What gets neutralized:** a text cell, when either of these is true:

- after skipping leading whitespace and invisible or control characters (such as tab, CR, LF, NUL, non-breaking space, zero-width space and the byte-order mark), its first character is `=`, `+`, `-` or `@`, including the full-width `＝ ＋ － ＠`
- it starts with a tab or carriage return

**How:** the cell gets a single quote (`'`) in front. The original text follows unchanged, so `=1+1` is written as `'=1+1`. Spreadsheets show the quoted value as plain text.

**What's left alone:**

- ordinary text, including text with `=`, `+`, `-` or `@` later in the cell (`SDR - Account Executive`, `a=b`, email addresses)
- numbers
- text that already starts with `'`

**Only at write time.** Scoring results in memory, and the text the app keeps and displays, are never changed. Only the written file is.

- **Side effect:** a legitimate value that starts with one of these characters keeps the leading `'` when it's imported into another tool.

## How scoring works

The ICP score is out of 100 points:

| Criterion | Points |
|-----------|--------|
| B2B SaaS fit (from the description) | 30 |
| Employee count 50–500 inclusive (two sources) | 20 |
| Company's own sales function (from the description) | 20 |
| Relevant sales hiring within 90 days | 20 |
| Outbound prospecting confidence | 10 |

- **`icp_score`** counts **confirmed** evidence only.
- **`potential_score`** adds the points that **unresolved** evidence could earn, such as a missing description, a single employee source or unresearched hiring.

Missing data never counts as negative evidence. It also never counts twice: each criterion contributes either confirmed points or potential points, never both.

The engine classifies each record by applying these rules in order. The first rule that matches decides the outcome.

1. Both employee sources below 50, or both above 500 → **Disqualified**
2. Confirmed non-SaaS → **Disqualified**
3. Score ≥ 70 with no blocking flag → **Qualified**
4. Score ≥ 40 → **Review**
5. Score < 40 but potential ≥ 70 → **Review** (`INSUFFICIENT_DATA`)
6. Otherwise → **Disqualified**

The blocking flags are a size conflict, a single size source, an unknown size, and unclear or unknown SaaS fit.

## Output

`scored_companies.csv` has one row per company, with these columns:

- **Identity:** `company_id`, `company_name`, `is_synthetic`
- **ICP:** `icp_outcome`, `icp_score`, `potential_score`, `size_indication`
- **Per criterion:** `<criterion>_status`, `<criterion>_points` and `<criterion>_potential` for each criterion
- **ICP explanation:** `icp_flags` (pipe-separated) and `icp_reasons` (one sentence per criterion)
- **Contact:** `contact_readiness`, `contact_flags`, `contact_reasons`
- **Campaign:** `campaign_readiness`, `campaign_trigger_status`, `campaign_reasons` (lists every outstanding blocker)

## Project layout

```
data/
  input/
    sample_companies.csv          # 25 synthetic records (v2)
    data_dictionary.md            # column definitions and formats
    backup/                       # original v1 dataset
  output/                         # engine results (generated)
docs/
  scoring_specification.md        # approved scoring rules
scoring/
  rules.py                        # all thresholds and keyword lists
  icp.py                          # A. company ICP qualification
  contact.py                      # B. contact readiness
  campaign.py                     # C. campaign readiness
  pipeline.py                     # load, assess, write, export guard
  __main__.py                     # command-line entry point
scripts/
  validate_dataset.py             # schema and expected-results validation
ui/
  helpers.py                      # upload parsing, column checks, labels, filters (no Streamlit import)
  csv_safety.py                   # formula-injection neutralisation for every CSV file (CLI and app)
outreach/
  first_touch.py                  # deterministic, evidence-based first-touch drafts (no Streamlit import)
  sequence.py                     # drafts, approval, filters, Draft Review and Sequencing CSV exports
streamlit_app.py                  # Streamlit web interface (two tabs)
.streamlit/config.toml            # binds the app to 127.0.0.1; usage statistics off
requirements.txt                  # web interface dependency (Streamlit)
tests/
  fixtures/expected_results.csv   # hand-derived expected outcomes
  test_sample_dataset.py          # all 25 records against the fixture
  test_rules.py                   # rule boundaries and test-only cases
  test_ui_helpers.py              # upload handling, safety labels, filters
  test_export_guard.py            # fail-closed sequencing export guard
  test_first_touch.py             # evidence rules and draft generation
  test_sequence_builder.py        # approval, sender changes, filters, both exports, guard
  test_csv_safety.py              # formula-injection protection; localhost-only server config
.gitignore                        # excludes .venv, caches, secrets and generated output
```

Generated files are not committed: `data/output/` and any `scored_companies*.csv`, `sequence_drafts_*.csv` or `sequencing_import_*.csv` file saved into the project are ignored. The sample input, its backup, the data dictionary and the test fixtures are tracked.

## Changing the rules

1. Update [`docs/scoring_specification.md`](docs/scoring_specification.md) and get the change approved.
2. Edit the thresholds or keyword lists in [`scoring/rules.py`](scoring/rules.py), or the logic in the relevant module.
3. Update [`tests/fixtures/expected_results.csv`](tests/fixtures/expected_results.csv) **by hand from the spec**. Don't regenerate it from engine output.
4. Run the validator and the tests.

The `test_scenario` column in the dataset is test metadata only. The engine drops it before scoring, and a test checks that it never affects any result.
