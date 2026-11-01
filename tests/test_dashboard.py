"""GTM Operations Dashboard: calculations reuse engine results, filters never mutate data, theme/security config."""

import copy
import csv
import importlib.util
import tomllib
import unittest
from pathlib import Path

from tests.test_first_touch import AS_OF
from ui import dashboard, helpers

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_ROWS = helpers.parse_csv_bytes((ROOT / "data" / "input" / "sample_companies.csv").read_bytes()).rows
with open(ROOT / "tests" / "fixtures" / "expected_results.csv", newline="", encoding="utf-8") as handle:
    EXPECTED = list(csv.DictReader(handle))


def sample_results():
    return helpers.score_rows(SAMPLE_ROWS, AS_OF)


def ids(results):
    return [result["company_id"] for result in results]


class KpiTest(unittest.TestCase):
    def test_sample_kpis_match_the_engine(self):
        self.assertEqual(dashboard.kpis(sample_results()), {
            "total": 25, "qualified": 6, "review": 12, "disqualified": 7,
            "contacts_ready": 16, "ready_to_sequence": 3})

    def test_kpis_agree_with_the_hand_derived_fixture(self):
        values = dashboard.kpis(sample_results())
        count = lambda field, value: sum(1 for row in EXPECTED if row[field] == value)  # noqa: E731
        self.assertEqual(values["qualified"], count("icp_outcome", "Qualified"))
        self.assertEqual(values["review"], count("icp_outcome", "Review"))
        self.assertEqual(values["disqualified"], count("icp_outcome", "Disqualified"))
        self.assertEqual(values["contacts_ready"], count("contact_readiness", "Ready"))
        self.assertEqual(values["ready_to_sequence"], count("campaign_readiness", "Ready to Sequence"))

    def test_kpis_follow_the_filtered_view(self):
        view = dashboard.filter_dashboard(sample_results(), icp=["Qualified"])
        self.assertEqual(dashboard.kpis(view), {
            "total": 6, "qualified": 6, "review": 0, "disqualified": 0,
            "contacts_ready": 4, "ready_to_sequence": 3})

    def test_every_kpi_has_a_label(self):
        self.assertEqual([key for key, _ in dashboard.KPI_LABELS], list(dashboard.kpis([])))


class FilterTest(unittest.TestCase):
    def setUp(self):
        self.results = sample_results()

    def test_no_filters_returns_every_record(self):
        self.assertEqual(ids(dashboard.filter_dashboard(self.results)), ids(self.results))

    def test_each_filter(self):
        f = dashboard.filter_dashboard
        self.assertEqual(len(f(self.results, icp=["Review"])), 12)
        self.assertEqual(len(f(self.results, contact=["Not Ready"])), 5)
        self.assertEqual(ids(f(self.results, campaign=["Ready to Sequence"])), ["SYN-001", "SYN-013", "SYN-018"])
        self.assertEqual(ids(f(self.results, icp=["Qualified"], contact=["Needs Attention"])), ["SYN-019", "SYN-020"])

    def test_score_range_is_inclusive(self):
        f = dashboard.filter_dashboard
        self.assertEqual(ids(f(self.results, score_range=(100, 100))), ["SYN-001"])
        at_seventy = ids(f(self.results, score_range=(70, 70)))
        self.assertEqual(at_seventy, ["SYN-017"])                      # 70 is included, whatever its outcome
        self.assertEqual(len(f(self.results, score_range=(0, 39))), 7)
        self.assertEqual(len(f(self.results, score_range=(40, 69))), 9)
        self.assertEqual(len(f(self.results, score_range=(70, 100))), 9)

    def test_filters_combine_with_score_range(self):
        view = dashboard.filter_dashboard(self.results, icp=["Disqualified"], score_range=(60, 100))
        self.assertEqual(ids(view), ["SYN-006", "SYN-017"])

    def test_filtering_never_mutates_the_results(self):
        before = copy.deepcopy(self.results)
        view = dashboard.filter_dashboard(self.results, icp=["Qualified"], contact=["Ready"], score_range=(50, 90))
        dashboard.kpis(view)
        dashboard.prioritised_accounts(view)
        dashboard.score_histogram(view)
        self.assertEqual(self.results, before)
        self.assertIsNot(view, self.results)

    def test_missing_or_malformed_scores_only_drop_out_of_a_narrowed_range(self):
        odd = [dict(self.results[0], icp_score=None), dict(self.results[1], icp_score="n/a")]
        self.assertEqual(len(dashboard.filter_dashboard(odd)), 2)
        self.assertEqual(dashboard.filter_dashboard(odd, score_range=(0, 99)), [])


class DistributionTest(unittest.TestCase):
    def test_fixed_order_with_zero_counts(self):
        view = dashboard.filter_dashboard(sample_results(), icp=["Qualified"])
        self.assertEqual(dashboard.icp_distribution(view), [
            {"category": "Qualified", "count": 6, "share": 1.0},
            {"category": "Review", "count": 0, "share": 0.0},
            {"category": "Disqualified", "count": 0, "share": 0.0}])
        campaign = dashboard.campaign_distribution(view)
        self.assertEqual([row["category"] for row in campaign], helpers.CAMPAIGN_OUTCOMES)
        self.assertEqual([row["count"] for row in campaign], [3, 1, 2, 0, 0])

    def test_shares_sum_to_one(self):
        for rows in (dashboard.icp_distribution(sample_results()), dashboard.contact_distribution(sample_results())):
            self.assertAlmostEqual(sum(row["share"] for row in rows), 1.0)

    def test_unrecognised_values_are_counted_not_dropped(self):
        odd = [dict(sample_results()[0], contact_readiness="Something Else")]
        rows = dashboard.contact_distribution(odd)
        self.assertEqual(rows[-1], {"category": "Something Else", "count": 1, "share": 1.0})


class HistogramTest(unittest.TestCase):
    def test_sample_bins(self):
        bins, missing = dashboard.score_histogram(sample_results())
        self.assertEqual(missing, 0)
        self.assertEqual([b["label"] for b in bins],
                         ["0-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70-79", "80-89", "90-100"])
        self.assertEqual([b["count"] for b in bins], [3, 0, 2, 2, 1, 3, 5, 5, 2, 2])

    def test_boundaries_and_invalid_scores(self):
        results = [{"icp_score": score} for score in (0, 9, 10, 99, 100)] + [{"icp_score": None},
                                                                          {"icp_score": 101}, {}]
        bins, missing = dashboard.score_histogram(results)
        counts = {b["label"]: b["count"] for b in bins}
        self.assertEqual((counts["0-9"], counts["10-19"], counts["90-100"], missing), (2, 1, 2, 3))


class PriorityTest(unittest.TestCase):
    def test_order_is_campaign_readiness_then_score(self):
        rows = dashboard.prioritised_accounts(sample_results())
        self.assertEqual(list(rows[0]), dashboard.PRIORITY_COLUMNS)
        self.assertEqual([r["Company"] for r in rows[:6]], [
            "Brightloop Analytics", "Mosslight Compliance", "Copperleaf Billing",     # Ready to Sequence 100, 97, 77
            "Sablewood Payroll",                                                      # Hold: Trigger Research 80
            "Ochre Systems", "Northgale Marketing Cloud"])                            # Hold: Contact 80, 77
        self.assertTrue(all(r["Campaign readiness"] == "Excluded" for r in rows[-7:]))
        self.assertTrue(all(r["Data"] == "🧪 TEST DATA" for r in rows))

    def test_classifications_are_copied_not_recomputed(self):
        by_name = {r["Company"]: r for r in dashboard.prioritised_accounts(sample_results())}
        for result in sample_results():
            row = by_name[result["company_name"]]
            self.assertEqual((row["ICP score"], row["ICP classification"], row["Contact readiness"],
                              row["Campaign readiness"]),
                             (result["icp_score"], result["icp_outcome"], result["contact_readiness"],
                              result["campaign_readiness"]))

    def test_unrecognised_campaign_value_sorts_last(self):
        results = sample_results()
        results[0] = dict(results[0], campaign_readiness="???")
        self.assertEqual(dashboard.prioritised_accounts(results)[-1]["Campaign readiness"], "???")


class EmptyAndLabelTest(unittest.TestCase):
    def test_empty_dataset(self):
        self.assertEqual(dashboard.kpis([]), {key: 0 for key, _ in dashboard.KPI_LABELS})
        self.assertTrue(all(row["count"] == 0 and row["share"] == 0.0 for row in dashboard.icp_distribution([])))
        bins, missing = dashboard.score_histogram([])
        self.assertEqual((sum(b["count"] for b in bins), missing), (0, 0))
        self.assertEqual(dashboard.prioritised_accounts([]), [])
        self.assertEqual(dashboard.filter_dashboard([], icp=["Qualified"]), [])

    def test_dataset_labels(self):
        results = sample_results()
        self.assertEqual(dashboard.dataset_label(results)[0], "synthetic")
        self.assertEqual(dashboard.dataset_label([])[0], "empty")
        mixed = [dict(results[0], data_status=helpers.MARKED_REAL), results[1]]
        self.assertEqual(dashboard.dataset_label(mixed)[0], "mixed")
        unverified = [dict(results[0], data_status=helpers.MARKED_REAL), dict(results[1], data_status=helpers.UNVERIFIED)]
        self.assertEqual(dashboard.dataset_label(unverified)[0], "unverified")
        self.assertEqual(dashboard.dataset_label([dict(results[0], data_status=None)])[0], "unverified")
        real = [dict(r, data_status=helpers.MARKED_REAL) for r in results]
        self.assertEqual(dashboard.dataset_label(real)[0], "marked_real")


class ThemeAndSecurityConfigTest(unittest.TestCase):
    def setUp(self):
        self.config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))

    def test_brand_theme(self):
        theme = self.config["theme"]
        self.assertEqual((theme["base"], theme["primaryColor"], theme["backgroundColor"],
                          theme["secondaryBackgroundColor"], theme["textColor"], theme["borderColor"]),
                         ("light", "#173B4D", "#F5F8FA", "#FFFFFF", "#243746", "#DCE5EA"))

    def test_theme_did_not_weaken_server_settings(self):
        self.assertEqual(self.config["server"], {"address": "127.0.0.1"})
        self.assertIs(self.config["browser"]["gatherUsageStats"], False)


@unittest.skipUnless(importlib.util.find_spec("altair"), "altair is only installed in the app environment")
class ChartSpecTest(unittest.TestCase):
    def test_distribution_chart_uses_fixed_order_and_accent(self):
        from ui import charts
        rows = dashboard.campaign_distribution(dashboard.filter_dashboard(sample_results(), icp=["Qualified"]))
        spec = charts.distribution_bar(rows, "Campaign readiness", "Campaign readiness").to_dict()
        bar, label = spec["layer"]
        self.assertEqual(bar["encoding"]["y"]["sort"], helpers.CAMPAIGN_OUTCOMES)
        self.assertEqual(bar["mark"]["color"], charts.ACCENT)
        self.assertLessEqual(bar["mark"]["size"], 24)
        self.assertEqual(bar["mark"]["cornerRadiusEnd"], 4)
        self.assertEqual(label["mark"]["color"], charts.TEXT)             # text never wears the series colour
        self.assertIn("tooltip", bar["encoding"])

    def test_histogram_marks_engine_thresholds(self):
        from ui import charts
        spec = charts.score_histogram(dashboard.score_histogram(sample_results())[0]).to_dict()
        text = str(spec)
        self.assertIn("Review from 40", text)
        self.assertIn("Qualified from 70", text)

    def test_histogram_keeps_empty_bins_on_the_axis(self):
        from ui import charts
        bins = dashboard.score_histogram(sample_results())[0]
        self.assertEqual(bins[1]["count"], 0)                               # 10-19 is empty in the sample
        spec = charts.score_histogram(bins).to_dict()
        self.assertEqual(spec["layer"][0]["encoding"]["x"]["scale"]["domain"], [b["label"] for b in bins])

    def test_value_axis_leaves_room_for_tip_labels(self):
        from ui import charts
        rows = dashboard.campaign_distribution(sample_results())
        spec = charts.distribution_bar(rows, "Campaign readiness", "Campaign readiness").to_dict()
        self.assertGreater(spec["layer"][0]["encoding"]["x"]["scale"]["domain"][1], max(r["count"] for r in rows))
        self.assertEqual(charts.headroom([], 1.2), 1)                      # empty data still has a valid axis
