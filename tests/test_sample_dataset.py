"""The 25 sample records must match the hand-derived results in fixtures/expected_results.csv (spec §E)."""

import csv
import unittest
from datetime import date
from pathlib import Path

from scoring import assess_record
from scoring.pipeline import CRITERIA, load_records
from scoring.rules import MAX_POINTS

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 10, 30)

with open(ROOT / "tests" / "fixtures" / "expected_results.csv", newline="", encoding="utf-8") as handle:
    EXPECTED = {row["company_id"]: row for row in csv.DictReader(handle)}

RECORDS = load_records(ROOT / "data" / "input" / "sample_companies.csv")
RESULTS = {row["company_id"]: assess_record(row, AS_OF) for row in RECORDS}

COMPARED = ["saas_fit_status", "size_status", "sales_function_status", "hiring_status", "outbound_status",
            "icp_score", "potential_score", "icp_outcome", "contact_readiness", "campaign_trigger_status",
            "campaign_readiness"]


class SampleDatasetTest(unittest.TestCase):

    def test_every_record_has_an_expectation(self):
        self.assertEqual(sorted(RESULTS), sorted(EXPECTED))
        self.assertEqual(len(RESULTS), 25)

    def test_records_match_expected_results(self):
        for company_id, expected in EXPECTED.items():
            result = RESULTS[company_id]
            for column in COMPARED:
                with self.subTest(company_id=company_id, column=column):
                    self.assertEqual(str(result[column]), expected[column])

    def test_scores_never_double_count(self):
        for company_id, result in RESULTS.items():
            with self.subTest(company_id=company_id):
                for name in CRITERIA:
                    points, potential = result[f"{name}_points"], result[f"{name}_potential"]
                    self.assertFalse(points and potential, f"{name} has confirmed and unresolved points")
                    self.assertLessEqual(points + potential, MAX_POINTS[name])
                self.assertEqual(result["icp_score"], sum(result[f"{n}_points"] for n in CRITERIA))
                self.assertEqual(result["potential_score"],
                                 result["icp_score"] + sum(result[f"{n}_potential"] for n in CRITERIA))
                self.assertLessEqual(result["potential_score"], 100)

    def test_test_scenario_never_influences_results(self):
        for row in RECORDS:
            for replacement in ("", "Qualified", "Disqualified: out of range"):
                with self.subTest(company_id=row["company_id"], replacement=replacement):
                    altered = dict(row, test_scenario=replacement)
                    self.assertEqual(assess_record(altered, AS_OF), RESULTS[row["company_id"]])
            self.assertNotIn("test_scenario", RESULTS[row["company_id"]])

    def test_summary_counts(self):
        def count(field, value):
            return sum(1 for result in RESULTS.values() if result[field] == value)
        self.assertEqual(count("icp_outcome", "Qualified"), 6)
        self.assertEqual(count("icp_outcome", "Review"), 12)
        self.assertEqual(count("icp_outcome", "Disqualified"), 7)
        self.assertEqual(count("campaign_readiness", "Ready to Sequence"), 3)
        self.assertEqual(count("campaign_readiness", "Hold: Trigger Research"), 1)
        self.assertEqual(count("campaign_readiness", "Hold: Contact"), 2)


if __name__ == "__main__":
    unittest.main()
