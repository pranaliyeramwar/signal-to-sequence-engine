"""Altair chart builders for the GTM Operations Dashboard (imported by the Streamlit app only).

Single-series charts: one accent colour for every bar, value labels in text colours (never the bar
colour), fixed category order from the engine, hairline solid grid, 4px rounded data-ends.
The accent is 2.97:1 against white, so every value is also printed as a label and each chart has a
table view in the app.
"""

import math

import altair as alt

from scoring.rules import QUALIFIED_MIN, REVIEW_MIN

from .style import ACCENT, BORDER, MUTED, PRIMARY, SURFACE, TEXT  # single palette source

FONT = "sans-serif"

BAR_SIZE = 22                 # mark spec: <= 24px thick


def headroom(counts, factor):
    """Value-axis maximum leaving room for the value label at the tallest bar's tip."""
    return max(1, math.ceil(max(counts, default=0) * factor))


def configure(chart):
    return (chart.configure(background=SURFACE, font=FONT)
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=MUTED, titleColor=MUTED, labelFontSize=12, titleFontSize=12,
                            gridColor=BORDER, gridWidth=1, gridDash=[], domainColor=BORDER, tickColor=BORDER)
            .configure_title(color=PRIMARY, fontSize=14, fontWeight=600, anchor="start"))


def distribution_bar(rows, title, category_title):
    """Horizontal bars for a distribution from ui.dashboard.distribution(): one row per outcome."""
    order = [row["category"] for row in rows]
    data = alt.Data(values=[dict(row, share_label=f"{row['share']:.0%}") for row in rows])
    base = alt.Chart(data).encode(
        y=alt.Y("category:N", sort=order, title=None, axis=alt.Axis(labelLimit=220, ticks=False)),
        x=alt.X("count:Q", title="Companies", axis=alt.Axis(tickMinStep=1, format="d"),
                scale=alt.Scale(domain=[0, headroom([row["count"] for row in rows], 1.2)])),
        tooltip=[alt.Tooltip("category:N", title=category_title), alt.Tooltip("count:Q", title="Companies"),
                 alt.Tooltip("share_label:N", title="Share")],
    )
    bars = base.mark_bar(color=ACCENT, size=BAR_SIZE, cornerRadiusEnd=4)
    labels = base.mark_text(align="left", dx=6, color=TEXT, fontSize=12).encode(text=alt.Text("count:Q"))
    height = max(len(order) * 40, 120)
    return configure((bars + labels).properties(title=title, height=height))


def score_histogram(bins):
    """Columns per 10-point ICP score bin, with the engine's Review and Qualified thresholds as solid rules."""
    data = alt.Data(values=bins)
    order = [item["label"] for item in bins]
    # Pin the x domain to every bin so an empty bin keeps its place on the axis instead of vanishing.
    x_scale = alt.Scale(domain=order)
    base = alt.Chart(data).encode(
        x=alt.X("label:N", sort=order, scale=x_scale, title="ICP score", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("count:Q", title="Companies", axis=alt.Axis(tickMinStep=1, format="d"),
                scale=alt.Scale(domain=[0, headroom([item["count"] for item in bins], 1.4)])),
        tooltip=[alt.Tooltip("label:N", title="ICP score"), alt.Tooltip("count:Q", title="Companies")],
    )
    columns = base.mark_bar(color=ACCENT, size=BAR_SIZE, cornerRadiusEnd=4).transform_filter("datum.count > 0")
    labels = (base.mark_text(dy=-6, baseline="bottom", color=TEXT, fontSize=12)
              .encode(text=alt.Text("count:Q")).transform_filter("datum.count > 0"))
    thresholds = alt.Data(values=[
        {"label": f"{REVIEW_MIN}-{REVIEW_MIN + 9}", "name": f"Review from {REVIEW_MIN}"},
        {"label": f"{QUALIFIED_MIN}-{QUALIFIED_MIN + 9}", "name": f"Qualified from {QUALIFIED_MIN}"},
    ])
    rule_base = alt.Chart(thresholds).encode(x=alt.X("label:N", sort=order, scale=x_scale, bandPosition=0))
    rules = rule_base.mark_rule(color=PRIMARY, strokeWidth=1)
    rule_labels = rule_base.mark_text(align="left", dx=4, y=4, baseline="top", color=PRIMARY,
                                      fontSize=11).encode(text="name:N")
    return configure((columns + labels + rules + rule_labels).properties(
        title="ICP score distribution", height=260))
