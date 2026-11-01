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

- Python 3.11+ for the complete project and test suite (developed and tested on 3.15.1). The tests read `.streamlit/config.toml` with the standard-library `tomllib` module, which was added in Python 3.11.
- **The engine, CLI and tests:** no third-party packages. Tests use the standard-library `unittest`.
- **The web interface only:** Streamlit, Altair and pandas, pinned in [`requirements.txt`](requirements.txt). Install them into a project virtual environment rather than your global Python (see below).

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

**Localhost only (local runs).** [`.streamlit/config.toml`](.streamlit/config.toml) sets `server.address = "127.0.0.1"`, so the app listens on this computer's loopback interface and can't be reached from your network. It also turns off Streamlit usage statistics. Streamlit's XSRF and CORS protections stay at their enabled defaults. Streamlit reads this file only when launched **from the project root**. If you launch it from elsewhere, add `--server.address 127.0.0.1`. To confirm the binding, check that the startup message shows a single `http://127.0.0.1:8501` URL and no "Network URL".

**Sidebar:**

- upload a company CSV, or load the synthetic sample dataset
- set the "Assess as of" reference date
- enter sender settings for the Sequence Builder

The app has three tabs. **Run ICP scoring** sits above the tabs and feeds all three.

**Dashboard**

- a read-only GTM operations view
- KPI cards, distribution charts, an ICP score histogram and a prioritised account table
- see [Dashboard](#dashboard) below

**ICP & Account Intelligence** (account intelligence and scoring results)

- preview the loaded data
- see ICP, campaign and contact counts from the latest scoring run
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

## Dashboard

The first tab summarises the **existing assessment results**. It doesn't score, reclassify or rank anything itself. All of its calculations are in [`ui/dashboard.py`](ui/dashboard.py), which reads the engine's output fields and reuses the same counting helper and outcome lists as the rest of the app.

**Filters:** ICP classification, contact readiness, campaign readiness and an ICP score range. The range includes both ends, and a record without a valid score drops out only when the range is narrowed. The filters sit in one row above everything they apply to, and the KPI cards, charts and table all use the same filtered set. Filtering builds a new list, so it never changes the scored results, the drafts or anything the exports use.

**KPI cards:**

- Total Companies Analysed
- Qualified Accounts
- Accounts Under Review
- Disqualified Accounts
- Contacts Ready
- Campaigns Ready to Sequence (a readiness status, not a launched campaign)

**Charts:** ICP classification, contact readiness and campaign readiness distributions, plus an ICP score histogram in 10-point bins.

- Each chart is a single series in the accent colour.
- Categories stay in the engine's fixed order, including zero counts, so filtering never reorders or recolours them.
- Each bar has its value printed at its tip, a tooltip, and a **View as table** twin. The accent is 2.97:1 against white, so values are never shown by colour alone.
- The histogram marks the engine's Review (40) and Qualified (70) thresholds. Its caption notes that a score of 70+ is Qualified only when no blocking flag applies.

**Prioritised accounts:** ordered by campaign readiness (Ready to Sequence first, Excluded last), then ICP score, then company ID. This only orders the list; it changes no classification.

**Data integrity:**

- Synthetic data is labelled DEMO DATA, and unverified data UNVERIFIED.
- The dashboard shows assessment counts only. There are no revenue, pipeline, conversion, engagement or campaign-performance figures.
- Before scoring, with an empty dataset, or when the filters match nothing, it shows a message instead of empty charts.

### Visual theme

Set in [`.streamlit/config.toml`](.streamlit/config.toml) using Streamlit's built-in theming. The `[server]` and `[browser]` settings are unchanged: localhost only, usage statistics off.

| Role | Colour |
|---|---|
| Primary: buttons, tabs, headings, threshold lines | `#173B4D` deep teal-blue |
| Accent: chart marks, highlights, active indicators | `#19A7A0` aqua teal |
| Page background | `#F5F8FA` |
| Cards, panels, sidebar background, main-area inputs | `#FFFFFF` |
| Sidebar inputs | `#F5F8FA` |
| Text | `#243746` |
| Muted chart axis text | `#64748B` |
| Borders | `#DCE5EA` |

- **Theme scope:** light theme only.
- **Brand styling** lives in [`ui/style.py`](ui/style.py): the palette constants (shared with the charts) and one fixed stylesheet with no user data. It adds:
  - a deep teal-blue header band with an aqua edge
  - uppercase sidebar section headings with aqua rules, and a sidebar border and shadow
  - deep teal-blue headings with an aqua bar on section headings
  - bold active tab text with an aqua underline
  - aqua-tinted filter chips and a hover state on secondary buttons
  - white KPI and chart cards with an aqua top edge (the Ready to Sequence KPI card is aqua-tinted)
  - aqua-tinted Ready to Sequence rows in the prioritised table (applied with a pandas Styler)
- **Selectors:**
  - Mostly Streamlit's documented `st.container(key=…)` classes, plus `data-testid` and ARIA attributes.
  - Two hooks are marked less stable in the stylesheet: the tab underline and the filter chips. If a Streamlit upgrade renames them, those elements fall back to the theme colours.
- **Contrast:** every text colour pair is at least 6.4:1, and tests check that each pair meets WCAG AA (4.5:1). Aqua is used only for non-text accents, and always next to text that carries the same meaning.
- **Status colours:** Streamlit's own success, warning and error colours are left as they are, so status never depends on the brand colours. Every status also carries text and an icon.

## Sequence Builder

The third tab turns assessment results into **first-touch email drafts for human review**.

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

## Deploying to Streamlit Community Cloud

The app can run on Streamlit Community Cloud using only the synthetic sample dataset. It needs no secrets, API keys or external integrations.

**Before deploying:**

- Push the complete project to GitHub, including every module the app imports (`scoring/`, `outreach/`, `ui/`) and `data/input/sample_companies.csv`.
- Generated output and local secrets are excluded by `.gitignore` and aren't needed.

**Deployment settings:**

| Setting | Value |
|---|---|
| Repository and branch | this repository, `main` |
| Main file path | `streamlit_app.py` (at the repository root) |
| Python version (Advanced settings) | **3.12**, the Community Cloud default and the version the pinned dependencies were tested on |
| Secrets (Advanced settings) | leave empty; the app reads none |

Community Cloud installs the pinned packages from `requirements.txt` and runs the app from the repository root, so it reads the same `.streamlit/config.toml` (theme included).

**Dependency verification:**

- The pins (`streamlit==1.66.1`, `altair==6.3.0`, `pandas==3.1.0`) were installed with uv into a clean Python 3.12 environment, and the full test suite and the headless app walkthrough passed there.
- The pins also resolve to prebuilt Linux wheels for Python 3.12, the platform Community Cloud runs on.
- The app itself hasn't yet been tested on Community Cloud.

**Network address:** `.streamlit/config.toml` keeps `server.address = "127.0.0.1"` for local runs, and it must not be removed or changed on `main`.

- Community Cloud reads this file too, and offers no way to override it before the server starts.
- Community Cloud's health check connects to the app at `localhost:8501` inside its container, so the loopback setting may work as it is. That hasn't been confirmed yet.
- If the deploy fails the health check (for example `connection refused` on `/healthz` in the app logs), don't edit the config on `main`. The planned fallback is a separate deploy-only branch whose config leaves out the `address` line. That branch doesn't exist yet and needs its own review, including the tests that check the localhost setting.

**On Community Cloud:**

- **Loading data:** click **Load sample dataset (synthetic)** in the sidebar, then **Run ICP scoring**. Every synthetic record keeps its TEST DATA and DEMO DATA labels, and the Sequencing CSV stays disabled.
- **Uploaded files** are processed on Community Cloud's servers. Don't upload real prospect or personal data to a hosted deployment.
- **Session state:** drafts, approvals and sender settings live in the browser session and are lost when the page is refreshed, the app restarts or the app goes to sleep after a period of inactivity.
- **Visibility:** a deployed app can be opened by anyone with its link unless its sharing settings restrict viewers. Check those settings if the demo shouldn't be public.
- **No sending:** the app still never sends email or contacts any service. Its only outputs are CSV downloads to the viewer's browser.

## Limitations and Scope

- **Rule-based scoring.** Scoring uses deterministic, keyword-based rules (`scoring/rules.py`). It doesn't use a model or AI service, so a description that describes the company in words the keyword lists don't cover can be marked unclear or unknown.
- **Session-only workflow.** Drafts, approvals and sender settings live in the browser session. They're never saved to disk and may be lost when the tab is refreshed or the server restarts. Download a Draft Review CSV to keep a copy.
- **Single user, localhost only.** Locally, the app is configured to listen on `127.0.0.1` only. It has no accounts, sign-in or shared state of its own. A Streamlit Community Cloud deployment is the one supported hosted option, and its access is controlled by Community Cloud's sharing settings, not by the app (see [Deploying to Streamlit Community Cloud](#deploying-to-streamlit-community-cloud)).
- **Synthetic data only.** The project has been tested with synthetic data only. It hasn't been validated on real prospect data.
- **No live data enrichment.** The engine assesses only the fields in the input CSV. It doesn't look up companies, contacts, hiring or triggers from any external source.
- **No sending.** The application never sends email or launches campaigns. Its only outputs are CSV files.
- **Review records can't be approved.** They can be drafted and edited in the Sequence Builder, but never approved or exported for sequencing.
- **Two internal Streamlit selectors.** The theme's tab underline and filter-chip styling rely on Streamlit internal CSS hooks that may need updating after a Streamlit upgrade. If they stop matching, those elements fall back to the theme colours.

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
  dashboard.py                    # dashboard filters, KPIs, distributions, histogram, priority order (no Streamlit)
  charts.py                       # Altair chart builders for the dashboard (app only)
  style.py                        # brand palette, app stylesheet, priority-row highlight
outreach/
  first_touch.py                  # deterministic, evidence-based first-touch drafts (no Streamlit import)
  sequence.py                     # drafts, approval, filters, Draft Review and Sequencing CSV exports
streamlit_app.py                  # Streamlit web interface (three tabs)
.streamlit/config.toml            # binds the app to 127.0.0.1; usage statistics off; brand theme
requirements.txt                  # web interface dependencies (Streamlit, Altair, pandas), pinned
tests/
  fixtures/expected_results.csv   # hand-derived expected outcomes
  test_sample_dataset.py          # all 25 records against the fixture
  test_rules.py                   # rule boundaries and test-only cases
  test_ui_helpers.py              # upload handling, safety labels, filters
  test_export_guard.py            # fail-closed sequencing export guard
  test_first_touch.py             # evidence rules and draft generation
  test_sequence_builder.py        # approval, sender changes, filters, both exports, guard
  test_csv_safety.py              # formula-injection protection; localhost-only server config
  test_dashboard.py               # dashboard calculations, filters, no mutation, theme/security config
  test_style.py                   # palette, stylesheet, contrast, priority-row highlight
.gitignore                        # excludes .venv, caches, secrets and generated output
```

Generated files are not committed: `data/output/` and any `scored_companies*.csv`, `sequence_drafts_*.csv` or `sequencing_import_*.csv` file saved into the project are ignored. The sample input, its backup, the data dictionary and the test fixtures are tracked.

## Changing the rules

1. Update [`docs/scoring_specification.md`](docs/scoring_specification.md) and get the change approved.
2. Edit the thresholds or keyword lists in [`scoring/rules.py`](scoring/rules.py), or the logic in the relevant module.
3. Update [`tests/fixtures/expected_results.csv`](tests/fixtures/expected_results.csv) **by hand from the spec**. Don't regenerate it from engine output.
4. Run the validator and the tests.

The `test_scenario` column in the dataset is test metadata only. The engine drops it before scoring, and a test checks that it never affects any result.
