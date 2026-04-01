"""Power Markets dashboard page."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta

# BRA prices from plant_config (hardcoded for display)
BRA_PRICES = {
    "2026/2027": 329.17,
    "2027/2028": 333.44,
}


def render():
    st.header("Power Markets")

    conn = get_conn()

    cutoff_7d = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    # ── Load PJM data ──────────────────────────────────────────────────────────
    df_pjm = pd.read_sql_query(
        f"""
        SELECT datetime, market, pnode_name, lmp_total, lmp_energy, lmp_congestion, lmp_loss
        FROM pjm_lmp
        WHERE datetime >= '{cutoff_7d}'
        ORDER BY datetime ASC
        """,
        conn,
    )

    # ── Load ERCOT data ────────────────────────────────────────────────────────
    df_ercot = pd.read_sql_query(
        f"""
        SELECT datetime, settlement_point, lmp
        FROM ercot_lmp
        WHERE datetime >= '{cutoff_7d}'
        ORDER BY datetime ASC
        """,
        conn,
    )

    # ── Top metrics ────────────────────────────────────────────────────────────
    avg_pjm = df_pjm["lmp_total"].mean() if not df_pjm.empty else None
    max_pjm = df_pjm["lmp_total"].max() if not df_pjm.empty else None
    avg_ercot = df_ercot["lmp"].mean() if not df_ercot.empty else None

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(
        "Avg PJM LMP (7d)",
        f"${avg_pjm:.2f}/MWh" if avg_pjm is not None else "—",
    )
    c2.metric(
        "Max PJM LMP (7d)",
        f"${max_pjm:.2f}/MWh" if max_pjm is not None else "—",
    )
    c3.metric(
        "Avg ERCOT LMP (7d)",
        f"${avg_ercot:.2f}/MWh" if avg_ercot is not None else "—",
    )
    c4.metric(
        "BRA 2026/2027",
        f"${BRA_PRICES['2026/2027']:.2f}/MW-day",
    )
    c5.metric(
        "BRA 2027/2028",
        f"${BRA_PRICES['2027/2028']:.2f}/MW-day",
        delta="At cap",
    )

    st.divider()

    # ── PJM LMP time series ────────────────────────────────────────────────────
    st.subheader("PJM LMP — Last 7 Days")

    if df_pjm.empty:
        st.info("No PJM LMP data yet.")
    else:
        df_pjm["datetime"] = pd.to_datetime(df_pjm["datetime"], errors="coerce")
        pjm_nodes = sorted(df_pjm["pnode_name"].unique().tolist())
        selected_pjm = st.multiselect(
            "PJM Pricing Nodes",
            options=pjm_nodes,
            default=pjm_nodes[:5] if len(pjm_nodes) >= 5 else pjm_nodes,
            key="pjm_node_filter",
        )
        df_pjm_f = df_pjm[df_pjm["pnode_name"].isin(selected_pjm)] if selected_pjm else df_pjm

        fig_pjm = px.line(
            df_pjm_f,
            x="datetime",
            y="lmp_total",
            color="pnode_name",
            title="PJM Hourly LMP by Node",
            labels={"datetime": "Hour", "lmp_total": "LMP ($/MWh)", "pnode_name": "Node"},
            template="plotly_dark",
        )
        fig_pjm.update_layout(
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.25),
            margin=dict(t=40, b=10),
        )
        st.plotly_chart(fig_pjm, use_container_width=True)

    st.divider()

    # ── ERCOT LMP time series ──────────────────────────────────────────────────
    st.subheader("ERCOT LMP — Last 7 Days")

    if df_ercot.empty:
        st.info("No ERCOT LMP data yet.")
    else:
        df_ercot["datetime"] = pd.to_datetime(df_ercot["datetime"], errors="coerce")
        ercot_points = sorted(df_ercot["settlement_point"].unique().tolist())
        selected_ercot = st.multiselect(
            "ERCOT Settlement Points",
            options=ercot_points,
            default=ercot_points[:5] if len(ercot_points) >= 5 else ercot_points,
            key="ercot_point_filter",
        )
        df_ercot_f = df_ercot[df_ercot["settlement_point"].isin(selected_ercot)] if selected_ercot else df_ercot

        fig_ercot = px.line(
            df_ercot_f,
            x="datetime",
            y="lmp",
            color="settlement_point",
            title="ERCOT Hourly LMP by Settlement Point",
            labels={"datetime": "Hour", "lmp": "LMP ($/MWh)", "settlement_point": "Settlement Point"},
            template="plotly_dark",
        )
        fig_ercot.update_layout(
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.25),
            margin=dict(t=40, b=10),
        )
        st.plotly_chart(fig_ercot, use_container_width=True)

    st.divider()

    # ── LMP distribution histogram ─────────────────────────────────────────────
    st.subheader("LMP Distribution (7d)")

    col_hist_pjm, col_hist_ercot = st.columns(2)

    with col_hist_pjm:
        if df_pjm.empty:
            st.info("No PJM data.")
        else:
            fig_hist_pjm = px.histogram(
                df_pjm,
                x="lmp_total",
                color="pnode_name",
                nbins=60,
                title="PJM LMP Distribution",
                labels={"lmp_total": "LMP ($/MWh)", "pnode_name": "Node"},
                template="plotly_dark",
                opacity=0.75,
            )
            fig_hist_pjm.update_layout(
                barmode="overlay",
                legend=dict(orientation="h", y=-0.3),
                margin=dict(t=40, b=10),
            )
            st.plotly_chart(fig_hist_pjm, use_container_width=True)

    with col_hist_ercot:
        if df_ercot.empty:
            st.info("No ERCOT data.")
        else:
            fig_hist_ercot = px.histogram(
                df_ercot,
                x="lmp",
                color="settlement_point",
                nbins=60,
                title="ERCOT LMP Distribution",
                labels={"lmp": "LMP ($/MWh)", "settlement_point": "Settlement Point"},
                template="plotly_dark",
                opacity=0.75,
            )
            fig_hist_ercot.update_layout(
                barmode="overlay",
                legend=dict(orientation="h", y=-0.3),
                margin=dict(t=40, b=10),
            )
            st.plotly_chart(fig_hist_ercot, use_container_width=True)

    st.divider()

    # ── Price heatmap: hour-of-day vs day-of-week ─────────────────────────────
    st.subheader("PJM LMP Price Heatmap — Hour of Day × Day of Week")

    if df_pjm.empty:
        st.info("No PJM data for heatmap.")
    else:
        df_hm = df_pjm.copy()
        df_hm["datetime"] = pd.to_datetime(df_hm["datetime"], errors="coerce")
        df_hm = df_hm.dropna(subset=["datetime"])
        df_hm["hour"] = df_hm["datetime"].dt.hour
        df_hm["dow"] = df_hm["datetime"].dt.day_name()

        dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        pivot_hm = (
            df_hm.groupby(["dow", "hour"])["lmp_total"]
            .mean()
            .reset_index()
            .pivot(index="dow", columns="hour", values="lmp_total")
            .reindex(dow_order)
        )

        if pivot_hm.empty or pivot_hm.isnull().all().all():
            st.info("Insufficient data for price heatmap.")
        else:
            fig_hm = go.Figure(
                data=go.Heatmap(
                    z=pivot_hm.values,
                    x=[f"{h:02d}:00" for h in pivot_hm.columns],
                    y=pivot_hm.index.tolist(),
                    colorscale="RdYlGn",
                    colorbar=dict(title="Avg LMP ($/MWh)"),
                    hovertemplate="Day: %{y}<br>Hour: %{x}<br>Avg LMP: $%{z:.2f}/MWh<extra></extra>",
                )
            )
            fig_hm.update_layout(
                title="Avg PJM LMP by Hour of Day × Day of Week",
                template="plotly_dark",
                xaxis_title="Hour of Day",
                yaxis_title="Day of Week",
                margin=dict(t=40, b=10),
            )
            st.plotly_chart(fig_hm, use_container_width=True)

    conn.close()
