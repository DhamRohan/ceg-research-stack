"""Regulatory Tracker dashboard page."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import json
from datetime import datetime, timedelta

PLANT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "plant_config.json")

# Form type color map for badges
FORM_TYPE_COLORS = {
    "8-K": "#e74c3c",
    "10-K": "#3498db",
    "10-Q": "#2ecc71",
    "DEF 14A": "#9b59b6",
    "SC 13G": "#f39c12",
    "SC 13G/A": "#e67e22",
    "4": "#1abc9c",
    "3": "#16a085",
    "5": "#27ae60",
    "S-3": "#8e44ad",
    "424B5": "#2980b9",
}


def _load_plant_config():
    with open(PLANT_CONFIG_PATH) as f:
        return json.load(f)


def _form_badge(form_type: str) -> str:
    color = FORM_TYPE_COLORS.get(str(form_type).upper(), "#7f8c8d")
    return f'<span style="background-color:{color};color:white;padding:2px 7px;border-radius:4px;font-size:0.8em;font-weight:bold;">{form_type}</span>'


def _clickable_url(url: str, label: str = "View") -> str:
    if url:
        return f'<a href="{url}" target="_blank">{label}</a>'
    return "—"


def render():
    st.header("Regulatory Tracker")

    conn = get_conn()

    # ── Load FERC filings ──────────────────────────────────────────────────────
    df_ferc = pd.read_sql_query(
        """
        SELECT id, docket, filing_date, document_type, description, url
        FROM ferc_filings
        ORDER BY filing_date DESC
        """,
        conn,
    )

    # ── Load EDGAR filings ─────────────────────────────────────────────────────
    df_edgar = pd.read_sql_query(
        """
        SELECT accession_no, form_type, file_date, description, url
        FROM edgar_filings
        ORDER BY file_date DESC
        """,
        conn,
    )

    # ── Top metrics ────────────────────────────────────────────────────────────
    cutoff_30d = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    cutoff_7d = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    ferc_total = len(df_ferc)
    ferc_recent = len(df_ferc[df_ferc["filing_date"] >= cutoff_30d]) if not df_ferc.empty else 0
    edgar_total = len(df_edgar)
    edgar_recent = len(df_edgar[df_edgar["file_date"] >= cutoff_7d]) if not df_edgar.empty else 0
    unique_dockets = df_ferc["docket"].nunique() if not df_ferc.empty else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("FERC Filings (Total)", str(ferc_total))
    c2.metric("FERC Filings (30d)", str(ferc_recent))
    c3.metric("EDGAR Filings (Total)", str(edgar_total))
    c4.metric("EDGAR Filings (7d)", str(edgar_recent))
    c5.metric("Active FERC Dockets", str(unique_dockets))

    st.divider()

    # ── FERC filings table ─────────────────────────────────────────────────────
    st.subheader("FERC eLibrary Filings")

    if df_ferc.empty:
        st.info("No FERC filings data yet.")
    else:
        df_ferc_disp = df_ferc.copy()
        df_ferc_disp["Link"] = df_ferc_disp["url"].apply(
            lambda u: _clickable_url(u) if u else "—"
        )
        df_ferc_disp = df_ferc_disp.rename(columns={
            "docket": "Docket",
            "filing_date": "Filed",
            "document_type": "Type",
            "description": "Description",
        })

        # Search / filter
        ferc_search = st.text_input("Search FERC filings (docket / keyword)", key="ferc_search")
        if ferc_search:
            mask = (
                df_ferc_disp["Docket"].str.contains(ferc_search, case=False, na=False) |
                df_ferc_disp["Description"].str.contains(ferc_search, case=False, na=False) |
                df_ferc_disp["Type"].str.contains(ferc_search, case=False, na=False)
            )
            df_ferc_disp = df_ferc_disp[mask]

        st.write(
            df_ferc_disp[["Docket", "Filed", "Type", "Description", "Link"]]
            .head(200)
            .to_html(escape=False, index=False),
            unsafe_allow_html=True,
        )

    st.divider()

    # ── EDGAR filings table ────────────────────────────────────────────────────
    st.subheader("SEC EDGAR Filings")

    if df_edgar.empty:
        st.info("No EDGAR filings data yet.")
    else:
        df_edgar_disp = df_edgar.copy()
        df_edgar_disp["Form Badge"] = df_edgar_disp["form_type"].apply(
            lambda f: _form_badge(str(f)) if f else "—"
        )
        df_edgar_disp["Link"] = df_edgar_disp["url"].apply(
            lambda u: _clickable_url(u) if u else "—"
        )
        df_edgar_disp = df_edgar_disp.rename(columns={
            "accession_no": "Accession #",
            "file_date": "Filed",
            "description": "Description",
        })

        edgar_search = st.text_input("Search EDGAR filings", key="edgar_search")
        df_edgar_show = df_edgar_disp.copy()
        if edgar_search:
            mask = (
                df_edgar_show["Description"].str.contains(edgar_search, case=False, na=False) |
                df_edgar_show["Accession #"].str.contains(edgar_search, case=False, na=False)
            )
            df_edgar_show = df_edgar_show[mask]

        st.write(
            df_edgar_show[["Accession #", "Filed", "Form Badge", "Description", "Link"]]
            .head(200)
            .to_html(escape=False, index=False),
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Filing timeline ────────────────────────────────────────────────────────
    st.subheader("Filing Activity Timeline")

    timeline_data = []

    if not df_ferc.empty:
        for _, row in df_ferc.iterrows():
            timeline_data.append({
                "Date": row["filing_date"],
                "Source": "FERC",
                "Category": row["docket"] or "Unknown",
                "Label": f"FERC: {row['docket']} — {str(row['description'])[:60]}",
            })

    if not df_edgar.empty:
        for _, row in df_edgar.iterrows():
            timeline_data.append({
                "Date": row["file_date"],
                "Source": "EDGAR",
                "Category": row["form_type"] or "Unknown",
                "Label": f"EDGAR {row['form_type']}: {str(row['description'])[:60]}",
            })

    if not timeline_data:
        st.info("No filing data available for timeline.")
    else:
        df_tl = pd.DataFrame(timeline_data)
        df_tl["Date"] = pd.to_datetime(df_tl["Date"], errors="coerce")
        df_tl = df_tl.dropna(subset=["Date"]).sort_values("Date")

        fig_tl = px.scatter(
            df_tl,
            x="Date",
            y="Source",
            color="Category",
            hover_data=["Label"],
            title="Regulatory Filing Timeline",
            template="plotly_dark",
            symbol="Source",
        )
        fig_tl.update_traces(marker=dict(size=10, opacity=0.8))
        fig_tl.update_layout(
            hovermode="closest",
            legend=dict(orientation="h", y=-0.3),
            margin=dict(t=40, b=10),
            height=350,
        )
        st.plotly_chart(fig_tl, use_container_width=True)

    # Monthly filing count bar chart
    if timeline_data:
        df_tl_monthly = (
            df_tl.set_index("Date")
            .resample("ME")["Source"]
            .count()
            .reset_index()
            .rename(columns={"Date": "Month", "Source": "Filings"})
        )
        if not df_tl_monthly.empty:
            fig_monthly = px.bar(
                df_tl_monthly,
                x="Month",
                y="Filings",
                title="Monthly Filing Count (FERC + EDGAR)",
                template="plotly_dark",
            )
            fig_monthly.update_layout(margin=dict(t=40, b=10))
            st.plotly_chart(fig_monthly, use_container_width=True)

    st.divider()

    # ── SLR status table ───────────────────────────────────────────────────────
    st.subheader("Subsequent License Renewal (SLR) Status")

    cfg = _load_plant_config()
    plants = cfg.get("plants", {})

    slr_rows = []
    for plant_key, plant in plants.items():
        name = plant.get("name", plant_key)
        slr_status = plant.get("slr_status", "—")
        nrc_dockets = ", ".join(plant.get("nrc_dockets", []))
        expiry = plant.get("license_expiry", {})

        # Build expiry string
        if isinstance(expiry, dict):
            expiry_str = ", ".join(f"{k}: {v}" for k, v in expiry.items())
        else:
            expiry_str = str(expiry)

        # Reactor type and state
        reactor = plant.get("reactor_type", "—")
        state = plant.get("state", "—")
        net_mw = plant.get("net_mw", "—")

        slr_rows.append({
            "Plant": name,
            "State": state,
            "Type": reactor,
            "Net MW": net_mw,
            "NRC Dockets": nrc_dockets,
            "License Expiry": expiry_str,
            "SLR Status": slr_status,
        })

    df_slr = pd.DataFrame(slr_rows)

    def _slr_color(status: str) -> str:
        s = str(status).lower()
        if "approved" in s:
            return "background-color: #1a472a; color: #2ecc71"
        elif "pending" in s or "filed" in s or "expected" in s or "application" in s:
            return "background-color: #4a3f00; color: #f1c40f"
        elif "restart" in s or "operating" in s:
            return "background-color: #1a3a5c; color: #3498db"
        elif "preparation" in s or "planned" in s or "meeting" in s:
            return "background-color: #3d1a3d; color: #9b59b6"
        return ""

    st.dataframe(
        df_slr,
        use_container_width=True,
        hide_index=True,
        column_config={
            "SLR Status": st.column_config.TextColumn("SLR Status", width="large"),
            "License Expiry": st.column_config.TextColumn("License Expiry", width="medium"),
        },
    )

    conn.close()
