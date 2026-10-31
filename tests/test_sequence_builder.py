"""Sequence Builder: drafts, approval, sender changes, filters, both exports and the fail-closed guard."""

import csv
import io
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest import mock

from outreach import sequence as seq
from outreach.first_touch import SenderSettings
from tests.test_first_touch import AS_OF, SENDER, row
from ui import helpers

ROOT = Path(__file__).resolve().parent.parent
FIFTY_FIVE_WORDS = " ".join(["word"] * 55)


def make(**overrides):
    data = row(**overrides)
    return seq.make_records([data], helpers.score_rows([data], AS_OF))[0]


def approved(record=None, sender=SENDER):
    record = record or make()
    draft = seq.new_draft(record, sender, AS_OF)
    problems = seq.approve(draft, record)
    assert not problems, problems
    return record, draft


def sample_records():
    parsed = helpers.parse_csv_bytes((ROOT / "data" / "input" / "sample_companies.csv").read_bytes())
    return seq.make_records(parsed.rows, helpers.score_rows(parsed.rows, AS_OF))


def parse_csv(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


class BaselineTest(unittest.TestCase):
    def test_fixture_is_fully_eligible(self):
        record, draft = approved()
        self.assertEqual(draft.status, seq.APPROVED)
        self.assertEqual(seq.live_export_problems(record, draft), [])


class ApprovalConditionTest(unittest.TestCase):
    """Each approval condition fails on its own, with exactly that explanation."""

    def assertOnlyProblem(self, draft, record, fragment):
        problems = seq.approval_problems(draft, record)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(fragment, problems[0])
        before = draft.status
        self.assertTrue(seq.approve(draft, record))
        self.assertEqual(draft.status, before)

    def test_icp_must_be_qualified(self):
        record = make(employee_count_source_b="")          # single source -> Review
        self.assertEqual(record.result["icp_outcome"], "Review")
        self.assertOnlyProblem(seq.new_draft(record, SENDER, AS_OF), record, "only Qualified")

    def test_contact_must_be_ready(self):
        for status in ("unverified", "catch_all", "risky", "invalid"):
            with self.subTest(status=status):
                record = make(email_verification_status=status)
                self.assertEqual(record.result["icp_outcome"], "Qualified")
                self.assertOnlyProblem(seq.new_draft(record, SENDER, AS_OF), record, "Contact readiness is")

    def test_subject_must_not_be_empty(self):
        record = make()
        draft = seq.new_draft(record, SENDER, AS_OF)
        seq.edit_draft(draft, subject="   ")
        self.assertOnlyProblem(draft, record, "Subject is empty")

    def test_body_word_count_boundaries(self):
        record = make()
        for words, allowed in ((49, False), (50, True), (80, True), (81, False)):
            with self.subTest(words=words):
                draft = seq.new_draft(record, SENDER, AS_OF)
                seq.edit_draft(draft, body=" ".join(["word"] * words))
                if allowed:
                    self.assertEqual(seq.approval_problems(draft, record), [])
                else:
                    self.assertOnlyProblem(draft, record, f"Body has {words} words")

    def test_no_placeholders_may_remain(self):
        record = make()
        draft = seq.new_draft(record, SENDER, AS_OF)
        seq.edit_draft(draft, body=FIFTY_FIVE_WORDS + " [insert result]")
        self.assertOnlyProblem(draft, record, "[insert result]")

    def test_incomplete_sender_settings_block_approval(self):
        record = make()
        for sender in (SenderSettings("", SENDER.value_proposition, SENDER.call_to_action),
                       SenderSettings(SENDER.sender_name, "", SENDER.call_to_action),
                       SenderSettings(SENDER.sender_name, SENDER.value_proposition, "")):
            with self.subTest(sender=sender):
                draft = seq.new_draft(record, sender, AS_OF)
                problems = " ".join(seq.approval_problems(draft, record))
                self.assertIn("Replace placeholders", problems)

    def test_first_name_must_be_available(self):
        record = make(contact_first_name="")
        draft = seq.new_draft(record, SENDER, AS_OF)
        draft.greeting = "Hi there,"     # isolate the first-name condition from the greeting placeholder
        self.assertOnlyProblem(draft, record, "first name is missing")

    def test_personalization_reason_must_be_present(self):
        record = make()
        draft = seq.new_draft(record, SENDER, AS_OF)
        seq.edit_draft(draft, personalization_reason=" ")
        self.assertOnlyProblem(draft, record, "Personalization reason is empty")

    def test_evidence_must_be_current_and_documented(self):
        record = make()
        draft = seq.new_draft(record, SENDER, AS_OF)
        draft.evidence = ()
        self.assertOnlyProblem(draft, record, "No current, dated evidence")

    def test_needs_research_draft_cannot_be_approved_even_if_written_by_hand(self):
        record = make(open_sales_roles="0", sales_role_titles="", hiring_signal_last_seen="",
                      description="Billing software for finance teams. Sold through a direct sales team.")
        draft = seq.new_draft(record, SENDER, AS_OF)
        self.assertEqual(draft.status, seq.NEEDS_RESEARCH)
        seq.edit_draft(draft, subject="Hello", body=FIFTY_FIVE_WORDS, personalization_reason="My own research")
        self.assertOnlyProblem(draft, record, "No current, dated evidence")

    def test_review_records_can_be_drafted_and_edited_but_not_approved(self):
        record = make(employee_count_source_b="")
        draft = seq.new_draft(record, SENDER, AS_OF)
        self.assertEqual(draft.status, seq.DRAFT)
        self.assertTrue(seq.edit_draft(draft, subject="Edited for research"))
        self.assertTrue(seq.approve(draft, record))
        self.assertNotEqual(draft.status, seq.APPROVED)


class EditingTest(unittest.TestCase):
    def test_edits_are_kept_and_mark_the_draft_touched(self):
        record = make()
        drafts = seq.ensure_drafts({}, [record], SENDER, AS_OF)
        draft = drafts[record.key]
        self.assertTrue(seq.edit_draft(draft, subject="New subject", body=FIFTY_FIVE_WORDS))
        seq.ensure_drafts(drafts, [record], SENDER, AS_OF)          # a later rerun must not overwrite
        self.assertEqual((drafts[record.key].subject, drafts[record.key].body), ("New subject", FIFTY_FIVE_WORDS))
        self.assertTrue(drafts[record.key].touched)

    def test_unchanged_edit_is_not_a_change(self):
        record = make()
        draft = seq.new_draft(record, SENDER, AS_OF)
        self.assertFalse(seq.edit_draft(draft, subject=draft.subject))
        self.assertFalse(draft.touched)

    def test_editing_an_approved_draft_requires_review_again(self):
        record, draft = approved()
        seq.edit_draft(draft, body=FIFTY_FIVE_WORDS)
        self.assertEqual(draft.status, seq.NEEDS_REVIEW)

    def test_mark_needs_review_and_reset(self):
        record, draft = approved()
        seq.mark_needs_review(draft)
        self.assertEqual(draft.status, seq.NEEDS_REVIEW)
        fresh = seq.reset_draft(record, SENDER, AS_OF)
        self.assertEqual((fresh.status, fresh.touched), (seq.DRAFT, False))
        self.assertEqual(fresh.body, seq.new_draft(record, SENDER, AS_OF).body)


class SenderChangeTest(unittest.TestCase):
    def setUp(self):
        self.untouched, self.edited, self.approved_record = make(company_id="A"), make(company_id="B"), make(company_id="C")
        self.records = [self.untouched, self.edited, self.approved_record]
        self.drafts = seq.ensure_drafts({}, self.records, SENDER, AS_OF)
        seq.edit_draft(self.drafts[self.edited.key], body=FIFTY_FIVE_WORDS)
        seq.approve(self.drafts[self.approved_record.key], self.approved_record)
        self.new_sender = SenderSettings("Sam Example", SENDER.value_proposition.replace("faster", "sooner"),
                                         SENDER.call_to_action)

    def test_only_untouched_drafts_are_regenerated(self):
        regenerated, outdated = seq.apply_sender_settings(self.drafts, self.records, self.new_sender, AS_OF)
        self.assertEqual(regenerated, [self.untouched.key])
        self.assertEqual(sorted(outdated), sorted([self.edited.key, self.approved_record.key]))
        self.assertIn("sooner", self.drafts[self.untouched.key].body)
        self.assertIn("Sam Example", self.drafts[self.untouched.key].signature)

    def test_edited_and_approved_drafts_are_never_overwritten(self):
        seq.apply_sender_settings(self.drafts, self.records, self.new_sender, AS_OF)
        self.assertEqual(self.drafts[self.edited.key].body, FIFTY_FIVE_WORDS)
        self.assertEqual(self.drafts[self.approved_record.key].status, seq.APPROVED)
        self.assertIn("Jordan Example", self.drafts[self.approved_record.key].signature)

    def test_outdated_drafts_are_flagged(self):
        seq.apply_sender_settings(self.drafts, self.records, self.new_sender, AS_OF)
        self.assertFalse(seq.sender_outdated(self.drafts[self.untouched.key], self.new_sender))
        self.assertTrue(seq.sender_outdated(self.drafts[self.edited.key], self.new_sender))
        self.assertTrue(seq.sender_outdated(self.drafts[self.approved_record.key], self.new_sender))

    def test_whitespace_only_change_is_not_a_change(self):
        padded = SenderSettings(" " + SENDER.sender_name + " ", SENDER.value_proposition, SENDER.call_to_action)
        self.assertEqual(seq.apply_sender_settings(self.drafts, self.records, padded, AS_OF), ([], []))


class VisibilityAndFilterTest(unittest.TestCase):
    def setUp(self):
        self.records = sample_records()
        self.drafts = seq.ensure_drafts({}, self.records, SENDER, AS_OF)

    def ids(self, records):
        return [record.result["company_id"] for record in records]

    def test_qualified_by_default_and_review_on_request(self):
        default = seq.builder_records(self.records)
        self.assertEqual(self.ids(default), ["SYN-001", "SYN-013", "SYN-018", "SYN-019", "SYN-020", "SYN-023"])
        with_review = seq.builder_records(self.records, include_review=True)
        self.assertEqual(len(with_review), 18)
        self.assertEqual({r.result["icp_outcome"] for r in with_review}, {"Qualified", "Review"})

    def test_disqualified_never_enter_the_workflow(self):
        disqualified = {r.key for r in self.records if r.result["icp_outcome"] == "Disqualified"}
        self.assertEqual(len(disqualified), 7)
        self.assertFalse(disqualified & {r.key for r in seq.builder_records(self.records, include_review=True)})
        self.assertFalse(disqualified & set(self.drafts))

    def test_filters(self):
        visible = seq.builder_records(self.records, include_review=True)
        f = lambda **kw: self.ids(seq.filter_builder(visible, self.drafts, **kw))  # noqa: E731
        self.assertEqual(f(icp=["Qualified"]), self.ids(seq.builder_records(self.records)))
        self.assertEqual(f(icp=["Qualified"], contact=["Needs Attention"]), ["SYN-019", "SYN-020"])
        self.assertEqual(f(campaign=["Ready to Sequence"]), ["SYN-001", "SYN-013", "SYN-018"])
        self.assertEqual(f(icp=["Qualified"], draft_status=[seq.NEEDS_RESEARCH]), ["SYN-023"])
        self.assertEqual(f(search="talia"), ["SYN-001"])
        self.assertEqual(f(search="copperleaf"), ["SYN-013"])


class LiveExportConditionTest(unittest.TestCase):
    """Each live-export condition blocks a record on its own; malformed values fail closed."""

    def assertBlocked(self, record, draft, fragment):
        problems = seq.live_export_problems(record, draft)
        self.assertTrue(any(fragment in problem for problem in problems), problems)
        export = seq.build_sequencing_export([record], {record.key: draft}, {record.key})
        self.assertEqual(export.rows, [])
        self.assertEqual(len(export.blocked), 1)

    def with_result(self, record, **changes):
        return replace(record, result={**record.result, **changes})

    def test_is_synthetic_must_be_explicitly_false(self):
        for value, fragment in [("true", "Synthetic test data"), ("TRUE", "Synthetic test data"),
                                ("", "missing or blank"), ("  ", "missing or blank"),
                                ("yes", "not recognised"), ("0", "not recognised"), ("null", "not recognised"),
                                ("f", "not recognised")]:
            with self.subTest(value=value):
                record, draft = approved(make(is_synthetic=value))
                self.assertBlocked(record, draft, fragment)

    def test_missing_or_non_string_is_synthetic_fails_closed(self):
        record, draft = approved()
        no_column = replace(record, row={k: v for k, v in record.row.items() if k != "is_synthetic"},
                            result={k: v for k, v in record.result.items() if k != "is_synthetic"})
        self.assertBlocked(no_column, draft, "missing or blank")
        for value in (None, False):
            with self.subTest(value=value):
                odd = replace(record, row={**record.row, "is_synthetic": value},
                              result={**record.result, "is_synthetic": value})
                self.assertBlocked(odd, draft, "explicitly false")

    def test_row_and_result_must_both_be_false(self):
        record, draft = approved()
        self.assertBlocked(self.with_result(record, is_synthetic="true"), draft, "Synthetic test data")

    def test_icp_must_be_qualified(self):
        record, draft = approved()
        for value in ("Review", "Disqualified", "qualified", "", None):
            with self.subTest(value=value):
                self.assertBlocked(self.with_result(record, icp_outcome=value), draft, "ICP outcome is")

    def test_contact_must_be_ready(self):
        record, draft = approved()
        for value in ("Needs Attention", "Not Ready", "ready", None):
            with self.subTest(value=value):
                self.assertBlocked(self.with_result(record, contact_readiness=value), draft, "Contact readiness is")

    def test_campaign_must_be_ready_to_sequence(self):
        record, draft = approved()
        for value in ("Hold: Trigger Research", "Hold: Contact", "Excluded", "ready to sequence", None):
            with self.subTest(value=value):
                self.assertBlocked(self.with_result(record, campaign_readiness=value), draft, "Campaign readiness is")

    def test_draft_must_be_approved(self):
        record = make()
        for status in (seq.DRAFT, seq.NEEDS_REVIEW, seq.NEEDS_RESEARCH):
            with self.subTest(status=status):
                draft = seq.new_draft(record, SENDER, AS_OF)
                draft.status = status
                self.assertBlocked(record, draft, "must be Approved")
        self.assertBlocked(record, None, "No draft exists")

    def test_approved_draft_is_revalidated_at_export(self):
        record, draft = approved()
        draft.body = FIFTY_FIVE_WORDS + " {oops}"          # changed without going through edit_draft
        self.assertBlocked(record, draft, "no longer passes approval checks")

    def test_email_must_be_present_well_formed_and_verified(self):
        record, draft = approved()
        cases = [({"contact_email": ""}, "email is missing"),
                 ({"contact_email": "not-an-email"}, "malformed"),
                 ({"contact_email": "a@b"}, "malformed"),
                 ({"email_verification_status": "unverified"}, "must be verified"),
                 ({"email_verification_status": "catch_all"}, "must be verified"),
                 ({"email_verification_status": ""}, "must be verified")]
        for change, fragment in cases:
            with self.subTest(change=change):
                self.assertBlocked(replace(record, row={**record.row, **change}), draft, fragment)


class LiveExportOutputTest(unittest.TestCase):
    def test_eligible_record_exports_the_eleven_columns(self):
        record, draft = approved(make(contact_linkedin_url="https://www.linkedin.com/in/supplied-value"))
        export = seq.build_sequencing_export([record], {record.key: draft}, {record.key})
        self.assertEqual(export.blocked, [])
        self.assertEqual(list(export.rows[0]), seq.SEQUENCING_COLUMNS)
        out = export.rows[0]
        self.assertEqual((out["company_name"], out["contact_name"], out["job_title"], out["email"]),
                         ("Fixture Co", "Test Person", "VP of Sales", "test.person@fixture.example"))
        self.assertEqual(out["linkedin_url"], "https://www.linkedin.com/in/supplied-value")
        self.assertEqual(out["hiring_signal"], "SDR (last seen 2026-10-20)")
        self.assertEqual(out["campaign_trigger"], "")
        self.assertTrue(out["email_body"].startswith("Hi Test,"))
        self.assertTrue(out["email_body"].endswith("Jordan Example"))
        parsed = parse_csv(seq.rows_to_csv_bytes(export.rows, seq.SEQUENCING_COLUMNS))
        self.assertEqual(parsed[0]["subject"], "Sales hiring at Fixture Co")

    def test_linkedin_is_blank_when_not_supplied(self):
        record, draft = approved()
        export = seq.build_sequencing_export([record], {record.key: draft}, {record.key})
        self.assertEqual(export.rows[0]["linkedin_url"], "")

    def test_only_selected_records_are_considered(self):
        record, draft = approved()
        export = seq.build_sequencing_export([record], {record.key: draft}, set())
        self.assertEqual((export.rows, export.blocked), ([], []))

    def test_mixed_selection_exports_only_the_eligible_record(self):
        good, good_draft = approved(make(company_id="GOOD"))
        bad, bad_draft = approved(make(company_id="SYN", is_synthetic="true"))
        export = seq.build_sequencing_export([good, bad], {good.key: good_draft, bad.key: bad_draft},
                                             {good.key, bad.key})
        self.assertEqual(len(export.rows), 1)
        self.assertEqual(export.blocked[0][0].key, bad.key)


class FailClosedGuardTest(unittest.TestCase):
    def test_sequencing_export_guard_is_always_called(self):
        record, draft = approved()
        with mock.patch("outreach.sequence.sequencing_export", wraps=seq.sequencing_export) as guard:
            seq.build_sequencing_export([record], {record.key: draft}, {record.key})
        guard.assert_called_once()

    def test_guard_still_blocks_synthetic_if_eligibility_were_bypassed(self):
        record, draft = approved(make(is_synthetic="true"))
        with mock.patch("outreach.sequence.live_export_problems", return_value=[]):
            export = seq.build_sequencing_export([record], {record.key: draft}, {record.key})
        self.assertEqual(export.rows, [])
        self.assertIn("synthetic", export.guard_error)
        self.assertIn("fail-closed export guard", export.blocked[0][1][0])

    def test_guard_blocks_unverified_if_eligibility_were_bypassed(self):
        record, draft = approved(make(is_synthetic=""))
        with mock.patch("outreach.sequence.live_export_problems", return_value=[]):
            export = seq.build_sequencing_export([record], {record.key: draft}, {record.key})
        self.assertEqual(export.rows, [])
        self.assertIn("not explicitly marked is_synthetic=false", export.guard_error)

    def test_whole_synthetic_sample_never_exports(self):
        records = sample_records()
        drafts = seq.ensure_drafts({}, records, SENDER, AS_OF)
        for record in records:
            if record.key in drafts:
                seq.approve(drafts[record.key], record)
        approved_keys = {key for key, draft in drafts.items() if draft.status == seq.APPROVED}
        self.assertEqual(len(approved_keys), 3)        # SYN-001, 013, 018 pass approval as test data
        export = seq.build_sequencing_export(records, drafts, {record.key for record in records})
        self.assertEqual(export.rows, [])
        self.assertEqual(len(export.blocked), 25)
        self.assertTrue(all(any("Synthetic test data" in p for p in problems) for _, problems in export.blocked))


class ReviewExportTest(unittest.TestCase):
    def setUp(self):
        self.records = sample_records()
        self.drafts = seq.ensure_drafts({}, self.records, SENDER, AS_OF)
        self.keys = {record.key for record in seq.builder_records(self.records, include_review=True)}

    def test_includes_every_selected_record_labelled_review_only(self):
        rows = seq.review_rows(self.records, self.drafts, self.keys, SENDER)
        self.assertEqual(len(rows), 18)
        self.assertTrue(all(r["review_only"] == seq.REVIEW_LABEL for r in rows))
        self.assertTrue(all(r["data_status"] == helpers.SYNTHETIC for r in rows))
        self.assertTrue(all(r["eligible_for_sequencing"] == "no" for r in rows))
        self.assertTrue(all("Synthetic test data" in r["eligibility_reasons"] for r in rows))
        parsed = parse_csv(seq.rows_to_csv_bytes(rows, seq.REVIEW_COLUMNS))
        self.assertEqual(list(parsed[0])[0], "review_only")

    def test_review_file_is_not_import_shaped(self):
        self.assertNotIn("email", seq.REVIEW_COLUMNS)
        self.assertNotIn("email_body", seq.REVIEW_COLUMNS)
        self.assertIn("REVIEW_ONLY", seq.REVIEW_FILENAME)

    def test_filenames(self):
        rows = seq.review_rows(self.records, self.drafts, self.keys, SENDER)
        self.assertEqual(seq.review_filename(rows), "sequence_drafts_REVIEW_ONLY_SYNTHETIC_TEST_DATA.csv")
        unverified = [dict(r, data_status=helpers.UNVERIFIED) for r in rows]
        self.assertEqual(seq.review_filename(unverified), "sequence_drafts_REVIEW_ONLY_UNVERIFIED.csv")
        mixed = [dict(rows[0], data_status=helpers.MARKED_REAL), dict(rows[1], data_status=helpers.UNVERIFIED)]
        self.assertEqual(seq.review_filename(mixed), "sequence_drafts_REVIEW_ONLY_UNVERIFIED.csv")
        real = [dict(r, data_status=helpers.MARKED_REAL) for r in rows]
        self.assertEqual(seq.review_filename(real), "sequence_drafts_REVIEW_ONLY.csv")
        self.assertEqual(seq.review_filename(rows + unverified), seq.REVIEW_FILENAME_SYNTHETIC)

    def test_missing_data_status_is_treated_as_unverified(self):
        record = make()
        bare = replace(record, result={k: v for k, v in record.result.items() if k != "data_status"})
        drafts = {bare.key: seq.new_draft(bare, SENDER, AS_OF)}
        rows = seq.review_rows([bare], drafts, {bare.key}, SENDER)
        self.assertEqual(rows[0]["data_status"], "UNVERIFIED")
        self.assertEqual(seq.review_filename(rows), seq.REVIEW_FILENAME_UNVERIFIED)

    def test_records_approval_blockers_and_outdated_sender(self):
        key = next(r.key for r in self.records if r.result["company_id"] == "SYN-019")
        rows = seq.review_rows(self.records, self.drafts, {key}, SenderSettings("Someone Else", "x", "y"))
        self.assertIn("Contact readiness is Needs Attention", rows[0]["approval_blockers"])
        self.assertEqual(rows[0]["sender_settings_outdated"], "yes")


if __name__ == "__main__":
    unittest.main()
