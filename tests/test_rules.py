"""Test-only fixtures for rules not covered by the sample dataset, plus rule boundaries."""

import unittest
from datetime import date

from scoring import SyntheticDataError, assess_record, sequencing_export

AS_OF = date(2026, 10, 30)


def record(**overrides):
    """A record that is Qualified, Ready and Ready to Sequence unless overridden."""
    base = {
        "company_id": "TEST-001",
        "company_name": "Fixture Co",
        "domain": "fixture.example",
        "industry": "FinTech",
        "hq_country": "US",
        "description": "Billing software for finance teams. Sold through a direct sales team.",
        "employee_count_source_a": "200",
        "employee_count_source_b": "210",
        "open_sales_roles": "1",
        "sales_role_titles": "SDR",
        "hiring_role_notes": "",
        "hiring_signal_last_seen": "2026-10-20",
        "outbound_evidence_level": "strong",
        "outbound_evidence_notes": "",
        "campaign_trigger": "",
        "campaign_trigger_date": "",
        "contact_first_name": "Test",
        "contact_last_name": "Person",
        "contact_title": "VP of Sales",
        "contact_email": "test.person@fixture.example",
        "email_verification_status": "verified",
        "is_synthetic": "true",
        "test_scenario": "fixture",
    }
    base.update(overrides)
    return assess_record(base, AS_OF)


class BaselineTest(unittest.TestCase):
    def test_baseline_fixture_is_fully_ready(self):
        result = record()
        self.assertEqual((result["icp_score"], result["potential_score"]), (100, 100))
        self.assertEqual(result["icp_outcome"], "Qualified")
        self.assertEqual(result["contact_readiness"], "Ready")
        self.assertEqual(result["campaign_readiness"], "Ready to Sequence")


class SizeTest(unittest.TestCase):
    def test_opposite_side_sources_are_a_conflict_not_out_of_range(self):
        result = record(employee_count_source_a="30", employee_count_source_b="600")
        self.assertEqual(result["size_status"], "conflict")
        self.assertIn("SIZE_CONFLICT", result["icp_flags"])
        self.assertEqual((result["size_points"], result["size_potential"]), (0, 20))
        self.assertEqual((result["icp_score"], result["potential_score"]), (80, 100))
        self.assertEqual(result["icp_outcome"], "Review")

    def test_opposite_side_conflict_with_weak_evidence_uses_normal_logic(self):
        result = record(employee_count_source_a="30", employee_count_source_b="600",
                        description="Billing software for finance teams. Sold online with no sales team.",
                        open_sales_roles="0", sales_role_titles="", hiring_signal_last_seen="",
                        outbound_evidence_level="none")
        self.assertEqual((result["icp_score"], result["potential_score"]), (30, 50))
        self.assertEqual(result["icp_outcome"], "Disqualified")
        self.assertIn("LOW_SCORE", result["icp_flags"])
        self.assertNotIn("SIZE_OUT_OF_RANGE", result["icp_flags"])

    def test_single_source_outside_range_is_unresolved_not_disqualified(self):
        result = record(employee_count_source_a="2000", employee_count_source_b="")
        self.assertEqual(result["size_status"], "single_source")
        self.assertEqual(result["size_indication"], "likely_out_of_range")
        self.assertEqual((result["size_points"], result["size_potential"]), (0, 20))
        self.assertEqual(result["icp_outcome"], "Review")

    def test_single_source_inside_range_earns_no_confirmed_points(self):
        result = record(employee_count_source_a="", employee_count_source_b="200")
        self.assertEqual(result["size_indication"], "likely_in_range")
        self.assertEqual((result["icp_score"], result["potential_score"]), (80, 100))
        self.assertEqual(result["icp_outcome"], "Review")
        self.assertIn("BLOCKED_FROM_QUALIFIED", result["icp_flags"])

    def test_range_boundaries_are_inclusive(self):
        for low, high, status in [("50", "50", "confirmed_in_range"), ("500", "500", "confirmed_in_range"),
                                  ("49", "49", "confirmed_out_of_range"), ("501", "501", "confirmed_out_of_range"),
                                  ("49", "50", "conflict"), ("500", "501", "conflict")]:
            with self.subTest(sources=(low, high)):
                self.assertEqual(record(employee_count_source_a=low, employee_count_source_b=high)["size_status"],
                                 status)

    def test_confirmed_out_of_range_disqualifies_regardless_of_score(self):
        result = record(employee_count_source_a="600", employee_count_source_b="900")
        self.assertEqual(result["icp_outcome"], "Disqualified")
        self.assertIn("SIZE_OUT_OF_RANGE", result["icp_flags"])

    def test_unknown_size_blocks_qualified(self):
        result = record(employee_count_source_a="", employee_count_source_b="")
        self.assertEqual(result["size_status"], "unknown")
        self.assertEqual(result["icp_outcome"], "Review")


class SaasFitTest(unittest.TestCase):
    def test_unclear_fit_at_score_70_is_blocked_from_qualified(self):
        result = record(description="No-code form builder with approval workflows. Sold through a direct sales team.")
        self.assertEqual(result["saas_fit_status"], "unclear")
        self.assertEqual((result["icp_score"], result["potential_score"]), (70, 100))
        self.assertEqual(result["icp_outcome"], "Review")
        self.assertIn("BLOCKED_FROM_QUALIFIED", result["icp_flags"])

    def test_mixed_saas_and_non_saas_signals_are_unclear_not_disqualified(self):
        result = record(description="Agency and scheduling software for clinics.")
        self.assertEqual(result["saas_fit_status"], "unclear")
        self.assertNotEqual(result["icp_outcome"], "Disqualified")

    def test_confirmed_non_saas_is_disqualified(self):
        result = record(description="Consulting services agency for small businesses.")
        self.assertEqual(result["saas_fit_status"], "not_saas")
        self.assertEqual(result["icp_outcome"], "Disqualified")
        self.assertIn("SAAS_NOT_FIT", result["icp_flags"])

    def test_industry_alone_earns_no_points(self):
        result = record(description="", industry="B2B SaaS")
        self.assertEqual(result["saas_fit_status"], "unknown")
        self.assertEqual(result["saas_fit_points"], 0)


class SalesFunctionTest(unittest.TestCase):
    def test_customer_sales_wording_is_not_own_sales_function(self):
        result = record(description="CRM software for field sales teams.")
        self.assertEqual(result["sales_function_status"], "unknown")
        self.assertEqual(result["sales_function_potential"], 20)

    def test_contradictory_description_is_unknown(self):
        result = record(description="Billing software for finance teams with an inside sales team and no sales team.")
        self.assertEqual(result["sales_function_status"], "unknown")

    def test_explicit_absence_has_no_potential(self):
        result = record(description="Billing software for finance teams. Self-serve only.")
        self.assertEqual(result["sales_function_status"], "confirmed_absent")
        self.assertEqual((result["sales_function_points"], result["sales_function_potential"]), (0, 0))


class HiringTest(unittest.TestCase):
    def test_ninety_day_recency_boundary(self):
        self.assertEqual(record(hiring_signal_last_seen="2026-08-01")["hiring_status"], "current")   # 90 days
        self.assertEqual(record(hiring_signal_last_seen="2026-07-31")["hiring_status"], "stale")     # 91 days

    def test_not_researched_differs_from_confirmed_none(self):
        unknown = record(open_sales_roles="", sales_role_titles="", hiring_signal_last_seen="")
        none = record(open_sales_roles="0", sales_role_titles="", hiring_signal_last_seen="")
        self.assertEqual((unknown["hiring_status"], unknown["hiring_potential"]), ("unknown", 20))
        self.assertEqual((none["hiring_status"], none["hiring_potential"]), ("confirmed_none", 0))

    def test_relevant_titles(self):
        for title in ("SDR", "Sales Development Representative", "BDR", "Business Development Representative",
                      "Account Executive", "Enterprise Account Executive", "Sales Engineer",
                      "Sales Development Manager"):
            with self.subTest(title=title):
                self.assertEqual(record(sales_role_titles=title)["hiring_status"], "current")

    def test_irrelevant_titles(self):
        for title in ("Customer Success Manager", "RevOps Analyst", "Revenue Operations Manager"):
            with self.subTest(title=title):
                self.assertEqual(record(sales_role_titles=title)["hiring_status"], "confirmed_none")

    def test_solutions_consultant_depends_on_notes(self):
        cases = [("", "role_unverified"),
                 ("Owns prospecting and a quarterly quota", "current"),
                 ("Post-sale onboarding and training", "confirmed_none")]
        for notes, status in cases:
            with self.subTest(notes=notes):
                result = record(sales_role_titles="Solutions Consultant", hiring_role_notes=notes)
                self.assertEqual(result["hiring_status"], status)


class OutboundTest(unittest.TestCase):
    def test_invalid_value_is_unknown_and_flagged(self):
        result = record(outbound_evidence_level="high")
        self.assertEqual(result["outbound_status"], "unknown")
        self.assertEqual((result["outbound_points"], result["outbound_potential"]), (0, 10))
        self.assertIn("DATA_INVALID_OUTBOUND", result["icp_flags"])

    def test_unknown_is_not_none(self):
        unknown, none = record(outbound_evidence_level="unknown"), record(outbound_evidence_level="none")
        self.assertEqual(unknown["icp_score"], none["icp_score"])
        self.assertEqual(unknown["potential_score"], none["potential_score"] + 10)
        self.assertIn("OUTBOUND_UNKNOWN", unknown["icp_flags"])
        self.assertNotIn("OUTBOUND_UNKNOWN", none["icp_flags"])


class ContactTest(unittest.TestCase):
    def test_email_status_never_changes_icp(self):
        baseline = record()
        for status, readiness in [("verified", "Ready"), ("unverified", "Needs Attention"),
                                  ("catch_all", "Needs Attention"), ("risky", "Not Ready"),
                                  ("invalid", "Not Ready")]:
            with self.subTest(status=status):
                result = record(email_verification_status=status)
                self.assertEqual(result["contact_readiness"], readiness)
                for field in ("icp_score", "potential_score", "icp_outcome"):
                    self.assertEqual(result[field], baseline[field])

    def test_missing_email_and_missing_contact(self):
        self.assertEqual(record(contact_email="", email_verification_status="")["contact_readiness"], "Not Ready")
        missing = record(contact_first_name="", contact_last_name="", contact_title="", contact_email="",
                         email_verification_status="")
        self.assertIn("CONTACT_MISSING", missing["contact_flags"])

    def test_persona_mismatch_needs_attention(self):
        result = record(contact_title="Office Manager")
        self.assertEqual(result["contact_readiness"], "Needs Attention")
        self.assertIn("PERSONA_MISMATCH", result["contact_flags"])


class CampaignTest(unittest.TestCase):
    no_hiring = {"open_sales_roles": "0", "sales_role_titles": "", "hiring_signal_last_seen": ""}

    def test_strong_outbound_is_not_a_trigger(self):
        result = record(**self.no_hiring)
        self.assertEqual(result["icp_outcome"], "Qualified")
        self.assertEqual(result["campaign_trigger_status"], "none")
        self.assertEqual(result["campaign_readiness"], "Hold: Trigger Research")

    def test_current_documented_trigger(self):
        result = record(**self.no_hiring, campaign_trigger="New VP of Sales hired", campaign_trigger_date="2026-08-01")
        self.assertEqual(result["campaign_trigger_status"], "documented")
        self.assertEqual(result["campaign_readiness"], "Ready to Sequence")

    def test_stale_documented_trigger(self):
        result = record(**self.no_hiring, campaign_trigger="Series A funding", campaign_trigger_date="2026-07-01")
        self.assertEqual(result["campaign_trigger_status"], "stale")
        self.assertEqual(result["campaign_readiness"], "Hold: Trigger Research")

    def test_all_blockers_are_listed(self):
        result = record(**self.no_hiring, email_verification_status="invalid")
        self.assertEqual(result["campaign_readiness"], "Hold: Contact")
        self.assertIn("No current campaign trigger", result["campaign_reasons"])

    def test_campaign_never_changes_icp(self):
        self.assertEqual(record(**self.no_hiring, email_verification_status="invalid")["icp_outcome"], "Qualified")


class ExportGuardTest(unittest.TestCase):
    def test_synthetic_rows_cannot_be_exported(self):
        with self.assertRaises(SyntheticDataError):
            sequencing_export([record()])

    def test_real_rows_pass_through(self):
        self.assertEqual(len(sequencing_export([record(is_synthetic="false")])), 1)


if __name__ == "__main__":
    unittest.main()
