"""Data Center Demand Intelligence dashboard page."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import json
from datetime import datetime, timedelta

# FERC co-location dockets of interest
COLOCATION_DOCKETS = ["EL24-49", "EL25-20", "EL25-49", "RM26-4", "AD24-11", "ER25-1357"]

# Descriptions from plant_config for context
DOCKET_CONTEXT = {
    "EL24-49": "PJM co-location order (main) — Landmark Order Dec 2025",
    "EL25-20": "Constellation vs. PJM complaint — Consolidated with EL24-49",
    "EL25-49": "Paper hearing: co-location service rates — Ongoing",
    "RM26-4": "Interconnection of Large Loads to Transmission — ANOPR",
    "AD24-11": "FERC Tech Conference: Large Loads at Generators — Conference held Nov 2024",
    "ER25-1357": "PJM BRA price cap/floor approval — Approved",
}

PLANT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "plant_config.json")


def _load_plant_config():
    with open(PLANT_CONFIG_PATH) as f:
        return json.load(f)


def render():
    st.header("Data Center Demand Intelligence")

    conn = get_conn()
    cutoff_30d = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

    # ── Load PJM queue load entries ────────────────────────────────────────────
    df_queue = pd.read_sql_query(
        """
        SELECT queue_number, queue_date, project_name, fuel_type, mw, state,
               county, to_zone, status, poi, first_seen
        FROM pjm_queue
        WHERE LOWER(fuel_type) LIKE '%load%'
        ORDER BY queue_date DESC
        """,
        conn,
    )

    # New entries last 30d
    df_queue_new = df_queue[df_queue["first_seen"] >= cutoff_30d] if not df_queue.empty else pd.DataFrame()

    # ── Load FERC filings for co-location dockets ─────────────────────────────
    dockets_sql = ", ".join(f"'{d}'" for d in COLOCATION_DOCKETS)
    df_ferc = pd.read_sql_query(
        f"""
        SELECT id, docket, filing_date, document_type, description, url
        FROM ferc_filings
        WHERE docket IN ({dockets_sql})
        ORDER BY filing_date DESC
        """,
        conn,
    )

    total_mw = df_queue["mw"].sum() if not df_queue.empty else 0
    new_entries_count = len(df_queue_new)
    active_dockets = df_ferc["docket"].nunique() if not df_ferc.empty else 0

    # ── Top metrics ────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Total MW in PJM Queue (Load)",
        f"{total_mw:,.0f} MW" if total_mw else "—",
    )
    c2.metric(
        "New Load Entries (30d)",
        str(new_entries_count) if new_entries_count else "0",
    )
    c3.metric(
        "Active FERC Co-location Dockets",
        str(active_dockets) if active_dockets else str(len(COLOCATION_DOCKETS)),
    )

    st.divider()

    # ── PJM queue table ────────────────────────────────────────────────────────
    st.subheader("PJM Interconnection Queue — Load Entries")

    if df_queue.empty:
        st.info("No load entries found in PJM queue data yet.")
    else:
        display_cols = ["queue_number", "queue_date", "project_name", "mw",
                        "state", "county", "to_zone", "status", "poi", "first_seen"]
        st.dataframe(
            df_queue[display_cols].rename(columns={
                "queue_number": "Queue #",
                "queue_date": "Queue Date",
                "project_name": "Project",
                "mw": "MW",
                "state": "State",
                "county": "County",
                "to_zone": "Zone",
                "status": "Status",
                "poi": "POI",
                "first_seen": "First Seen",
            }),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ── Bar chart: MW by state/zone ───────────────────────────────────────────
    st.subheader("Load MW by State and Zone")

    if df_queue.empty:
        st.info("No data available for chart.")
    else:
        col_bar1, col_bar2 = st.columns(2)

        with col_bar1:
            df_state = (
                df_queue.groupby("state", dropna=False)["mw"]
                .sum()
                .reset_index()
                .sort_values("mw", ascending=False)
                .rename(columns={"state": "State", "mw": "Total MW"})
            )
            df_state["State"] = df_state["State"].fillna("Unknown")
            fig_state = px.bar(
                df_state,
                x="State",
                y="Total MW",
                title="Total MW by State",
                labels={"State": "State", "Total MW": "MW"},
                template="plotly_dark",
                color="Total MW",
                color_continuous_scale="Blues",
            )
            fig_state.update_layout(
                showlegend=False,
                margin=dict(t=40, b=10),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig_state, use_container_width=True)

        with col_bar2:
            df_zone = (
                df_queue.groupby("to_zone", dropna=False)["mw"]
                .sum()
                .reset_index()
                .sort_values("mw", ascending=False)
                .rename(columns={"to_zone": "Zone", "mw": "Total MW"})
            )
            df_zone["Zone"] = df_zone["Zone"].fillna("Unknown")
            fig_zone = px.bar(
                df_zone,
                x="Zone",
                y="Total MW",
                title="Total MW by PJM Zone",
                labels={"Zone": "Zone", "Total MW": "MW"},
                template="plotly_dark",
                color="Total MW",
                color_continuous_scale="Purples",
            )
            fig_zone.update_layout(
                showlegend=False,
                margin=dict(t=40, b=10),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig_zone, use_container_width=True)

    st.divider()

    # ── Timeline: queue entries over time ──────────────────────────────────────
    st.subheader("Queue Entry Timeline")

    if df_queue.empty:
        st.info("No queue data available.")
    else:
        df_timeline = df_queue.dropna(subset=["queue_date"]).copy()
        df_timeline["queue_date"] = pd.to_datetime(df_timeline["queue_date"], errors="coerce")
        df_timeline = df_timeline.dropna(subset=["queue_date"])

        if df_timeline.empty:
            st.info("No valid queue dates to display.")
        else:
            df_monthly = (
                df_timeline.set_index("queue_date")
                .resample("ME")["mw"]
                .sum()
                .reset_index()
                .rename(columns={"queue_date": "Month", "mw": "MW Added"})
            )
            fig_tl = px.bar(
                df_monthly,
                x="Month",
                y="MW Added",
                title="Monthly MW Added to PJM Queue (Load)",
                labels={"Month": "Month", "MW Added": "MW"},
                template="plotly_dark",
            )
            fig_tl.update_layout(margin=dict(t=40, b=10))
            st.plotly_chart(fig_tl, use_container_width=True)

    st.divider()

    # ── FERC co-location docket tracker ───────────────────────────────────────
    st.subheader("FERC Co-location Docket Tracker")

    # Show docket summary cards
    cfg_dockets = _load_plant_config().get("ferc_dockets", [])
    cfg_docket_map = {d["docket"]: d for d in cfg_dockets}

    docket_cols = st.columns(3)
    for idx, docket in enumerate(COLOCATION_DOCKETS):
        col = docket_cols[idx % 3]
        d_info = cfg_docket_map.get(docket, {})
        col.markdown(
            f"**{docket}**  \n"
            f"{d_info.get('subject', DOCKET_CONTEXT.get(docket, ''))}  \n"
            f"*{d_info.get('status', '')}*"
        )

    st.markdown("#### Recent FERC Filings")

    if df_ferc.empty:
        st.info("No FERC co-location docket filings found yet.")
    else:
        # Make URLs clickable
        def make_link(row):
            if row.get("url"):
                return f'<a href="{row["url"]}" target="_blank">View</a>'
            return "—"

        df_ferc_display = df_ferc.copy()
        df_ferc_display["Link"] = df_ferc_display.apply(make_link, axis=1)
        df_ferc_display = df_ferc_display.rename(columns={
            "docket": "Docket",
            "filing_date": "Filed",
            "document_type": "Type",
            "description": "Description",
        })
        st.write(
            df_ferc_display[["Docket", "Filed", "Type", "Description", "Link"]]
            .to_html(escape=False, index=False),
            unsafe_allow_html=True,
        )

    conn.close()
