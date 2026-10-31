"""Streamlit interface for the Signal-to-Sequence Engine.

Run: .venv\\Scripts\\python.exe -m streamlit run streamlit_app.py

Two tabs: "ICP & Account Intelligence" (assessment) and "Sequence Builder" (first-touch drafts).
This app never sends email or launches campaigns. Scoring is done by the scoring package; drafting
and export rules live in the outreach package. The Sequencing CSV is the only import-ready file and
every row in it has passed scoring.sequencing_export(), the fail-closed guard.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from outreach import sequence as seq
from outreach.first_touch import BODY_MAX_WORDS, BODY_MIN_WORDS, RESEARCH_NOTE, SenderSettings
from ui import helpers

SAMPLE_PATH = Path(__file__).resolve().parent / "data" / "input" / "sample_companies.csv"
SAMPLE_AS_OF = date(2026, 10, 30)
PREVIEW_ROWS = 20
TABLE_COLUMNS = ["data_status", "company_id", "company_name", "icp_outcome", "icp_score", "potential_score",
                 "contact_readiness", "campaign_readiness", "icp_flags", "contact_flags"]
WORKFLOW_STATE = ("drafts", "selected", "sender_applied", "sender_notice", "editor_version", "draft_message")
DRAFT_WIDGET_PREFIXES = ("subject::", "body::", "reason::")

st.set_page_config(page_title="Signal-to-Sequence Engine", layout="wide")


def clear_draft_widgets(keys=None):
    for name in list(st.session_state.keys()):
        if isinstance(name, str) and name.startswith(DRAFT_WIDGET_PREFIXES):
            if keys is None or name.split("::", 1)[1] in keys:
                del st.session_state[name]


def clear_workflow():
    """Drafts belong to one scoring run; a new file or a new run starts the workflow again."""
    for name in WORKFLOW_STATE:
        st.session_state.pop(name, None)
    clear_draft_widgets()


def load_source(name, data):
    """Remember the file and clear any results that belonged to a previous file."""
    if st.session_state.get("source") != (name, data):
        st.session_state["source"] = (name, data)
        st.session_state.pop("results", None)
        st.session_state.pop("scored_as_of", None)
        clear_workflow()


def data_badge(status):
    return {helpers.SYNTHETIC: "🧪 TEST DATA", helpers.UNVERIFIED: "⚠ UNVERIFIED"}.get(status, "")


# ---- Sidebar: input and sender settings -----------------------------------------------------
with st.sidebar:
    st.header("Input")
    uploaded = st.file_uploader("Company CSV", type=["csv"])
    if uploaded is not None:
        load_source(uploaded.name, uploaded.getvalue())
    if st.button("Load sample dataset (synthetic)"):
        load_source(SAMPLE_PATH.name, SAMPLE_PATH.read_bytes())
        st.session_state["as_of"] = SAMPLE_AS_OF

    st.session_state.setdefault("as_of", date.today())
    as_of = st.date_input("Assess as of", key="as_of",
                          help="Reference date for the 90-day hiring and trigger recency checks.")
    st.caption(f"The sample dataset is written for {SAMPLE_AS_OF.isoformat()}.")

    st.divider()
    st.header("Sender settings")
    st.text_input("Sender name", key="sender_name")
    st.text_area("Value proposition", key="sender_value", height=100,
                 help="What you offer, in your words. The generator never writes this for you.")
    st.text_area("Call to action", key="sender_cta", height=70)
    st.caption("Session only: not saved to disk and lost when the browser tab is refreshed. Until all three "
               "are filled in, drafts show placeholders and cannot be approved.")
    st.divider()
    st.caption("This app does not send email or launch campaigns. It produces CSV files only.")

sender = SenderSettings(st.session_state.get("sender_name", ""), st.session_state.get("sender_value", ""),
                        st.session_state.get("sender_cta", ""))

st.title("Signal-to-Sequence Engine")
st.caption("Company ICP qualification · Contact readiness · Campaign readiness · First-touch drafts")

source = st.session_state.get("source")
if source is None:
    st.info("Upload a company CSV or load the synthetic sample dataset from the sidebar to begin.")
    st.stop()

name, data = source

# ---- Validate the file before anything is scored ---------------------------------------------
parsed = helpers.parse_csv_bytes(data)
if parsed.errors:
    st.error(f"**{name}** cannot be scored:\n\n" + "\n".join(f"- {error}" for error in parsed.errors))
    st.stop()

columns = helpers.check_columns(parsed.header)
if columns.missing_required:
    st.error(f"**{name}** is missing required columns, so it cannot be scored: "
             + ", ".join(f"`{column}`" for column in columns.missing_required)
             + ". See data/input/data_dictionary.md for the expected format.")
    st.stop()
if columns.missing_optional:
    st.warning("Optional columns are missing. Scoring will run, with these effects:\n\n"
               + "\n".join(f"- `{column}`: {why}" for column, why in columns.missing_optional.items()))
if columns.unrecognised:
    st.info("Columns not used by the engine (ignored): " + ", ".join(f"`{c}`" for c in columns.unrecognised))
for warning in helpers.row_warnings(parsed.rows):
    st.warning(warning)

# ---- Data safety banner (shown above both tabs) ----------------------------------------------
statuses = [helpers.data_status(row) for row in parsed.rows]
synthetic_count = statuses.count(helpers.SYNTHETIC)
unverified_count = statuses.count(helpers.UNVERIFIED)
if synthetic_count:
    st.error(f"**TEST DATA:** {synthetic_count} of {len(statuses)} records are synthetic. "
             "They are fictional, for testing only, and are not real prospects.")
if unverified_count:
    st.warning(f"**UNVERIFIED:** {unverified_count} of {len(statuses)} records are not marked "
               "`is_synthetic=true` or `false`. Treat them as unverified, not as genuine prospects.")

# ---- Draft workflow state (shared by both tabs) ----------------------------------------------
results = st.session_state.get("results")
records, drafts, record_by_result = [], {}, {}
if results is not None:
    scored_as_of = st.session_state["scored_as_of"]
    records = seq.make_records(parsed.rows, results)
    record_by_result = {id(record.result): record for record in records}
    drafts = st.session_state.setdefault("drafts", {})
    applied = st.session_state.get("sender_applied")
    if applied is not None and applied != sender.normalised():
        regenerated, outdated = seq.apply_sender_settings(drafts, records, sender, scored_as_of)
        clear_draft_widgets(set(regenerated))
        st.session_state["sender_notice"] = (len(regenerated), len(outdated))
    st.session_state["sender_applied"] = sender.normalised()
    seq.ensure_drafts(drafts, records, sender, scored_as_of)

tab_icp, tab_builder = st.tabs(["ICP & Account Intelligence", "Sequence Builder"])

# =============================================================================================
# TAB 1: ICP & Account Intelligence
# =============================================================================================
with tab_icp:
    st.subheader("Uploaded data")
    st.caption(f"{name} · {len(parsed.rows)} records · showing the first {min(PREVIEW_ROWS, len(parsed.rows))}")
    st.dataframe(parsed.rows[:PREVIEW_ROWS], hide_index=True)

    touched = sum(1 for draft in drafts.values() if draft.touched)
    if touched:
        st.warning(f"Running scoring again will discard {touched} edited or reviewed draft(s) in the "
                   "Sequence Builder. Download a Draft Review CSV first if you want to keep them.")
    if st.button("Run ICP scoring", type="primary"):
        clear_workflow()
        st.session_state["results"] = helpers.score_rows(parsed.rows, as_of)
        st.session_state["scored_as_of"] = as_of
        st.rerun()

    if results is None:
        st.info("Run ICP scoring to see results.")
    else:
        if scored_as_of != as_of:
            st.warning(f"Results below were scored as of {scored_as_of.isoformat()}. Run scoring again to use "
                       f"{as_of.isoformat()}.")

        # ---- Summary metrics -----------------------------------------------------------------
        st.divider()
        label = " (test data)" if synthetic_count else ""
        st.subheader(f"Results{label}")
        st.caption(f"Scored as of {scored_as_of.isoformat()} · {len(results)} records")

        st.markdown("**Company ICP qualification**")
        for column, (outcome, count) in zip(st.columns(3), helpers.count_by(results, "icp_outcome",
                                                                             helpers.ICP_OUTCOMES).items()):
            column.metric(outcome, count)

        st.markdown("**Campaign readiness**")
        for column, (outcome, count) in zip(st.columns(5), helpers.count_by(results, "campaign_readiness",
                                                                             helpers.CAMPAIGN_OUTCOMES).items()):
            column.metric(outcome, count)

        st.markdown("**Contact readiness**")
        for column, (outcome, count) in zip(st.columns(3), helpers.count_by(results, "contact_readiness",
                                                                             helpers.CONTACT_OUTCOMES).items()):
            column.metric(outcome, count)

        # ---- Searchable, filterable table ----------------------------------------------------
        st.divider()
        st.subheader("Companies")
        search_col, icp_col, campaign_col = st.columns([2, 1, 1])
        search = search_col.text_input("Search company ID or name")
        icp_filter = icp_col.multiselect("ICP outcome", helpers.ICP_OUTCOMES)
        campaign_filter = campaign_col.multiselect("Campaign readiness", helpers.CAMPAIGN_OUTCOMES)
        contact_col, flag_col, status_col = st.columns([1, 2, 1])
        contact_filter = contact_col.multiselect("Contact readiness", helpers.CONTACT_OUTCOMES)
        flag_filter = flag_col.multiselect("Has any of these flags", helpers.all_flags(results))
        status_filter = status_col.multiselect("Data status", sorted({r["data_status"] for r in results}))

        filtered = helpers.filter_results(results, search, icp_filter, campaign_filter, contact_filter,
                                          flag_filter, status_filter)
        st.caption(f"{len(filtered)} of {len(results)} companies")
        st.dataframe([{column: result[column] for column in TABLE_COLUMNS} for result in filtered],
                     hide_index=True)

        # ---- Company detail ------------------------------------------------------------------
        st.divider()
        st.subheader("Company detail")
        if not filtered:
            st.info("No companies match the current filters.")
        else:
            by_id = {f"{r['company_id']} — {r['company_name']}": r for r in filtered}
            selected = by_id[st.selectbox("Select a company", list(by_id))]

            if selected["data_status"] == helpers.SYNTHETIC:
                st.error("SYNTHETIC TEST DATA — fictional record, not a real prospect.")
            elif selected["data_status"] == helpers.UNVERIFIED:
                st.warning("UNVERIFIED — this record is not marked as synthetic or genuine.")

            icp_col, contact_col, campaign_col = st.columns(3)
            with icp_col:
                st.markdown("##### A. Company ICP qualification")
                st.metric("Outcome", selected["icp_outcome"])
                st.write(f"Confirmed score: **{selected['icp_score']}** / 100")
                st.write(f"Potential score: **{selected['potential_score']}** / 100")
                if selected["size_indication"]:
                    st.write(f"Size indication (display only): `{selected['size_indication']}`")
            with contact_col:
                st.markdown("##### B. Contact readiness")
                st.metric("Outcome", selected["contact_readiness"])
                st.write(" ".join(f"`{flag}`" for flag in selected["contact_flags"].split("|") if flag)
                         or "No flags")
                st.caption(selected["contact_reasons"])
            with campaign_col:
                st.markdown("##### C. Campaign readiness")
                st.metric("Outcome", helpers.campaign_display(selected))
                st.write(f"Trigger status: `{selected['campaign_trigger_status']}`")
                st.caption(selected["campaign_reasons"])

            st.markdown("##### ICP score breakdown")
            st.dataframe(helpers.criterion_breakdown(selected), hide_index=True)
            st.markdown("**ICP flags:** " + (" ".join(f"`{flag}`" for flag in selected["icp_flags"].split("|")
                                                      if flag) or "none"))
            st.markdown("**ICP reasons**")
            st.write(selected["icp_reasons"])

            # ---- First-touch email preview -------------------------------------------------------
            st.markdown("##### First-touch email preview")
            record = record_by_result.get(id(selected))
            draft = drafts.get(record.key) if record else None
            if draft is None:
                st.info("Not in the sequencing workflow: only Qualified (and, for research, Review) records "
                        "are drafted. Disqualified records never enter it.")
            elif draft.status == seq.NEEDS_RESEARCH:
                st.warning(f"**Needs Research.** {RESEARCH_NOTE}")
            else:
                st.caption(f"Draft status: **{draft.status}** · {draft.body_words} body words · "
                           "edit and approve in the Sequence Builder tab")
                st.code(f"Subject: {draft.subject}\n\n{draft.full_email()}", language=None)
                st.markdown(f"**Personalization evidence:** {draft.personalization_reason}")

    # ---- Download --------------------------------------------------------------------------------
    if results is not None:
        st.divider()
        st.subheader("Download")
        filename = helpers.download_filename(results)
        if synthetic_count:
            st.caption("This report contains synthetic test records. The filename and the `data_status` and "
                       "`is_synthetic` columns mark them as test data.")
        st.download_button("Download scored CSV", data=helpers.results_to_csv_bytes(results), file_name=filename,
                           mime="text/csv", on_click="ignore")
        st.caption("This is an assessment report, not a sequencing export. No records are sent anywhere.")


# =============================================================================================
# TAB 2: Sequence Builder
# =============================================================================================
def save_draft_edit(key):
    edit = {"subject": st.session_state.get(f"subject::{key}"), "body": st.session_state.get(f"body::{key}"),
            "personalization_reason": st.session_state.get(f"reason::{key}")}
    if seq.edit_draft(drafts[key], **edit):
        st.session_state["draft_message"] = (key, "info", "Edit saved for this session.")


def approve_draft(key, record):
    problems = seq.approve(drafts[key], record)
    st.session_state["draft_message"] = ((key, "error", "Not approved: " + " ".join(problems)) if problems
                                         else (key, "success", "Approved."))


def mark_review(key):
    seq.mark_needs_review(drafts[key])
    st.session_state["draft_message"] = (key, "info", "Marked Needs Review.")


def reset_to_generated(key, record):
    drafts[key] = seq.reset_draft(record, sender, scored_as_of)
    clear_draft_widgets({key})
    st.session_state["draft_message"] = (key, "info", "Reset to the generated draft; edits and status cleared.")


def set_selection(keys, selected):
    chosen = st.session_state.setdefault("selected", set())
    chosen.update(keys) if selected else chosen.difference_update(keys)
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1


with tab_builder:
    st.subheader("Sequence Builder")
    st.caption("First-touch drafts for human review. Nothing is sent: the only output is CSV files.")

    if results is None:
        st.info("Run ICP scoring in the ICP & Account Intelligence tab first.")
    else:
        if synthetic_count:
            st.error("🧪 **TEST DATA.** Synthetic records can be drafted and tested here, but they are not real "
                     "prospects and can never be included in the Sequencing CSV.")
        if not sender.is_complete():
            st.warning("**Sender settings are incomplete** (sidebar). Drafts show placeholders and cannot be "
                       "approved until sender name, value proposition and call to action are all filled in.")
        notice = st.session_state.get("sender_notice")
        if notice:
            regenerated_count, outdated_count = notice
            st.info(f"Sender settings changed: {regenerated_count} untouched draft(s) regenerated. "
                    f"{outdated_count} edited or reviewed draft(s) were kept unchanged and are marked "
                    "'sender settings outdated'.")

        include_review = st.toggle("Include Review records", key="include_review",
                                   help="Review records can be drafted for research but never approved or exported.")
        workflow_records = seq.builder_records(records, include_review)

        search_col, icp_col, contact_col = st.columns([2, 1, 1])
        builder_search = search_col.text_input("Search company, ID or contact", key="builder_search")
        icp_options = ["Qualified", "Review"] if include_review else ["Qualified"]
        builder_icp = icp_col.multiselect("ICP outcome", icp_options, key="builder_icp")
        builder_contact = contact_col.multiselect("Contact readiness", helpers.CONTACT_OUTCOMES,
                                                  key="builder_contact")
        campaign_col, status_col = st.columns(2)
        builder_campaign = campaign_col.multiselect("Campaign readiness", helpers.CAMPAIGN_OUTCOMES,
                                                    key="builder_campaign")
        builder_status = status_col.multiselect("Draft status", seq.DRAFT_STATUSES, key="builder_status")

        shown = seq.filter_builder(workflow_records, drafts, builder_search, builder_icp, builder_contact,
                                   builder_campaign, builder_status)
        selected_keys = st.session_state.setdefault("selected", set())
        workflow_keys = {record.key for record in workflow_records}
        selected_keys.intersection_update({record.key for record in seq.builder_records(records, True)})
        active_selection = selected_keys & workflow_keys

        status_counts = {status: sum(1 for r in workflow_records if drafts[r.key].status == status)
                         for status in seq.DRAFT_STATUSES}
        for column, (status, count) in zip(st.columns(4), status_counts.items()):
            column.metric(status, count)

        # ---- Drafts table with multi-select ---------------------------------------------------
        st.markdown(f"**Drafts** · {len(shown)} shown of {len(workflow_records)} · "
                    f"{len(active_selection)} selected")
        select_col, clear_col, _ = st.columns([1, 1, 4])
        select_col.button("Select all shown", on_click=set_selection, args=([r.key for r in shown], True))
        clear_col.button("Clear selection", on_click=set_selection, args=(list(workflow_keys), False))

        def campaign_badge(result):
            readiness = result["campaign_readiness"]
            return readiness if readiness == "Ready to Sequence" else f"⚠ {readiness} — not campaign-ready"

        table = pd.DataFrame([{
            "_key": record.key,
            "Select": record.key in selected_keys,
            "Data": data_badge(record.result["data_status"]),
            "Company": record.result["company_name"],
            "Contact": f"{record.row.get('contact_first_name', '')} {record.row.get('contact_last_name', '')}".strip(),
            "Job title": record.row.get("contact_title", ""),
            "Email": record.row.get("contact_email", ""),
            "ICP score": record.result["icp_score"],
            "ICP outcome": record.result["icp_outcome"],
            "Contact readiness": record.result["contact_readiness"],
            "Campaign readiness": campaign_badge(record.result),
            "Email subject": drafts[record.key].subject,
            "Email body": drafts[record.key].full_email() if drafts[record.key].body else "",
            "Draft status": drafts[record.key].status,
            "Personalization evidence": drafts[record.key].personalization_reason or RESEARCH_NOTE,
        } for record in shown], columns=["_key", "Select", "Data", "Company", "Contact", "Job title", "Email",
                                         "ICP score", "ICP outcome", "Contact readiness", "Campaign readiness",
                                         "Email subject", "Email body", "Draft status",
                                         "Personalization evidence"])
        editor_key = f"builder_table::{st.session_state.get('editor_version', 0)}::{hash(tuple(table['_key']))}"
        edited = st.data_editor(table, key=editor_key, hide_index=True,
                                disabled=[column for column in table.columns if column != "Select"],
                                column_config={"_key": None,
                                               "Select": st.column_config.CheckboxColumn("Select"),
                                               "Email body": st.column_config.TextColumn(width="large"),
                                               "Personalization evidence": st.column_config.TextColumn(
                                                   width="medium")})
        for key, chosen in zip(edited["_key"], edited["Select"]):
            selected_keys.add(key) if chosen else selected_keys.discard(key)
        active_selection = selected_keys & workflow_keys

        # ---- Draft editor --------------------------------------------------------------------
        st.divider()
        st.markdown("##### Draft editor")
        if not shown:
            st.info("No drafts match the current filters.")
        else:
            labels = {f"{r.result['company_id']} — {r.result['company_name']}": r for r in shown}
            record = labels[st.selectbox("Choose a draft to edit", list(labels), key="builder_record")]
            key, draft = record.key, drafts[record.key]

            if record.result["data_status"] == helpers.SYNTHETIC:
                st.error("🧪 TEST DATA — fictional record. It can be drafted and approved for testing, but it can "
                         "never be exported to the Sequencing CSV.")
            elif record.result["data_status"] == helpers.UNVERIFIED:
                st.warning("⚠ UNVERIFIED — not marked is_synthetic=false, so it can never be exported as a real "
                           "prospect.")
            if record.result["icp_outcome"] == "Review":
                st.info("Review record: may be drafted and edited for research and preparation, but cannot be "
                        "approved or exported.")
            if record.result["campaign_readiness"] != "Ready to Sequence":
                st.warning(f"Not campaign-ready: {record.result['campaign_readiness']}. "
                           f"{record.result['campaign_reasons']}")
            if seq.sender_outdated(draft, sender):
                st.warning("Sender settings outdated: this draft was edited or reviewed before the sender settings "
                           "changed, so it was kept as-is. Its sender details may be out of date; edit it or use "
                           "Reset to generated.")
            if draft.status == seq.NEEDS_RESEARCH:
                st.warning(f"**Needs Research.** {RESEARCH_NOTE} You can write notes here for preparation, but "
                           "this draft cannot be approved without current, dated evidence in the input data.")

            message = st.session_state.get("draft_message")
            if message and message[0] == key:
                getattr(st, message[1])(message[2])

            for prefix, value in (("subject::", draft.subject), ("body::", draft.body),
                                  ("reason::", draft.personalization_reason)):
                st.session_state.setdefault(prefix + key, value)

            st.caption(f"Status: **{draft.status}**")
            st.text_input("Subject", key=f"subject::{key}", on_change=save_draft_edit, args=(key,))
            st.text(draft.greeting)
            st.text_area(f"Body ({BODY_MIN_WORDS}-{BODY_MAX_WORDS} words; the greeting above and signature below "
                         "are added automatically and not counted)", key=f"body::{key}", height=220,
                         on_change=save_draft_edit, args=(key,))
            st.text(draft.signature)
            words = draft.body_words
            if BODY_MIN_WORDS <= words <= BODY_MAX_WORDS:
                st.success(f"Body word count: {words} (within {BODY_MIN_WORDS}-{BODY_MAX_WORDS}).")
            else:
                st.error(f"Body word count: {words}. Approval needs {BODY_MIN_WORDS}-{BODY_MAX_WORDS} words in the "
                         "body; the greeting and signature are excluded from the count.")
            st.text_input("Personalization reason", key=f"reason::{key}", on_change=save_draft_edit, args=(key,))

            st.markdown("**Personalization evidence**")
            if draft.evidence:
                st.dataframe([{"Type": e.kind, "Fact used": e.summary, "Date": e.date,
                               "Days before as-of": e.age_days, "Source fields": ", ".join(e.source_fields),
                               "Why it counts": e.basis} for e in draft.evidence], hide_index=True)
            else:
                st.caption("No current, dated evidence for this record.")

            st.markdown("**Approval checklist**")
            checks = seq.approval_checks(draft, record)
            for check_label, passed, explanation in checks:
                st.markdown(f"{'✅' if passed else '❌'} {check_label}" + ("" if passed else f" — {explanation}"))

            approve_col, review_col, reset_col = st.columns(3)
            approve_col.button("Approve", type="primary", disabled=not all(passed for _, passed, _ in checks),
                               on_click=approve_draft, args=(key, record), key=f"approve::{key}")
            review_col.button("Mark Needs Review", on_click=mark_review, args=(key,), key=f"review::{key}")
            reset_col.button("Reset to generated", on_click=reset_to_generated, args=(key, record),
                             key=f"reset::{key}")

            st.markdown("**Copy this draft**")
            st.code(f"Subject: {draft.subject}\n\n{draft.full_email()}", language=None)

        # ---- Exports ---------------------------------------------------------------------------
        st.divider()
        st.markdown("##### Export selected records")
        chosen = active_selection
        if not chosen:
            st.info("Select records in the table to export them.")
        else:
            review = seq.review_rows(records, drafts, chosen, sender)
            export = seq.build_sequencing_export(records, drafts, chosen)
            st.dataframe([{"Data": data_badge(r["data_status"]), "Company": r["company_name"],
                           "Draft status": r["draft_status"], "Eligible for Sequencing CSV": r["eligible_for_sequencing"],
                           "Reasons": r["eligibility_reasons"] or "All six conditions met."} for r in review],
                         hide_index=True)

            review_col, live_col = st.columns(2)
            with review_col:
                st.markdown("**A. Draft Review CSV — REVIEW ONLY**")
                st.caption(f"All {len(review)} selected record(s), including synthetic and unverified ones, with "
                           "data status, draft status and eligibility reasons. Not an import file: never load it "
                           "into a sending tool.")
                st.download_button("Download Draft Review CSV (REVIEW ONLY)",
                                   data=seq.rows_to_csv_bytes(review, seq.REVIEW_COLUMNS),
                                   file_name=seq.review_filename(review), mime="text/csv", on_click="ignore")
            with live_col:
                st.markdown("**B. Sequencing CSV**")
                st.caption(f"{len(export.rows)} of {len(chosen)} selected record(s) meet all six conditions and "
                           "passed the fail-closed guard. For later manual import; nothing is sent.")
                if export.guard_error:
                    st.error(f"Blocked by the fail-closed export guard: {export.guard_error}")
                st.download_button("Download Sequencing CSV",
                                   data=seq.rows_to_csv_bytes(export.rows, seq.SEQUENCING_COLUMNS),
                                   file_name=f"sequencing_import_{scored_as_of.isoformat()}.csv", mime="text/csv",
                                   disabled=not export.rows, on_click="ignore")
