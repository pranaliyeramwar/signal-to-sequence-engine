"""First-touch generator: only current, dated, traceable evidence; deterministic; no invented claims."""

import unittest
from datetime import date

from outreach.first_touch import (PLACEHOLDER_CTA, PLACEHOLDER_FIRST_NAME, PLACEHOLDER_SENDER,
                                  PLACEHOLDER_VALUE, SenderSettings, find_placeholders, generate, word_count)
from ui import helpers

AS_OF = date(2026, 10, 30)
SENDER = SenderSettings(
    "Jordan Example",
    "We help revenue teams turn new sales hires into productive pipeline faster, with onboarding playbooks "
    "and call coaching built around the accounts each rep owns.",
    "Would a short call next week be useful to see whether this fits how your team ramps new reps?")


def row(**overrides):
    base = {
        "company_id": "GEN-001", "company_name": "Fixture Co", "domain": "fixture.example", "industry": "FinTech",
        "hq_country": "US",
        "description": "Billing software for finance teams. Sold through a direct sales team.",
        "employee_count_source_a": "200", "employee_count_source_b": "210",
        "open_sales_roles": "1", "sales_role_titles": "SDR", "hiring_role_notes": "",
        "hiring_signal_last_seen": "2026-10-20", "outbound_evidence_level": "strong",
        "outbound_evidence_notes": "Active SDR team running sequences", "campaign_trigger": "",
        "campaign_trigger_date": "", "contact_first_name": "Test", "contact_last_name": "Person",
        "contact_title": "VP of Sales", "contact_email": "test.person@fixture.example",
        "email_verification_status": "verified", "is_synthetic": "false", "test_scenario": "fixture",
    }
    base.update(overrides)
    return base


def draft_for(sender=SENDER, **overrides):
    data = row(**overrides)
    result = helpers.score_rows([data], AS_OF)[0]
    return generate(data, result, sender, AS_OF)


class HiringEvidenceTest(unittest.TestCase):
    def test_names_only_roles_the_engine_recognises(self):
        draft = draft_for(open_sales_roles="4",
                          sales_role_titles="SDR|RevOps Analyst|Customer Success Manager|Account Executive")
        self.assertIn("hiring for SDR and Account Executive roles", draft.body)
        for excluded in ("RevOps", "Customer Success"):
            self.assertNotIn(excluded, draft.body + draft.personalization_reason)

    def test_single_role_uses_correct_article(self):
        for title, phrase in [("SDR", "an SDR role"), ("BDR", "a BDR role"),
                              ("Account Executive", "an Account Executive role"),
                              ("Sales Development Manager", "a Sales Development Manager role")]:
            with self.subTest(title=title):
                self.assertIn(phrase, draft_for(sales_role_titles=title).body)

    def test_evidence_is_dated_and_traceable(self):
        draft = draft_for()
        evidence = draft.evidence[0]
        self.assertEqual((evidence.kind, evidence.summary, evidence.date, evidence.age_days),
                         ("hiring", "SDR", "2026-10-20", 10))
        self.assertIn("sales_role_titles", evidence.source_fields)
        self.assertIn("hiring_signal_last_seen", evidence.source_fields)
        self.assertEqual(draft.personalization_reason, "Hiring: SDR (last seen 2026-10-20, 10 days before 2026-10-30)")

    def test_stale_hiring_is_not_evidence(self):
        self.assertTrue(draft_for(hiring_signal_last_seen="2026-07-01").needs_research)

    def test_undated_hiring_is_not_evidence(self):
        self.assertTrue(draft_for(hiring_signal_last_seen="").needs_research)

    def test_future_dated_hiring_is_not_evidence(self):
        self.assertTrue(draft_for(hiring_signal_last_seen="2026-11-15").needs_research)

    def test_irrelevant_roles_only_are_not_evidence(self):
        self.assertTrue(draft_for(sales_role_titles="Customer Success Manager").needs_research)

    def test_solutions_consultant_only_when_engine_counts_it(self):
        counted = draft_for(sales_role_titles="Solutions Consultant",
                            hiring_role_notes="Owns new-business pipeline and quota")
        self.assertIn("a Solutions Consultant role", counted.body)
        self.assertTrue(draft_for(sales_role_titles="Solutions Consultant", hiring_role_notes="").needs_research)


class TriggerEvidenceTest(unittest.TestCase):
    no_hiring = {"open_sales_roles": "0", "sales_role_titles": "", "hiring_signal_last_seen": ""}

    def test_uses_documented_trigger_text_and_date(self):
        draft = draft_for(**self.no_hiring, campaign_trigger="Series B funding announced",
                          campaign_trigger_date="2026-10-06")
        self.assertIn("update from 6 October 2026: Series B funding announced.", draft.body)
        self.assertEqual(draft.evidence[0].kind, "trigger")
        self.assertIn("dated 2026-10-06", draft.personalization_reason)

    def test_stale_future_and_undated_triggers_are_not_evidence(self):
        for trigger_date in ("2026-07-01", "2026-12-01", "", "not-a-date"):
            with self.subTest(trigger_date=trigger_date):
                self.assertTrue(draft_for(**self.no_hiring, campaign_trigger="Series B funding announced",
                                          campaign_trigger_date=trigger_date).needs_research)

    def test_hiring_and_trigger_are_both_recorded(self):
        draft = draft_for(campaign_trigger="New VP of Sales hired", campaign_trigger_date="2026-10-01")
        self.assertEqual([e.kind for e in draft.evidence], ["hiring", "trigger"])
        self.assertIn("Hiring:", draft.personalization_reason)
        self.assertIn("Documented trigger:", draft.personalization_reason)


class NoInventionTest(unittest.TestCase):
    def test_no_evidence_means_needs_research_without_an_opener(self):
        draft = draft_for(open_sales_roles="0", sales_role_titles="", hiring_signal_last_seen="")
        self.assertTrue(draft.needs_research)
        self.assertEqual((draft.subject, draft.body, draft.personalization_reason, draft.evidence), ("", "", "", ()))

    def test_outbound_and_description_are_never_used(self):
        draft = draft_for()
        text = (draft.subject + draft.body).lower()
        for phrase in ("outbound", "sequence", "billing software", "direct sales team", "priority", "struggl"):
            self.assertNotIn(phrase, text)

    def test_strong_outbound_alone_is_not_evidence(self):
        self.assertTrue(draft_for(open_sales_roles="0", sales_role_titles="", hiring_signal_last_seen="",
                                  outbound_evidence_level="strong").needs_research)

    def test_generation_is_deterministic(self):
        self.assertEqual(draft_for(), draft_for())


class SenderAndWordCountTest(unittest.TestCase):
    def test_missing_sender_settings_leave_placeholders(self):
        draft = draft_for(sender=SenderSettings())
        for placeholder in (PLACEHOLDER_VALUE, PLACEHOLDER_CTA):
            self.assertIn(placeholder, draft.body)
        self.assertIn(PLACEHOLDER_SENDER, draft.signature)
        self.assertFalse(SenderSettings("a", "b", " ").is_complete())
        self.assertTrue(SENDER.is_complete())

    def test_missing_first_name_leaves_a_placeholder(self):
        self.assertIn(PLACEHOLDER_FIRST_NAME, draft_for(contact_first_name="").greeting)

    def test_word_count_excludes_greeting_and_signature(self):
        draft = draft_for()
        self.assertEqual(word_count(draft.body), 9 + 25 + 19)     # opener + value proposition + call to action
        self.assertNotIn("Hi", draft.body)
        self.assertNotIn("Jordan", draft.body)

    def test_placeholder_detection(self):
        self.assertEqual(find_placeholders("Hi {first name}, see [insert stat]."), ["{first name}", "[insert stat]"])
        self.assertEqual(find_placeholders("No placeholders here."), [])


if __name__ == "__main__":
    unittest.main()
