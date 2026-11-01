"""Brand palette and presentation styling for the Streamlit app. No business logic.

Selector strategy, most to least stable:
  1. `.st-key-<key>` classes from st.container(key=...) - Streamlit's documented styling hook.
  2. `data-testid` attributes plus ARIA state (e.g. `[data-testid="stTab"][aria-selected="true"]`).
  3. Two internal hooks, marked LESS STABLE below. If a Streamlit upgrade renames them, those elements
     fall back to the theme colours in .streamlit/config.toml; nothing else breaks.
The stylesheet is a fixed string built from the constants below and never contains user data.
"""

PRIMARY = "#173B4D"          # deep teal-blue: hierarchy, navigation, buttons, headings
ACCENT = "#19A7A0"           # aqua teal: highlights, chart marks, active indicators
ACCENT_TINT = "#E6F6F5"      # pale aqua surface for highlighted rows, chips and the key KPI card
ACCENT_INK = "#0E5E5A"       # dark aqua for text on ACCENT_TINT (accent itself is too light for text)
BACKGROUND = "#F5F8FA"
SURFACE = "#FFFFFF"
TEXT = "#243746"
MUTED = "#64748B"            # chart axes on white only (4.76:1); not used on the off-white background
SECONDARY_TEXT = "#4A5D6B"   # muted text that also sits on the off-white background
BORDER = "#DCE5EA"
HEADER_SUBTEXT = "#D4E6EC"   # light text on the PRIMARY header band

HEADER_KEY = "app_header"
CARD_PREFIX = "card_"
KPI_CARD_PREFIX = "card_kpi_"
HIGHLIGHT_KPI_KEY = "card_kpi_ready_to_sequence"
PRIORITY_VALUE = "Ready to Sequence"

# One fixed block (no user data), so no general heading rule or element spacing can interfere with it.
HEADER_HTML = (
    '<div class="app-header">'
    '<span class="brand-tag">GTM Operations</span>'
    '<h1 class="app-title">Signal-to-Sequence Engine</h1>'
    '<p class="app-subtitle">Company ICP qualification · Contact readiness · Campaign readiness · '
    'First-touch drafts</p>'
    '</div>'
)


def card_key(*parts):
    """Container key that the stylesheet renders as a card, e.g. card_key('kpi', 'total')."""
    return CARD_PREFIX + "_".join(str(part) for part in parts)


def app_css():
    return f"""<style>
/* ---- Workspace and sidebar separation ------------------------------------------------------ */
[data-testid="stSidebar"] {{
  border-right: 1px solid {BORDER};
  box-shadow: 4px 0 16px rgba(23, 59, 77, 0.05);
}}
[data-testid="stSidebar"] h2 {{
  color: {PRIMARY};
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding-bottom: 0.45rem;
  border-bottom: 2px solid {ACCENT};
}}
[data-testid="stSidebar"] hr {{ border-color: {BORDER}; margin: 1.25rem 0; }}

/* ---- Branded header band ------------------------------------------------------------------- */
.st-key-{HEADER_KEY} {{
  background: {PRIMARY};
  border-radius: 14px;
  border-bottom: 4px solid {ACCENT};
  padding: 1.35rem 1.75rem 1.2rem 1.75rem;
}}
.st-key-{HEADER_KEY} .app-header {{ display: flex; flex-direction: column; align-items: flex-start; gap: 0.35rem; }}
.st-key-{HEADER_KEY} .app-header .app-title {{
  color: {SURFACE};
  font-size: 1.85rem;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.02em;
  margin: 0;
  padding: 0;
}}
.st-key-{HEADER_KEY} .app-header .app-subtitle {{ color: {HEADER_SUBTEXT}; margin: 0; font-size: 0.95rem; }}
.st-key-{HEADER_KEY} .brand-tag {{
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: {PRIMARY};
  background: {ACCENT_TINT};
  border-left: 3px solid {ACCENT};
  border-radius: 4px;
  padding: 0.15rem 0.55rem;
}}

/* ---- Headings ------------------------------------------------------------------------------ */
[data-testid="stHeading"] h1, [data-testid="stHeading"] h2, [data-testid="stHeading"] h3,
[data-testid="stHeading"] h4, [data-testid="stHeading"] h5 {{ color: {PRIMARY}; letter-spacing: -0.01em; }}
[data-testid="stMainBlockContainer"] [data-testid="stHeading"] h3 {{
  border-left: 4px solid {ACCENT};
  padding-left: 0.65rem;
}}

/* ---- Tab navigation ------------------------------------------------------------------------ */
[data-testid="stTabs"] [role="tablist"] {{ gap: 1.5rem; border-bottom: 1px solid {BORDER}; }}
[data-testid="stTab"] p {{ color: {SECONDARY_TEXT}; font-weight: 500; font-size: 0.98rem; }}
[data-testid="stTab"]:hover p {{ color: {PRIMARY}; }}
[data-testid="stTab"][aria-selected="true"] p {{ color: {PRIMARY}; font-weight: 700; }}
/* LESS STABLE: react-aria class for the underline under the active tab. The extra stTab hook gives this
   rule enough specificity to win over Streamlit's own (later-loaded) rule for the same element. */
[data-testid="stTabs"] [data-testid="stTab"] .react-aria-SelectionIndicator {{
  background-color: {ACCENT};
  height: 3px;
}}

/* ---- Buttons and controls ------------------------------------------------------------------ */
[data-testid="stBaseButton-secondary"] {{ border-color: #B8D2DA; color: {PRIMARY}; }}
[data-testid="stBaseButton-secondary"]:hover {{
  border-color: {ACCENT};
  color: {PRIMARY};
  background: {ACCENT_TINT};
}}
/* LESS STABLE: selected filter values (chips) inside multiselects. */
[data-testid="stMultiSelectTagsContainer"] [data-tag] {{
  background: {ACCENT_TINT};
  color: {ACCENT_INK};
  border: 1px solid {ACCENT};
}}
[data-testid="stMultiSelectTagsContainer"] [data-tag] span,
[data-testid="stMultiSelectTagsContainer"] [data-tag] button {{ color: {ACCENT_INK}; }}

/* ---- Cards (containers keyed card_*) ------------------------------------------------------- */
[class*="st-key-{CARD_PREFIX}"] {{
  background: {SURFACE};
  border: 1px solid {BORDER};
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(23, 59, 77, 0.06);
  padding: 1rem 1.15rem;
}}
[class*="st-key-{KPI_CARD_PREFIX}"] {{ border-top: 3px solid {ACCENT}; }}
.st-key-{HIGHLIGHT_KPI_KEY} {{ background: {ACCENT_TINT}; }}
[data-testid="stMetricValue"] {{ color: {PRIMARY}; }}
[data-testid="stMetricLabel"] p {{
  color: {SECONDARY_TEXT};
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}}

/* ---- Tables, expanders, dividers ----------------------------------------------------------- */
[data-testid="stExpander"] details {{ border-color: {BORDER}; border-radius: 10px; }}
[data-testid="stMainBlockContainer"] hr {{ border-color: {BORDER}; }}
</style>"""


def priority_row_style(row):
    """Pandas Styler row function: aqua-tinted rows for accounts that are Ready to Sequence.

    The row's own "Campaign readiness" text already says so, so the tint is never the only signal.
    """
    highlighted = row.get("Campaign readiness") == PRIORITY_VALUE
    css = f"background-color: {ACCENT_TINT}; color: {ACCENT_INK}; font-weight: 600" if highlighted else ""
    return [css] * len(row)
