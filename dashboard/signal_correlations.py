"""
Signal Correlations — Dashboard Page 9
Explores relationships between dimension scores over time.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np


# ── Constants ─────────────────────────────────────────────────────────────────

DIMENSION_DISPLAY = {
    "nuclear_ops": "Nuclear Ops",
    "power_markets": "Power Markets",
    "data_center_demand": "Data Center",
    "regulatory": "Regulatory",
    "financial_insider": "Fin / Insider",
    "physical_validation": "Physical",
}

DIM_COLORS = {
    "nuclear_ops": "#1E88E5",
    "power_markets": "#43A047",
    "data_center_demand": "#E53935",
    "regulatory": "#FB8C00",
    "financial_insider": "#8E24AA",
    "physical_validation": "#00ACC1",
}


# ── Data loader ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _load_pivot() -> pd.DataFrame:
    """Return a wide-format DataFrame: date × dimension scores."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT date, dimension, score
        FROM signals
        WHERE dimension != 'composite'
        ORDER BY date
    """, conn)
    conn.close()
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    pivot = df.pivot_table(index="date", columns="dimension", values="score", aggfunc="mean")
    pivot.columns.name = None
    pivot = pivot.sort_index()
    return pivot


# ── helpers ───────────────────────────────────────────────────────────────────

def _nice_name(col: str) -> str:
    return DIMENSION_DISPLAY.get(col, col)


def _divergence_pairs(pivot: pd.DataFrame, threshold: float = 1.0) -> pd.DataFrame:
    """
    Find rows where at least one dimension is strongly bullish (>= threshold)
    and at least one is strongly bearish (<= -threshold).
    """
    if pivot.empty:
        return pd.DataFrame()
    rows = []
    for date, row in pivot.iterrows():
        bulls = [c for c in row.index if row[c] >= threshold]
        bears = [c for c in row.index if row[c] <= -threshold]
        if bulls and bears:
            rows.append({
                "Date": date.strftime("%Y-%m-%d"),
                "Bullish Dims": ", ".join(_nice_name(b) for b in bulls),
                "Bearish Dims": ", ".join(_nice_name(b) for b in bears),
                "Max Bull Score": row[bulls].max(),
                "Min Bear Score": row[bears].min(),
            })
    return pd.DataFrame(rows)


# ── render ────────────────────────────────────────────────────────────────────

def render():
    st.header("Signal Correlations")

    pivot = _load_pivot()

    if pivot.empty:
        st.info("No dimension signal history yet — run processors/signal_scorer.py first.")
        return

    dims = [c for c in pivot.columns if c in DIMENSION_DISPLAY]
    missing = [c for c in DIMENSION_DISPLAY if c not in pivot.columns]
    # Fill missing dims with NaN so charts stay consistent
    for c in missing:
        pivot[c] = np.nan
    dims_ordered = list(DIMENSION_DISPLAY.keys())

    # ── Section 1: Correlation Heatmap ────────────────────────────────────────
    st.subheader("Dimension Score Correlation Matrix")

    clean = pivot[dims_ordered].dropna(how="all")
    if len(clean) >= 2:
        corr = clean.corr()
        labels = [_nice_name(c) for c in dims_ordered]
        corr.index = labels
        corr.columns = labels

        z = corr.values
        # Annotate with rounded values
        annotations = []
        for i in range(len(labels)):
            for j in range(len(labels)):
                v = z[i][j]
                annotations.append(dict(
                    x=labels[j], y=labels[i],
                    text=f"{v:.2f}" if not np.isnan(v) else "—",
                    showarrow=False,
                    font=dict(color="#fff" if abs(v) > 0.5 else "#ccc", size=12)
                ))

        fig_hm = go.Figure(go.Heatmap(
            z=z,
            x=labels,
            y=labels,
            colorscale=[
                [0.0, "#B71C1C"],
                [0.25, "#E53935"],
                [0.5, "#1A1F2B"],
                [0.75, "#1565C0"],
                [1.0, "#1E88E5"],
            ],
            zmin=-1, zmax=1,
            showscale=True,
            colorbar=dict(title="Pearson r", tickvals=[-1, -0.5, 0, 0.5, 1],
                          ticktext=["-1.0", "-0.5", "0", "+0.5", "+1.0"]),
        ))
        fig_hm.update_layout(
            template="plotly_dark",
            plot_bgcolor="#0E1117",
            paper_bgcolor="#0E1117",
            annotations=annotations,
            height=450,
            xaxis=dict(side="bottom"),
        )
        st.plotly_chart(fig_hm, use_container_width=True)
        st.caption(
            "Pearson correlation over all available observation dates. "
            "Blue = positive correlation (dimensions move together); "
            "Red = inverse correlation (dimensions diverge)."
        )
    else:
        st.info("Insufficient observations to compute correlations (need ≥ 2 dates).")

    st.divider()

    # ── Section 2: Time Series Overlay ────────────────────────────────────────
    st.subheader("Dimension Scores Over Time")

    sel_dims = st.multiselect(
        "Select dimensions to display",
        options=dims_ordered,
        default=dims_ordered,
        format_func=_nice_name,
        key="corr_ts_dims",
    )

    if sel_dims:
        fig_ts = go.Figure()
        for dim in sel_dims:
            series = pivot[dim].dropna()
            if series.empty:
                continue
            fig_ts.add_trace(go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines+markers",
                name=_nice_name(dim),
                line=dict(color=DIM_COLORS.get(dim, "#888"), width=2),
                marker=dict(size=5),
            ))
        fig_ts.add_hline(y=0, line_dash="dot", line_color="#444")
        fig_ts.add_hline(y=1.0, line_dash="dash", line_color="#333",
                         annotation_text="Strong Bull", annotation_position="right",
                         annotation_font=dict(color="#555", size=10))
        fig_ts.add_hline(y=-1.0, line_dash="dash", line_color="#333",
                         annotation_text="Strong Bear", annotation_position="right",
                         annotation_font=dict(color="#555", size=10))
        fig_ts.update_layout(
            template="plotly_dark",
            plot_bgcolor="#0E1117",
            paper_bgcolor="#0E1117",
            yaxis=dict(range=[-2.2, 2.2], title="Score"),
            xaxis_title="",
            height=380,
            legend_title_text="Dimension",
        )
        st.plotly_chart(fig_ts, use_container_width=True)
    else:
        st.info("Select at least one dimension above.")

    st.divider()

    # ── Section 3: Pairwise scatter plots ─────────────────────────────────────
    st.subheader("Pairwise Dimension Scatter Plots")

    col_a, col_b = st.columns(2)
    with col_a:
        dim_x = st.selectbox("X-axis dimension", dims_ordered, index=0,
                              format_func=_nice_name, key="scatter_x")
    with col_b:
        default_y_idx = 1 if len(dims_ordered) > 1 else 0
        dim_y = st.selectbox("Y-axis dimension", dims_ordered, index=default_y_idx,
                              format_func=_nice_name, key="scatter_y")

    scatter_data = pivot[[dim_x, dim_y]].dropna()
    if len(scatter_data) >= 2:
        scatter_data = scatter_data.reset_index()
        scatter_data["date_str"] = scatter_data["date"].dt.strftime("%Y-%m-%d")

        fig_sc = px.scatter(
            scatter_data,
            x=dim_x,
            y=dim_y,
            hover_data={"date_str": True, dim_x: ":.2f", dim_y: ":.2f"},
            template="plotly_dark",
            color_discrete_sequence=["#1E88E5"],
            labels={dim_x: _nice_name(dim_x), dim_y: _nice_name(dim_y), "date_str": "Date"},
        )
        # Trend line
        if len(scatter_data) >= 3:
            x_vals = scatter_data[dim_x].values
            y_vals = scatter_data[dim_y].values
            mask = ~(np.isnan(x_vals) | np.isnan(y_vals))
            if mask.sum() >= 2:
                m, b = np.polyfit(x_vals[mask], y_vals[mask], 1)
                x_line = np.linspace(x_vals[mask].min(), x_vals[mask].max(), 100)
                y_line = m * x_line + b
                fig_sc.add_trace(go.Scatter(
                    x=x_line, y=y_line,
                    mode="lines", name="Trend",
                    line=dict(color="#FF9100", dash="dash", width=1.5),
                ))
        fig_sc.add_vline(x=0, line_dash="dot", line_color="#444")
        fig_sc.add_hline(y=0, line_dash="dot", line_color="#444")
        fig_sc.update_layout(
            plot_bgcolor="#0E1117",
            paper_bgcolor="#0E1117",
            height=380,
            xaxis=dict(range=[-2.2, 2.2]),
            yaxis=dict(range=[-2.2, 2.2]),
        )
        st.plotly_chart(fig_sc, use_container_width=True)

        # Correlation value
        r = scatter_data[[dim_x, dim_y]].corr().iloc[0, 1]
        st.caption(f"Pearson r = **{r:.3f}** ({len(scatter_data)} observations)")
    elif dim_x == dim_y:
        st.info("Select two different dimensions for a scatter plot.")
    else:
        st.info("Insufficient overlapping data points for scatter plot.")

    st.divider()

    # ── Section 4: Divergence Detector ────────────────────────────────────────
    st.subheader("Divergence Detector")
    st.caption(
        "Rows where at least one dimension is strongly bullish (≥ +1.0) "
        "and at least one is strongly bearish (≤ –1.0) simultaneously."
    )

    threshold = st.slider("Divergence threshold", 0.5, 2.0, 1.0, 0.1, key="div_threshold")
    div_df = _divergence_pairs(pivot, threshold=threshold)

    if div_df.empty:
        st.success(
            f"No divergences detected at threshold ±{threshold:.1f}. "
            "All tracked dimensions agree in direction."
        )
    else:
        st.warning(f"{len(div_df)} divergence event(s) detected.")
        st.dataframe(div_df, use_container_width=True, hide_index=True)
        st.caption(
            "Divergences signal uncertainty: the composite score may be masking "
            "opposing forces. Review each dimension for context."
        )
