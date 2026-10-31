"""Tests for ui/helpers.py. These run without Streamlit installed."""

import csv
import io
import unittest
from datetime import date
from pathlib import Path

from scoring import SyntheticDataError, assess_record, sequencing_export
from ui import helpers

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (ROOT / "data" / "input" / "sample_companies.csv").read_bytes()
AS_OF = date(2026, 10, 30)


def csv_bytes(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def sample_without(column):
    parsed = helpers.parse_csv_bytes(SAMPLE)
    header = [name for name in parsed.header if name != column]
    return csv_bytes(header, [[row[name] for name in header] for row in parsed.rows])


class ParseUploadTest(unittest.TestCase):
    def test_sample_dataset_parses(self):
        parsed = helpers.parse_csv_bytes(SAMPLE)
        self.assertEqual(parsed.errors, [])
        self.assertEqual(len(parsed.rows), 25)

    def test_byte_order_mark_is_stripped(self):
        parsed = helpers.parse_csv_bytes(b"\xef\xbb\xbf" + SAMPLE)
        self.assertEqual(parsed.header[0], "company_id")

    def test_empty_and_whitespace_files(self):
        for data in (b"", b"   \n\n"):
            with self.subTest(data=data):
                self.assertIn("The file is empty.", helpers.parse_csv_bytes(data).errors)

    def test_header_only(self):
        parsed = helpers.parse_csv_bytes(b"company_id,company_name\n")
        self.assertTrue(any("no data rows" in error for error in parsed.errors))

    def test_non_utf8_file(self):
        parsed = helpers.parse_csv_bytes("company_id,company_name\nSYN-1,Caf\xe9\n".encode("latin-1"))
        self.assertTrue(any("not UTF-8" in error for error in parsed.errors))

    def test_binary_file(self):
        parsed = helpers.parse_csv_bytes(b"PK\x03\x04\x00\x00binary")
        self.assertTrue(parsed.errors)
        self.assertEqual(parsed.rows, [])

    def test_ragged_rows_are_rejected_with_line_numbers(self):
        parsed = helpers.parse_csv_bytes(b"a,b,c\n1,2,3\n1,2\n1,2,3,4\n")
        self.assertEqual(parsed.rows, [])
        self.assertTrue(any("Line 3 has 2 fields" in error for error in parsed.errors))
        self.assertTrue(any("Line 4 has 4 fields" in error for error in parsed.errors))

    def test_blank_and_duplicate_header_names(self):
        self.assertTrue(helpers.parse_csv_bytes(b"a,,c\n1,2,3\n").errors)
        parsed = helpers.parse_csv_bytes(b"a,a,c\n1,2,3\n")
        self.assertTrue(any("repeats column names: a" in error for error in parsed.errors))

    def test_blank_lines_are_ignored(self):
        parsed = helpers.parse_csv_bytes(b"a,b\n\n1,2\n\n")
        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.rows, [{"a": "1", "b": "2"}])


class ColumnCheckTest(unittest.TestCase):
    def test_sample_has_every_column(self):
        check = helpers.check_columns(helpers.parse_csv_bytes(SAMPLE).header)
        self.assertEqual((check.missing_required, check.missing_optional, check.unrecognised), ([], {}, []))

    def test_missing_required_column_is_reported(self):
        check = helpers.check_columns(helpers.parse_csv_bytes(sample_without("description")).header)
        self.assertEqual(check.missing_required, ["description"])

    def test_missing_optional_column_is_a_warning(self):
        check = helpers.check_columns(helpers.parse_csv_bytes(sample_without("contact_email")).header)
        self.assertEqual(check.missing_required, [])
        self.assertIn("contact_email", check.missing_optional)

    def test_unrecognised_columns_are_listed(self):
        self.assertEqual(helpers.check_columns(helpers.REQUIRED_COLUMNS + ["notes"]).unrecognised, ["notes"])

    def test_row_warnings(self):
        rows = [{"company_id": "A"}, {"company_id": "A"}, {"company_id": " "}]
        warnings = helpers.row_warnings(rows)
        self.assertTrue(any("no company_id" in warning for warning in warnings))
        self.assertTrue(any("Duplicate company_id values: A" in warning for warning in warnings))


class EngineReuseTest(unittest.TestCase):
    def test_scores_are_exactly_the_engine_output(self):
        rows = helpers.parse_csv_bytes(SAMPLE).rows
        for row, result in zip(rows, helpers.score_rows(rows, AS_OF)):
            engine = assess_record(row, AS_OF)
            self.assertEqual({key: value for key, value in result.items() if key != "data_status"}, engine)

    def test_counts_match_the_approved_expectations(self):
        results = helpers.score_rows(helpers.parse_csv_bytes(SAMPLE).rows, AS_OF)
        self.assertEqual(helpers.count_by(results, "icp_outcome", helpers.ICP_OUTCOMES),
                         {"Qualified": 6, "Review": 12, "Disqualified": 7})
        self.assertEqual(helpers.count_by(results, "campaign_readiness", helpers.CAMPAIGN_OUTCOMES)
                         ["Ready to Sequence"], 3)


class SafetyLabelTest(unittest.TestCase):
    def setUp(self):
        self.results = helpers.score_rows(helpers.parse_csv_bytes(SAMPLE).rows, AS_OF)

    def test_data_status_values(self):
        self.assertEqual(helpers.data_status({"is_synthetic": "true"}), helpers.SYNTHETIC)
        self.assertEqual(helpers.data_status({"is_synthetic": "TRUE "}), helpers.SYNTHETIC)
        self.assertEqual(helpers.data_status({"is_synthetic": "false"}), helpers.MARKED_REAL)
        for value in ({}, {"is_synthetic": ""}, {"is_synthetic": "yes"}):
            with self.subTest(value=value):
                self.assertEqual(helpers.data_status(value), helpers.UNVERIFIED)

    def test_synthetic_download_keeps_its_safety_label(self):
        self.assertEqual(helpers.download_filename(self.results), "scored_companies_SYNTHETIC_TEST_DATA.csv")
        report = list(csv.DictReader(io.StringIO(helpers.results_to_csv_bytes(self.results).decode("utf-8"))))
        self.assertEqual(len(report), 25)
        self.assertTrue(all(row["is_synthetic"] == "true" for row in report))
        self.assertTrue(all(row["data_status"] == helpers.SYNTHETIC for row in report))

    def test_mixed_file_still_gets_the_synthetic_filename(self):
        mixed = self.results[:1] + [dict(self.results[1], data_status=helpers.MARKED_REAL)]
        self.assertEqual(helpers.download_filename(mixed), helpers.FILENAME_SYNTHETIC)

    def test_missing_is_synthetic_column_is_unverified(self):
        rows = helpers.parse_csv_bytes(sample_without("is_synthetic")).rows
        results = helpers.score_rows(rows, AS_OF)
        self.assertTrue(all(result["data_status"] == helpers.UNVERIFIED for result in results))
        self.assertEqual(helpers.download_filename(results), helpers.FILENAME_UNVERIFIED)

    def test_only_rows_marked_false_get_the_plain_filename(self):
        marked = [dict(result, data_status=helpers.MARKED_REAL) for result in self.results]
        self.assertEqual(helpers.download_filename(marked), helpers.FILENAME_DEFAULT)

    def test_ready_to_sequence_is_never_shown_as_a_real_prospect(self):
        ready = [result for result in self.results if result["campaign_readiness"] == "Ready to Sequence"]
        self.assertEqual(len(ready), 3)
        for result in ready:
            self.assertIn("not a real prospect", helpers.campaign_display(result))
        unverified = dict(ready[0], data_status=helpers.UNVERIFIED)
        self.assertIn("unverified data", helpers.campaign_display(unverified))

    def test_sequencing_export_still_refuses_synthetic_rows(self):
        with self.assertRaises(SyntheticDataError):
            sequencing_export(self.results)


class FilterTest(unittest.TestCase):
    def setUp(self):
        self.results = helpers.score_rows(helpers.parse_csv_bytes(SAMPLE).rows, AS_OF)

    def ids(self, **filters):
        return [result["company_id"] for result in helpers.filter_results(self.results, **filters)]

    def test_no_filters_returns_everything(self):
        self.assertEqual(len(self.ids()), 25)

    def test_search_matches_id_or_name_case_insensitively(self):
        self.assertEqual(self.ids(search="syn-001"), ["SYN-001"])
        self.assertEqual(self.ids(search="brightloop"), ["SYN-001"])

    def test_outcome_filters_combine(self):
        self.assertEqual(self.ids(icp=["Qualified"], campaign=["Ready to Sequence"]), ["SYN-001", "SYN-013", "SYN-018"])
        self.assertEqual(self.ids(icp=["Qualified"], contact=["Needs Attention"]), ["SYN-019", "SYN-020"])

    def test_flag_filter(self):
        self.assertEqual(self.ids(flags=["SIZE_CONFLICT"]), ["SYN-008", "SYN-009", "SYN-025"])
        self.assertIn("EMAIL_INVALID", helpers.all_flags(self.results))

    def test_breakdown_reads_engine_fields(self):
        result = next(r for r in self.results if r["company_id"] == "SYN-002")
        size = next(row for row in helpers.criterion_breakdown(result) if row["Criterion"] == "Employee count")
        self.assertEqual((size["Status"], size["Confirmed points"], size["Unresolved (potential)"], size["Max"]),
                         ("single_source", 0, 20, 20))
        self.assertEqual(sum(row["Max"] for row in helpers.criterion_breakdown(result)), 100)


if __name__ == "__main__":
    unittest.main()
