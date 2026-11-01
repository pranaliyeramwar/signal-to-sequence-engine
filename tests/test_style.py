"""Presentation styling: one palette, a fixed stylesheet, and an accessible priority-row highlight."""

import importlib.util
import re
import tomllib
import unittest
from pathlib import Path

from ui import style

ROOT = Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))


def contrast(foreground, background):
    def luminance(colour):
        channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class PaletteTest(unittest.TestCase):
    def test_brand_colours_match_the_theme(self):
        theme = CONFIG["theme"]
        self.assertEqual((style.PRIMARY, style.ACCENT), ("#173B4D", "#19A7A0"))
        self.assertEqual(theme["primaryColor"], style.PRIMARY)
        self.assertEqual(theme["backgroundColor"], style.BACKGROUND)
        self.assertEqual(theme["textColor"], style.TEXT)
        self.assertEqual(theme["borderColor"], style.BORDER)

    def test_text_pairs_meet_wcag_aa(self):
        pairs = [(style.SURFACE, style.PRIMARY), (style.HEADER_SUBTEXT, style.PRIMARY),
                 (style.PRIMARY, style.ACCENT_TINT), (style.ACCENT_INK, style.ACCENT_TINT),
                 (style.SECONDARY_TEXT, style.BACKGROUND), (style.SECONDARY_TEXT, style.SURFACE),
                 (style.PRIMARY, style.BACKGROUND), (style.TEXT, style.ACCENT_TINT)]
        for foreground, background in pairs:
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(contrast(foreground, background), 4.5)

    @unittest.skipUnless(importlib.util.find_spec("altair"), "altair is only installed in the app environment")
    def test_charts_use_the_same_palette(self):
        from ui import charts
        self.assertEqual((charts.PRIMARY, charts.ACCENT, charts.TEXT), (style.PRIMARY, style.ACCENT, style.TEXT))


class StylesheetTest(unittest.TestCase):
    def setUp(self):
        self.css = style.app_css()

    def test_is_a_single_fixed_style_block(self):
        self.assertTrue(self.css.startswith("<style>") and self.css.endswith("</style>"))
        self.assertEqual(self.css.count("<style>"), 1)
        self.assertNotIn("<script", self.css.lower())
        self.assertEqual(style.app_css(), self.css)                       # no inputs, always identical

    def test_no_unformatted_placeholders(self):
        self.assertIsNone(re.search(r"\{[A-Z_]+\}", self.css))

    def test_brand_colours_are_applied(self):
        for colour in (style.PRIMARY, style.ACCENT, style.ACCENT_TINT):
            self.assertIn(colour, self.css)
        for hook in ('[data-testid="stSidebar"]', '[data-testid="stTab"][aria-selected="true"]',
                     f".st-key-{style.HEADER_KEY}", f'[class*="st-key-{style.CARD_PREFIX}"]'):
            self.assertIn(hook, self.css)

    def test_header_title_is_white_and_outranks_the_heading_rule(self):
        # Regression: a general `[data-testid="stHeading"] h1` rule once painted the header title dark-on-dark.
        self.assertIn('<h1 class="app-title">Signal-to-Sequence Engine</h1>', style.HEADER_HTML)
        rule = re.search(r"\.st-key-app_header \.app-header \.app-title \{([^}]*)\}", self.css)
        self.assertIsNotNone(rule)
        self.assertIn(f"color: {style.SURFACE}", rule.group(1))
        self.assertNotIn("stHeading", style.HEADER_HTML)

    def test_status_alert_colours_are_left_to_streamlit(self):
        self.assertNotIn("stAlert", self.css)

    def test_card_keys(self):
        self.assertEqual(style.card_key("kpi", "total"), "card_kpi_total")
        self.assertTrue(style.HIGHLIGHT_KPI_KEY.startswith(style.KPI_CARD_PREFIX))


class PriorityRowStyleTest(unittest.TestCase):
    def test_ready_to_sequence_rows_are_highlighted(self):
        row = {"Company": "A", "Campaign readiness": "Ready to Sequence", "ICP score": 90}
        cells = style.priority_row_style(row)
        self.assertEqual(len(cells), 3)
        self.assertTrue(all(style.ACCENT_TINT in css and style.ACCENT_INK in css for css in cells))

    def test_other_rows_are_unstyled(self):
        for value in ("Hold: Contact", "Excluded", "", None):
            with self.subTest(value=value):
                self.assertEqual(style.priority_row_style({"Company": "A", "Campaign readiness": value}), ["", ""])
        self.assertEqual(style.priority_row_style({"Company": "A"}), [""])


if __name__ == "__main__":
    unittest.main()
