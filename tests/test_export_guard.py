"""sequencing_export() must fail closed: only records explicitly marked is_synthetic=false may pass."""

import unittest
from datetime import date

from scoring import SyntheticDataError, assess_record, sequencing_export
from tests.test_rules import record


def genuine(**overrides):
    return record(is_synthetic="false", **overrides)


def with_value(value, company_id="TEST-001"):
    """A Ready to Sequence result whose is_synthetic is set to an arbitrary value (or removed)."""
    result = genuine(company_id=company_id)
    if value is MISSING:
        del result["is_synthetic"]
    else:
        result["is_synthetic"] = value
    return result


MISSING = object()


class BlockedValuesTest(unittest.TestCase):
    def assertBlocked(self, value, reason):
        with self.subTest(value=value):
            with self.assertRaises(SyntheticDataError) as caught:
                sequencing_export([with_value(value)])
            self.assertIn(reason, str(caught.exception))
            self.assertIn("TEST-001", str(caught.exception))

    def test_true_is_blocked_as_synthetic(self):
        for value in ("true", "TRUE", "True", "  true  "):
            self.assertBlocked(value, "synthetic record")

    def test_missing_key_is_blocked(self):
        self.assertBlocked(MISSING, "not explicitly marked is_synthetic=false")

    def test_blank_and_whitespace_are_blocked(self):
        for value in ("", " ", "\t", "\n"):
            self.assertBlocked(value, "not explicitly marked is_synthetic=false")

    def test_null_is_blocked(self):
        self.assertBlocked(None, "not explicitly marked is_synthetic=false")

    def test_unrecognised_strings_are_blocked(self):
        for value in ("yes", "no", "0", "1", "f", "n", "n/a", "null", "none", "falsey", "not false", "false."):
            self.assertBlocked(value, "not explicitly marked is_synthetic=false")

    def test_non_string_values_are_blocked(self):
        for value in (False, True, 0, 1, ["false"]):
            self.assertBlocked(value, "not explicitly marked is_synthetic=false")


class AllowedValuesTest(unittest.TestCase):
    def test_explicit_false_is_allowed(self):
        for value in ("false", "FALSE", "False", " false "):
            with self.subTest(value=value):
                self.assertEqual(len(sequencing_export([with_value(value)])), 1)

    def test_only_ready_to_sequence_rows_are_returned(self):
        ready = genuine(company_id="READY")
        held = genuine(company_id="HELD", email_verification_status="invalid")
        excluded = genuine(company_id="EXCLUDED", employee_count_source_a="900", employee_count_source_b="1000")
        exported = sequencing_export([ready, held, excluded])
        self.assertEqual([result["company_id"] for result in exported], ["READY"])

    def test_empty_input_exports_nothing(self):
        self.assertEqual(sequencing_export([]), [])


class BatchTest(unittest.TestCase):
    def test_one_bad_record_blocks_the_whole_batch(self):
        batch = [genuine(company_id="OK-1"), with_value("", company_id="BAD-1"), genuine(company_id="OK-2")]
        with self.assertRaises(SyntheticDataError) as caught:
            sequencing_export(batch)
        message = str(caught.exception)
        self.assertIn("BAD-1", message)
        self.assertNotIn("OK-1", message)

    def test_message_separates_synthetic_and_unverified(self):
        batch = [with_value("true", company_id="SYN-A"), with_value(None, company_id="UNV-B")]
        with self.assertRaises(SyntheticDataError) as caught:
            sequencing_export(batch)
        message = str(caught.exception)
        self.assertIn("1 synthetic record(s): SYN-A", message)
        self.assertIn("1 record(s) not explicitly marked is_synthetic=false: UNV-B", message)

    def test_records_without_company_id_are_identified_by_position(self):
        batch = [genuine(company_id="OK-1"), with_value("", company_id="")]
        with self.assertRaisesRegex(SyntheticDataError, r"<record 2>"):
            sequencing_export(batch)

    def test_input_file_without_is_synthetic_column_is_blocked(self):
        row = {"company_id": "NO-COLUMN", "company_name": "No Column Co"}
        result = assess_record(row, date(2026, 10, 30))
        with self.assertRaisesRegex(SyntheticDataError, "NO-COLUMN"):
            sequencing_export([result])

    def test_whole_sample_style_batch_is_blocked(self):
        with self.assertRaises(SyntheticDataError):
            sequencing_export([record(company_id=f"SYN-{i:03d}") for i in range(1, 26)])


if __name__ == "__main__":
    unittest.main()
