"""
Composite Signal Scorecard — Dashboard Page 8
Displays the weighted composite investment signal for Constellation Energy.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


# ── Constants ─────────────────────────────────────────────────────────────────

DIMENSION_WEIGHTS = {
    "nuclear_ops": 0.30,
    "power_markets": 0.25,
    "data_center_demand": 0.20,
    "regulatory": 0.10,
    "financial_insider": 0.10,
    "physical_validation": 0.05,
}

DIMENSION_DISPLAY = {
    "nuclear_ops": "Nuclear Operations",
    "power_markets": "Power Markets",
    "data_center_demand": "Data Center Demand",
    "regulatory": "Regulatory",
    "financial_insider": "Financial / Insider",
    "physical_validation": "Physical Validation",
}

SCORE_LABELS = [
    (1.0, 2.01, "Strong Bull", "#00C853"),
    (0.5, 1.0, "Moderate Bull", "#69F0AE"),
    (0.0, 0.5, "Neutral", "#FFD600"),
    (-0.5, 0.0, "Cautious", "#FF9100"),
    (-2.01, -0.5, "Bearish", "#FF1744"),
]


def _score_label(score: float) -> tuple[str, str]:
    """Return (label, hex_color) for a composite score."""
    for lo, hi, label, color in SCORE_LABELS:
        if lo <= score < hi:
            return label, color
    if score >= 2.0:
        return "Strong Bull", "#00C853"
    return "Bearish", "#FF1744"


# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _load_latest_dimension_scores() -> pd.DataFrame:
    """Load the most recent score for each dimension."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT s.date, s.dimension, s.score, s.notes
        FROM signals s
        INNER JOIN (
            SELECT dimension, MAX(date) AS max_date
            FROM signals
            WHERE dimension != 'composite'
            GROUP BY dimension
        ) latest ON s.dimension = latest.dimension AND s.date = latest.max_date
        ORDER BY s.dimension
    """, conn)
    conn.close()
    return df


@st.cache_data(ttl=300)
def _load_composite_history() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT date, score
        FROM signals
        WHERE dimension = 'composite'
        ORDER BY date
    """, conn)
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=300)
def _load_all_dimension_history() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT date, dimension, score
        FROM signals
        WHERE dimension != 'composite'
        ORDER BY date
    """, conn)
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


# ── render ────────────────────────────────────────────────────────────────────

def render():
    st.header("Composite Signal Scorecard")

    dim_df = _load_latest_dimension_scores()
    hist_df = _load_composite_history()
    all_hist_df = _load_all_dimension_history()

    # ── Compute live composite from latest dimension scores ───────────────────
    if dim_df.empty:
        composite = 0.0
        convergence = "No data"
    else:
        composite = 0.0
        for _, row in dim_df.iterrows():
            w = DIMENSION_WEIGHTS.get(row["dimension"], 0)
            composite += row["score"] * w
        composite = round(composite, 3)

        strong_bull = (dim_df["score"] >= 1.0).sum()
        strong_bear = (dim_df["score"] <= -1.0).sum()
        if strong_bull >= 3:
            convergence = "BULLISH CONVERGENCE"
        elif strong_bear >= 3:
            convergence = "BEARISH CONVERGENCE"
        else:
            convergence = "No convergence"

    label, label_color = _score_label(composite)

    # ── Hero metric ───────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        st.markdown(
            f"""
            <div style="text-align:center;padding:20px;background:#1A1F2B;border-radius:12px;">
                <div style="font-size:60px;font-weight:900;color:{label_color};">{composite:+.3f}</div>
                <div style="font-size:28px;font-weight:700;color:{label_color};margin-top:4px;">{label}</div>
                <div style="font-size:13px;color:#aaa;margin-top:8px;">Composite Signal Score (–2 to +2)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        conv_color = "#00C853" if "BULL" in convergence else ("#FF1744" if "BEAR" in convergence else "#888")
        conv_icon = "▲" if "BULL" in convergence else ("▼" if "BEAR" in convergence else "◆")
        st.markdown(
            f"""
            <div style="text-align:center;padding:20px;background:#1A1F2B;border-radius:12px;height:100%">
                <div style="font-size:32px;color:{conv_color};">{conv_icon}</div>
                <div style="font-size:14px;font-weight:700;color:{conv_color};margin-top:8px;">{convergence}</div>
                <div style="font-size:12px;color:#aaa;margin-top:6px;">Convergence Flag</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c3:
        latest_hist_date = hist_df["date"].max().strftime("%Y-%m-%d") if not hist_df.empty else "—"
        n_days = len(hist_df) if not hist_df.empty else 0
        st.markdown(
            f"""
            <div style="text-align:center;padding:20px;background:#1A1F2B;border-radius:12px;height:100%">
                <div style="font-size:28px;font-weight:700;color:#1E88E5;">{n_days}</div>
                <div style="font-size:14px;color:#aaa;margin-top:8px;">Historical Observations</div>
                <div style="font-size:12px;color:#555;margin-top:6px;">Last: {latest_hist_date}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Gauge chart ───────────────────────────────────────────────────────────
    st.subheader("Signal Gauge")
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=composite,
        number={"suffix": "", "font": {"size": 40, "color": label_color}},
        gauge={
            "axis": {"range": [-2, 2], "tickwidth": 1, "tickcolor": "#555",
                     "tickvals": [-2, -1, -0.5, 0, 0.5, 1, 2],
                     "ticktext": ["-2", "-1", "-0.5", "0", "+0.5", "+1", "+2"]},
            "bar": {"color": label_color, "thickness": 0.25},
            "bgcolor": "#1A1F2B",
            "borderwidth": 0,
            "steps": [
                {"range": [-2, -0.5], "color": "#4A1A1A"},
                {"range": [-0.5, 0], "color": "#4A3A1A"},
                {"range": [0, 0.5], "color": "#3A3A1A"},
                {"range": [0.5, 1.0], "color": "#1A3A2A"},
                {"range": [1.0, 2.0], "color": "#0A2A1A"},
            ],
            "threshold": {
                "line": {"color": "#fff", "width": 3},
                "thickness": 0.75,
                "value": composite,
            },
        },
    ))
    fig_gauge.update_layout(
        paper_bgcolor="#0E1117",
        font={"color": "#FAFAFA"},
        height=280,
        margin=dict(t=20, b=0, l=40, r=40),
    )
    st.plotly_chart(fig_gauge, use_container_width=True)

    st.divider()

    # ── Dimension breakdown table ─────────────────────────────────────────────
    st.subheader("Dimension Breakdown")

    if dim_df.empty:
        st.info("No signal data yet — run processors/signal_scorer.py first.")
    else:
        rows = []
        for dim, weight in DIMENSION_WEIGHTS.items():
            match = dim_df[dim_df["dimension"] == dim]
            if match.empty:
                score, notes, date = None, "No data", "—"
            else:
                r = match.iloc[0]
                score, notes, date = r["score"], r.get("notes", ""), r.get("date", "—")

            slabel, scolor = _score_label(float(score)) if score is not None else ("No Data", "#888")
            score_badge = (
                f'<span style="background:{scolor};color:#000;padding:2px 8px;'
                f'border-radius:4px;font-size:12px;font-weight:700">'
                f'{float(score):+.2f} {slabel}</span>'
            ) if score is not None else '<span style="color:#888">—</span>'

            rows.append({
                "Dimension": DIMENSION_DISPLAY.get(dim, dim),
                "Weight": f"{weight*100:.0f}%",
                "Score": score_badge,
                "Weighted": f"{(float(score)*weight):+.3f}" if score is not None else "—",
                "As of": date,
                "Notes": notes or "—",
            })

        table_df = pd.DataFrame(rows)
        st.write(table_df.to_html(escape=False, index=False), unsafe_allow_html=True)

    st.divider()

    # ── Historical composite line chart ───────────────────────────────────────
    st.subheader("Historical Composite Score")

    if hist_df.empty:
        st.info("No composite history yet — run processors/signal_scorer.py first.")
    else:
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Scatter(
            x=hist_df["date"],
            y=hist_df["score"],
            mode="lines+markers",
            line=dict(color="#1E88E5", width=2),
            marker=dict(size=5),
            name="Composite Score",
        ))
        # Reference bands
        for lo, hi, lbl, col in SCORE_LABELS:
            fig_hist.add_hrect(y0=lo, y1=hi, fillcolor=col, opacity=0.06,
                               line_width=0, annotation_text=lbl,
                               annotation_position="right",
                               annotation_font=dict(color=col, size=10))
        fig_hist.add_hline(y=0, line_dash="dot", line_color="#444")
        fig_hist.update_layout(
            template="plotly_dark",
            plot_bgcolor="#0E1117",
            paper_bgcolor="#0E1117",
            yaxis=dict(range=[-2.1, 2.1], title="Score"),
            xaxis_title="",
            height=320,
            showlegend=False,
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    st.divider()

    # ── Radar / spider chart ──────────────────────────────────────────────────
    st.subheader("Dimension Radar")

    if dim_df.empty:
        st.info("No dimension data for radar chart.")
    else:
        dims = list(DIMENSION_WEIGHTS.keys())
        scores_for_radar = []
        labels_for_radar = []
        for d in dims:
            match = dim_df[dim_df["dimension"] == d]
            score_val = float(match.iloc[0]["score"]) if not match.empty else 0.0
            # Normalize -2..+2 → 0..4 for radar (all positive range)
            scores_for_radar.append(score_val + 2)
            labels_for_radar.append(DIMENSION_DISPLAY.get(d, d))

        # Close the loop
        scores_for_radar.append(scores_for_radar[0])
        labels_for_radar.append(labels_for_radar[0])

        fig_radar = go.Figure(go.Scatterpolar(
            r=scores_for_radar,
            theta=labels_for_radar,
            fill="toself",
            fillcolor="rgba(30,136,229,0.2)",
            line=dict(color="#1E88E5", width=2),
            marker=dict(size=7, color="#1E88E5"),
            name="Current Signal",
        ))
        fig_radar.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 4],
                    tickvals=[0, 1, 2, 3, 4],
                    ticktext=["−2", "−1", "0", "+1", "+2"],
                    gridcolor="#333",
                    linecolor="#444",
                ),
                angularaxis=dict(gridcolor="#333", linecolor="#444"),
                bgcolor="#0E1117",
            ),
            paper_bgcolor="#0E1117",
            font=dict(color="#FAFAFA"),
            showlegend=False,
            height=450,
            margin=dict(t=40, b=40, l=60, r=60),
        )
        st.plotly_chart(fig_radar, use_container_width=True)
        st.caption(
            "Radar axes show score on a –2 to +2 scale. "
            "Area coverage represents the breadth of bullish conviction."
        )
