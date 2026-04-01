"""Fleet Operations dashboard page."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta

# CEG fleet NRC unit names
CEG_UNITS = [
    "BRAIDWOOD 1", "BRAIDWOOD 2",
    "BYRON 1", "BYRON 2",
    "CALVERT CLIFFS 1", "CALVERT CLIFFS 2",
    "CLINTON 1",
    "DRESDEN 2", "DRESDEN 3",
    "LASALLE 1", "LASALLE 2",
    "LIMERICK 1", "LIMERICK 2",
    "NINE MILE POINT 1", "NINE MILE POINT 2",
    "PEACH BOTTOM 2", "PEACH BOTTOM 3",
    "QUAD CITIES 1", "QUAD CITIES 2",
    "GINNA",
    "THREE MILE ISLAND 1",
]

# Approximate MW capacity per unit for fleet capacity calculations
UNIT_MW = {
    "BRAIDWOOD 1": 1166, "BRAIDWOOD 2": 1166,
    "BYRON 1": 1150, "BYRON 2": 1150,
    "CALVERT CLIFFS 1": 873, "CALVERT CLIFFS 2": 872,
    "CLINTON 1": 1079,
    "DRESDEN 2": 1000, "DRESDEN 3": 1000,
    "LASALLE 1": 1170, "LASALLE 2": 1170,
    "LIMERICK 1": 1130, "LIMERICK 2": 1130,
    "NINE MILE POINT 1": 613, "NINE MILE POINT 2": 1277,
    "PEACH BOTTOM 2": 1430, "PEACH BOTTOM 3": 1430,
    "QUAD CITIES 1": 1000, "QUAD CITIES 2": 1000,
    "GINNA": 614,
    "THREE MILE ISLAND 1": 835,
}

TOTAL_FLEET_MW = sum(UNIT_MW.values())


def _status_badge(pct: float) -> str:
    if pct is None:
        return "⚫ Unknown"
    if pct >= 90:
        return "🟢 Full Power"
    elif pct >= 50:
        return "🟡 Reduced"
    else:
        return "🔴 Offline/Low"


def _load_nrc_data(conn, days: int = 90) -> pd.DataFrame:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    units_sql = ", ".join(f"'{u}'" for u in CEG_UNITS)
    query = f"""
        SELECT date, unit, power_pct
        FROM nrc_status
        WHERE unit IN ({units_sql})
          AND date >= '{cutoff}'
        ORDER BY date ASC
    """
    df = pd.read_sql_query(query, conn)
    return df


def render():
    st.header("Fleet Operations")

    conn = get_conn()

    # ── Load data ──────────────────────────────────────────────────────────────
    df_all = _load_nrc_data(conn, days=90)

    today = datetime.utcnow().strftime("%Y-%m-%d")
    cutoff_7d = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    cutoff_30d = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

    if df_all.empty:
        st.info("No NRC status data yet. Run the NRC collector to populate.")
    else:
        # Most recent date available
        latest_date = df_all["date"].max()
        df_latest = df_all[df_all["date"] == latest_date]

        # Fleet CF (latest day)
        fleet_cf = df_latest["power_pct"].mean() if not df_latest.empty else None
        units_online = int((df_latest["power_pct"] >= 90).sum()) if not df_latest.empty else 0
        total_mw_online = sum(
            UNIT_MW.get(row["unit"], 0) * (row["power_pct"] / 100.0)
            for _, row in df_latest.iterrows()
            if row["power_pct"] is not None
        )

        # 7-day avg for trend arrow
        df_7d = df_all[df_all["date"] >= cutoff_7d]
        fleet_cf_7d = df_7d["power_pct"].mean() if not df_7d.empty else None
        trend_delta = None
        if fleet_cf is not None and fleet_cf_7d is not None:
            trend_delta = f"{fleet_cf - fleet_cf_7d:+.1f}% vs 7d avg"

        # ── Top metrics row ────────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Fleet Capacity Factor",
            f"{fleet_cf:.1f}%" if fleet_cf is not None else "—",
            delta=trend_delta,
        )
        c2.metric("Units ≥90% Power", f"{units_online} / {len(CEG_UNITS)}")
        c3.metric(
            "Capacity Online (MW)",
            f"{total_mw_online:,.0f} MW",
            delta=f"of {TOTAL_FLEET_MW:,} MW total",
        )
        c4.metric(
            "Last NRC Update",
            latest_date,
        )

        st.divider()

        # ── Unit status table ─────────────────────────────────────────────────
        st.subheader("Unit Status Summary")

        rows = []
        for unit in CEG_UNITS:
            df_unit = df_all[df_all["unit"] == unit]
            curr = df_unit[df_unit["date"] == latest_date]["power_pct"].values
            curr_pct = float(curr[0]) if len(curr) > 0 else None

            avg_7 = df_unit[df_unit["date"] >= cutoff_7d]["power_pct"].mean()
            avg_30 = df_unit[df_unit["date"] >= cutoff_30d]["power_pct"].mean()

            rows.append({
                "Unit": unit,
                "Current %": f"{curr_pct:.1f}" if curr_pct is not None else "—",
                "7-Day Avg %": f"{avg_7:.1f}" if not pd.isna(avg_7) else "—",
                "30-Day Avg %": f"{avg_30:.1f}" if not pd.isna(avg_30) else "—",
                "Status": _status_badge(curr_pct if curr_pct is not None else 0.0),
                "_pct": curr_pct if curr_pct is not None else 0.0,
            })

        df_table = pd.DataFrame(rows)
        st.dataframe(
            df_table.drop(columns=["_pct"]),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        # ── Line chart: individual unit power % last 90 days ──────────────────
        st.subheader("Unit Power % — Last 90 Days")

        unit_options = ["All Units"] + sorted(CEG_UNITS)
        selected_units = st.multiselect(
            "Filter units",
            options=CEG_UNITS,
            default=CEG_UNITS[:5],
            key="fleet_unit_filter",
        )
        if not selected_units:
            selected_units = CEG_UNITS

        df_line = df_all[df_all["unit"].isin(selected_units)].copy()
        if df_line.empty:
            st.info("No data for selected units.")
        else:
            fig_line = px.line(
                df_line,
                x="date",
                y="power_pct",
                color="unit",
                title="Unit Power % (Last 90 Days)",
                labels={"date": "Date", "power_pct": "Power (%)", "unit": "Unit"},
                template="plotly_dark",
            )
            fig_line.update_layout(
                hovermode="x unified",
                legend=dict(orientation="h", y=-0.25),
                margin=dict(t=40, b=10),
                yaxis=dict(range=[0, 110]),
            )
            fig_line.add_hline(y=90, line_dash="dash", line_color="green", opacity=0.4,
                               annotation_text="90%", annotation_position="right")
            fig_line.add_hline(y=50, line_dash="dash", line_color="orange", opacity=0.4,
                               annotation_text="50%", annotation_position="right")
            st.plotly_chart(fig_line, use_container_width=True)

        st.divider()

        # ── Heatmap: unit × date (last 30 days) ───────────────────────────────
        st.subheader("Fleet Heatmap — Last 30 Days")

        df_30 = df_all[df_all["date"] >= cutoff_30d].copy()
        if df_30.empty:
            st.info("No data for last 30 days.")
        else:
            pivot = df_30.pivot_table(index="unit", columns="date", values="power_pct", aggfunc="mean")
            # Preserve CEG_UNITS order
            ordered_units = [u for u in CEG_UNITS if u in pivot.index]
            pivot = pivot.reindex(ordered_units)

            fig_heat = go.Figure(
                data=go.Heatmap(
                    z=pivot.values,
                    x=pivot.columns.tolist(),
                    y=pivot.index.tolist(),
                    colorscale=[
                        [0.0, "#d62728"],
                        [0.5, "#ffdd57"],
                        [1.0, "#2ca02c"],
                    ],
                    zmin=0,
                    zmax=100,
                    colorbar=dict(title="Power %"),
                    hoverongaps=False,
                    hovertemplate="Unit: %{y}<br>Date: %{x}<br>Power: %{z:.1f}%<extra></extra>",
                )
            )
            fig_heat.update_layout(
                title="Power % Heatmap (Last 30 Days)",
                template="plotly_dark",
                xaxis_title="Date",
                yaxis_title="Unit",
                margin=dict(t=40, b=60, l=180),
                height=max(400, len(ordered_units) * 22),
            )
            st.plotly_chart(fig_heat, use_container_width=True)

        st.divider()

        # ── Outage timeline: units below 10% (last 90 days) ───────────────────
        st.subheader("Outage Timeline — Units ≤10% Power (Last 90 Days)")

        df_outage = df_all[df_all["power_pct"] <= 10].copy()
        if df_outage.empty:
            st.info("No outage events (≤10% power) in the last 90 days.")
        else:
            fig_out = px.bar(
                df_outage.sort_values("date"),
                x="date",
                y="power_pct",
                color="unit",
                barmode="group",
                title="Units at ≤10% Power (Outage Events)",
                labels={"date": "Date", "power_pct": "Power (%)", "unit": "Unit"},
                template="plotly_dark",
            )
            fig_out.update_layout(
                legend=dict(orientation="h", y=-0.25),
                margin=dict(t=40, b=10),
            )
            st.plotly_chart(fig_out, use_container_width=True)

    conn.close()
