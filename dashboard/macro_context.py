"""
Macro Context — Dashboard Page 7
Displays FRED macroeconomic data and its relevance to the CEG thesis.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


# ── Series metadata ───────────────────────────────────────────────────────────

SERIES_META = {
    "FEDFUNDS": {
        "name": "Fed Funds Rate",
        "unit": "%",
        "color": "#EF5350",
        "thesis": (
            "Lower Fed Funds Rate reduces CEG's cost of capital for nuclear fleet maintenance "
            "and new data-center load interconnection projects. Rate cuts are generally bullish "
            "for capital-intensive utilities."
        ),
    },
    "DGS10": {
        "name": "10-Year Treasury",
        "unit": "%",
        "color": "#FF7043",
        "thesis": (
            "As a regulated utility, CEG's dividend yield is benchmarked against the 10-year. "
            "Rising rates compress valuation multiples; falling rates make the ~2% yield more "
            "attractive and expand EV/EBITDA comparables."
        ),
    },
    "DCOILWTICO": {
        "name": "WTI Crude Oil",
        "unit": "$/bbl",
        "color": "#8D6E63",
        "thesis": (
            "Elevated oil prices raise the operating cost of gas and oil peakers, widening the "
            "clean-spread for nuclear baseload. High WTI often coincides with elevated power "
            "prices — a tailwind for merchant nuclear."
        ),
    },
    "CPIAUCSL": {
        "name": "CPI (All Urban)",
        "unit": "Index",
        "color": "#AB47BC",
        "thesis": (
            "CEG's Power Purchase Agreements with tech hyperscalers include CPI escalation "
            "clauses. Persistently elevated inflation flows through to contracted revenue, "
            "providing a partial inflation hedge."
        ),
    },
    "UNRATE": {
        "name": "Unemployment Rate",
        "unit": "%",
        "color": "#29B6F6",
        "thesis": (
            "Low unemployment supports data-center buildout as hyperscalers continue to invest. "
            "Conversely, rising unemployment could signal economic slowdown and weaker power "
            "demand — a mild headwind for merchant exposure."
        ),
    },
    "INDPRO": {
        "name": "Industrial Production",
        "unit": "Index",
        "color": "#26A69A",
        "thesis": (
            "Industrial production is a leading indicator of electricity demand. Strong INDPRO "
            "translates to higher load on the PJM grid where CEG's nuclear fleet operates, "
            "supporting capacity factor and LMP levels."
        ),
    },
    "CAPUTLG3311A2S": {
        "name": "Utilities Capacity Utilization",
        "unit": "%",
        "color": "#FFCA28",
        "thesis": (
            "High utilities capacity utilization means the grid is running close to its limits, "
            "which historically correlates with tighter reserve margins and higher capacity "
            "prices in PJM's Base Residual Auction — directly benefiting CEG."
        ),
    },
    "ELECPRICEUS": {
        "name": "US Electricity Price",
        "unit": "¢/kWh",
        "color": "#9CCC65",
        "thesis": (
            "Rising retail electricity prices validate higher wholesale LMPs and strengthen "
            "the economics of nuclear baseload contracts. Upward trends support CEG's "
            "long-term PPA pricing power."
        ),
    },
}


# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _load_fred_all() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT date, series_id, value
        FROM fred_data
        ORDER BY date
    """, conn)
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=300)
def _latest_value(df: pd.DataFrame, series_id: str):
    sub = df[df["series_id"] == series_id].dropna(subset=["value"])
    if sub.empty:
        return None, None
    row = sub.sort_values("date").iloc[-1]
    prev = sub.sort_values("date").iloc[-2] if len(sub) > 1 else row
    return row["value"], row["value"] - prev["value"]


# ── render ────────────────────────────────────────────────────────────────────

def render():
    st.header("Macro Context")

    fred_df = _load_fred_all()

    # ── KPI Metrics row ───────────────────────────────────────────────────────
    kpi_series = ["FEDFUNDS", "DGS10", "DCOILWTICO", "CPIAUCSL"]
    kpi_meta = {sid: SERIES_META[sid] for sid in kpi_series}

    cols = st.columns(4)
    for col, (sid, meta) in zip(cols, kpi_meta.items()):
        val, delta = _latest_value(fred_df, sid)
        if val is not None:
            label = f"{val:.2f} {meta['unit']}"
            d_label = f"{delta:+.2f}" if delta is not None else None
            col.metric(meta["name"], label, delta=d_label)
        else:
            col.metric(meta["name"], "—")

    st.divider()

    if fred_df.empty:
        st.info("No FRED macro data yet — run collectors first.")
        return

    # ── Charts per series ─────────────────────────────────────────────────────
    chart_series = ["FEDFUNDS", "DGS10", "DCOILWTICO", "CPIAUCSL", "UNRATE", "INDPRO"]

    # Layout: 2 columns
    left_series = chart_series[0::2]
    right_series = chart_series[1::2]

    def _draw_chart(sid: str, parent_col):
        meta = SERIES_META[sid]
        sub = fred_df[fred_df["series_id"] == sid].dropna(subset=["value"]).copy()
        with parent_col:
            st.markdown(f"**{meta['name']}** ({meta['unit']})")
            if sub.empty:
                st.caption("No data available.")
                return
            fig = px.line(
                sub,
                x="date",
                y="value",
                template="plotly_dark",
                color_discrete_sequence=[meta["color"]],
                labels={"date": "", "value": meta["unit"]},
            )
            fig.update_traces(line_width=2)
            fig.update_layout(
                plot_bgcolor="#0E1117",
                paper_bgcolor="#0E1117",
                margin=dict(l=0, r=0, t=10, b=0),
                height=220,
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"**CEG Thesis:** {meta['thesis']}")

    for l_sid, r_sid in zip(left_series, right_series):
        c1, c2 = st.columns(2)
        _draw_chart(l_sid, c1)
        _draw_chart(r_sid, c2)
        st.divider()

    # ── Additional series (Capacity Utilization + Electricity Price) ──────────
    st.subheader("Additional Macro Indicators")
    extra_series = ["CAPUTLG3311A2S", "ELECPRICEUS"]
    c1, c2 = st.columns(2)
    _draw_chart(extra_series[0], c1)
    _draw_chart(extra_series[1], c2)

    st.divider()

    # ── Multi-series overlay: normalized comparison ────────────────────────────
    st.subheader("Normalized Macro Index Overlay (Z-Score)")
    overlay_ids = ["FEDFUNDS", "DGS10", "DCOILWTICO", "INDPRO", "ELECPRICEUS"]
    overlay_df = fred_df[fred_df["series_id"].isin(overlay_ids)].dropna(subset=["value"]).copy()

    if not overlay_df.empty:
        # Z-score normalize per series
        def _zscore(group):
            mu = group["value"].mean()
            sigma = group["value"].std()
            group = group.copy()
            group["z_value"] = (group["value"] - mu) / sigma if sigma > 0 else 0
            return group

        overlay_df = overlay_df.groupby("series_id", group_keys=False).apply(_zscore)
        overlay_df["series_name"] = overlay_df["series_id"].map(
            lambda sid: SERIES_META.get(sid, {}).get("name", sid)
        )

        color_map = {SERIES_META[sid]["name"]: SERIES_META[sid]["color"] for sid in overlay_ids if sid in SERIES_META}

        fig2 = px.line(
            overlay_df,
            x="date",
            y="z_value",
            color="series_name",
            template="plotly_dark",
            color_discrete_map=color_map,
            labels={"date": "", "z_value": "Z-Score", "series_name": "Series"},
        )
        fig2.add_hline(y=0, line_dash="dot", line_color="#555", annotation_text="Mean")
        fig2.update_layout(
            plot_bgcolor="#0E1117",
            paper_bgcolor="#0E1117",
            height=380,
            legend_title_text="Indicator",
        )
        st.plotly_chart(fig2, use_container_width=True)
        st.caption(
            "Z-scores normalize each series to its own historical mean (0) and standard deviation (1), "
            "enabling cross-series comparison on a single chart."
        )
    else:
        st.info("Insufficient data for normalized overlay.")
