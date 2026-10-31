"""Spreadsheet formula-injection protection for every CSV download, and the localhost-only server config."""

import csv
import io
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from outreach import sequence as seq
from scoring import assess_record
from scoring.pipeline import write_results
from tests.test_first_touch import AS_OF, SENDER
from tests.test_sequence_builder import FIFTY_FIVE_WORDS, make, sample_records
from ui import helpers
from ui.csv_safety import is_dangerous, neutralise_cell

ROOT = Path(__file__).resolve().parent.parent

DANGEROUS = [
    "=1+1", "+1", "-1", "@SUM(A1:A9)", '=HYPERLINK("http://evil.example","click")', "=cmd|' /C calc'!A0",
    " =1+1", "   @SUM(A1)", "\t=1+1", "\r=1+1", "\n=1+1", "\x00=1+1", "\x1b-1", " =1",
    "​=1+1", "﻿@SUM(A1)", " \t\r\n+1",
    "＝1+1", "＋1", "－1", "＠SUM(A1)",          # full-width = + - @
    "\t", "\tplain text after a tab", "\rplain text after a carriage return",
    "-", "=", "@",
]
SAFE = [
    "", " ", "Hello", "Hi Talia,", "Sales hiring at Brightloop Analytics", "SDR - Account Executive",
    "a=b", "1+1", "x@y.example", "talia.brennick@brightloop.example", "https://www.linkedin.com/in/supplied",
    "100", "Series B funding announced (2026-10-06)", "REVIEW ONLY - NOT A SEQUENCING IMPORT",
    "SYNTHETIC TEST DATA", "Ready to Sequence", " leading space then text", "\nHi (newline then text)",
]


def parse(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


class NeutraliseCellTest(unittest.TestCase):
    def test_dangerous_values_are_prefixed_and_keep_their_original_text(self):
        for value in DANGEROUS:
            with self.subTest(value=value):
                self.assertTrue(is_dangerous(value))
                self.assertEqual(neutralise_cell(value), "'" + value)

    def test_safe_values_are_unchanged(self):
        for value in SAFE:
            with self.subTest(value=value):
                self.assertFalse(is_dangerous(value))
                self.assertEqual(neutralise_cell(value), value)

    def test_non_text_values_are_unchanged(self):
        for value in (None, 0, 42, -5, 3.5, True):
            with self.subTest(value=value):
                self.assertIs(neutralise_cell(value), value)

    def test_already_neutralised_text_is_not_double_prefixed(self):
        self.assertEqual(neutralise_cell("'=1+1"), "'=1+1")


class ScoredCsvTest(unittest.TestCase):
    def test_scored_report_neutralises_user_text_and_keeps_safety_columns(self):
        rows = helpers.parse_csv_bytes((ROOT / "data" / "input" / "sample_companies.csv").read_bytes()).rows
        rows[0] = dict(rows[0], company_name="=HYPERLINK(\"http://evil.example\",\"x\")",
                       sales_role_titles="@SDR|Account Executive")
        results = helpers.score_rows(rows, AS_OF)
        report = parse(helpers.results_to_csv_bytes(results))
        self.assertEqual(report[0]["company_name"], "'=HYPERLINK(\"http://evil.example\",\"x\")")
        self.assertEqual(results[0]["company_name"], "=HYPERLINK(\"http://evil.example\",\"x\")")   # unchanged in app
        self.assertTrue(all(row["is_synthetic"] == "true" for row in report))
        self.assertTrue(all(row["data_status"] == helpers.SYNTHETIC for row in report))
        self.assertEqual(report[1]["company_name"], results[1]["company_name"])                    # ordinary text

    def test_every_cell_in_the_sample_report_is_safe(self):
        rows = helpers.parse_csv_bytes((ROOT / "data" / "input" / "sample_companies.csv").read_bytes()).rows
        for row in parse(helpers.results_to_csv_bytes(helpers.score_rows(rows, AS_OF))):
            for column, value in row.items():
                with self.subTest(column=column):
                    self.assertFalse(is_dangerous(value))


class SequenceExportCsvTest(unittest.TestCase):
    malicious = {
        "company_name": "=1+1",
        "contact_first_name": "+Test",
        "contact_last_name": "@Person",
        "contact_title": "-VP of Sales",
        "contact_linkedin_url": '=HYPERLINK("http://evil.example","profile")',
        "campaign_trigger": "",
    }

    def setUp(self):
        self.record = make(**self.malicious)
        self.draft = seq.new_draft(self.record, SENDER, AS_OF)
        seq.edit_draft(self.draft, subject="=SUBJECT()", body="@" + FIFTY_FIVE_WORDS,
                       personalization_reason="\t-reason")
        self.assertEqual(seq.approve(self.draft, self.record), [])
        self.drafts = {self.record.key: self.draft}

    def test_sequencing_csv_neutralises_every_user_controlled_field(self):
        export = seq.build_sequencing_export([self.record], self.drafts, {self.record.key})
        self.assertEqual(len(export.rows), 1)
        out = parse(seq.rows_to_csv_bytes(export.rows, seq.SEQUENCING_COLUMNS))[0]
        expected = {
            "company_name": "'=1+1", "contact_name": "'+Test @Person", "job_title": "'-VP of Sales",
            "subject": "'=SUBJECT()", "linkedin_url": "'" + self.malicious["contact_linkedin_url"],
            "personalization_reason": "'-reason",      # the Sequencing CSV trims whitespace; "-" is still caught
        }
        for column, value in expected.items():
            with self.subTest(column=column):
                self.assertEqual(out[column], value)
        self.assertTrue(out["email_body"].startswith("Hi +Test,"))   # starts with "Hi", so left unchanged
        self.assertEqual(out["email"], "test.person@fixture.example")

    def test_draft_review_csv_neutralises_every_user_controlled_field(self):
        rows = seq.review_rows([self.record], self.drafts, {self.record.key}, SENDER)
        out = parse(seq.rows_to_csv_bytes(rows, seq.REVIEW_COLUMNS))[0]
        for column in ("company_name", "contact_name", "contact_title", "subject", "personalization_reason"):
            with self.subTest(column=column):
                self.assertTrue(out[column].startswith("'"), out[column])
        self.assertEqual(out["personalization_reason"], "'\t-reason")    # untrimmed here: leading tab caught
        self.assertEqual(out["review_only"], seq.REVIEW_LABEL)

    def test_original_text_is_preserved_inside_the_application(self):
        seq.rows_to_csv_bytes(seq.build_sequencing_export([self.record], self.drafts, {self.record.key}).rows,
                              seq.SEQUENCING_COLUMNS)
        self.assertEqual(self.draft.subject, "=SUBJECT()")
        self.assertEqual(self.draft.personalization_reason, "\t-reason")
        self.assertEqual(self.record.row["company_name"], "=1+1")
        export = seq.build_sequencing_export([self.record], self.drafts, {self.record.key})
        self.assertEqual(export.rows[0]["subject"], "=SUBJECT()")        # rows are neutralised only when written

    def test_ordinary_sample_exports_are_unchanged(self):
        records = sample_records()
        drafts = seq.ensure_drafts({}, records, SENDER, AS_OF)
        keys = {r.key for r in seq.builder_records(records, include_review=True)}
        rows = seq.review_rows(records, drafts, keys, SENDER)
        parsed = parse(seq.rows_to_csv_bytes(rows, seq.REVIEW_COLUMNS))
        for original, written in zip(rows, parsed):
            for column in seq.REVIEW_COLUMNS:
                with self.subTest(company=original["company_id"], column=column):
                    self.assertEqual(written[column], str(original[column]))


class CliCsvTest(unittest.TestCase):
    """python -m scoring writes data through scoring.pipeline.write_results()."""

    dangerous_names = ["=1+1", " =HYPERLINK(\"http://evil.example\",\"x\")", "\t@SUM(A1)", "+44 Ltd", "-Dash Co",
                       "​=1", "＝Fullwidth"]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rows = helpers.parse_csv_bytes((ROOT / "data" / "input" / "sample_companies.csv").read_bytes()).rows
        for index, name in enumerate(self.dangerous_names):
            self.rows[index] = dict(self.rows[index], company_name=name)
        self.rows[len(self.dangerous_names)] = dict(self.rows[len(self.dangerous_names)], company_id="@SYN-X")

    def score(self):
        return [assess_record(row, AS_OF) for row in self.rows]

    def written(self, results):
        path = Path(self.temp.name) / "scored.csv"
        write_results(results, path)
        with open(path, newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle)), path.read_bytes()

    def test_dangerous_prefixes_are_neutralised_in_the_file(self):
        rows, _ = self.written(self.score())
        for index, name in enumerate(self.dangerous_names):
            with self.subTest(name=name):
                self.assertEqual(rows[index]["company_name"], "'" + name)
        self.assertEqual(rows[len(self.dangerous_names)]["company_id"], "'@SYN-X")

    def test_ordinary_values_are_written_unchanged(self):
        results = self.score()
        rows, _ = self.written(results)
        for result, row in list(zip(results, rows))[len(self.dangerous_names) + 1:]:
            for column, value in result.items():
                with self.subTest(company=result["company_id"], column=column):
                    self.assertEqual(row[column], str(value))

    def test_results_in_memory_are_not_modified(self):
        results = self.score()
        before = [dict(result) for result in results]
        self.written(results)
        self.assertEqual(results, before)
        self.assertEqual(results[0]["company_name"], "=1+1")

    def test_columns_line_endings_and_safety_column_are_preserved(self):
        results = self.score()
        rows, raw = self.written(results)
        self.assertEqual(list(rows[0]), list(results[0]))
        self.assertTrue(raw.splitlines(keepends=True)[0].endswith(b"\r\n"))     # csv module default, as before
        self.assertTrue(all(row["is_synthetic"] == "true" for row in rows))

    def test_command_line_end_to_end(self):
        source = Path(self.temp.name) / "input.csv"
        output = Path(self.temp.name) / "output.csv"
        header = list(self.rows[0])
        with open(source, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=header)
            writer.writeheader()
            writer.writerows(self.rows)
        completed = subprocess.run([sys.executable, "-m", "scoring", "--input", str(source), "--output", str(output),
                                    "--as-of", AS_OF.isoformat()], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        with open(output, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["company_name"], "'=1+1")
        self.assertEqual(rows[len(self.dangerous_names)]["company_id"], "'@SYN-X")
        self.assertEqual(rows[-1]["company_name"], "Umberline Insurance Tech")
        self.assertIn("icp_outcome: Disqualified 7, Qualified 6, Review 12", completed.stdout)


class ServerConfigTest(unittest.TestCase):
    def test_streamlit_binds_to_localhost_only(self):
        config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["server"]["address"], "127.0.0.1")

    def test_security_defaults_are_not_weakened(self):
        server = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["server"]
        self.assertNotIn("enableXsrfProtection", server)     # Streamlit default: enabled
        self.assertNotIn("enableCORS", server)               # Streamlit default: enabled
        self.assertNotIn("headless", server)


if __name__ == "__main__":
    unittest.main()
