"""
Alert Log — Dashboard Page 10
Displays all system alerts with filtering, severity badges, and trend charts.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, date


# ── Constants ─────────────────────────────────────────────────────────────────

SEVERITY_COLORS = {
    "CRITICAL": "#FF1744",
    "HIGH": "#FF6D00",
    "MEDIUM": "#FFD600",
    "LOW": "#69F0AE",
    "INFO": "#40C4FF",
}

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _severity_badge(sev: str) -> str:
    color = SEVERITY_COLORS.get(str(sev).upper(), "#888")
    return (
        f'<span style="background:{color};color:#000;padding:2px 10px;'
        f'border-radius:4px;font-size:12px;font-weight:700">'
        f'{sev}</span>'
    )


def _sent_badge(sent) -> str:
    if sent:
        return '<span style="color:#69F0AE;font-weight:700">✓ Sent</span>'
    return '<span style="color:#888">Pending</span>'


# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def _load_alerts() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT id, timestamp, severity, category, title, body, sent
        FROM alert_log
        ORDER BY timestamp DESC
    """, conn)
    conn.close()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["severity"] = df["severity"].str.upper()
        df["category"] = df["category"].fillna("Uncategorized")
    return df


# ── render ────────────────────────────────────────────────────────────────────

def render():
    st.header("Alert Log")

    df = _load_alerts()
    today = date.today().strftime("%Y-%m-%d")

    # ── KPI metrics ───────────────────────────────────────────────────────────
    total = len(df)
    critical = len(df[df["severity"] == "CRITICAL"]) if not df.empty else 0
    today_count = (
        len(df[df["timestamp"].dt.strftime("%Y-%m-%d") == today]) if not df.empty else 0
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Alerts", total)
    c2.metric("Critical Alerts", critical, delta="⚠" if critical > 0 else None,
              delta_color="inverse" if critical > 0 else "off")
    c3.metric("Alerts Today", today_count)
    unsent = len(df[df["sent"] == 0]) if not df.empty else 0
    c4.metric("Unsent Alerts", unsent, delta="⚠" if unsent > 0 else None,
              delta_color="inverse" if unsent > 0 else "off")

    st.divider()

    if df.empty:
        st.info("No alerts logged yet — system is quiet or collectors have not run.")
        return

    # ── Filters ───────────────────────────────────────────────────────────────
    all_severities = [s for s in SEVERITY_ORDER if s in df["severity"].unique()]
    all_categories = sorted(df["category"].unique().tolist())

    f_col1, f_col2, f_col3 = st.columns([2, 2, 1])
    with f_col1:
        sel_sev = st.multiselect(
            "Filter by Severity", all_severities, default=all_severities, key="alert_sev_filter"
        )
    with f_col2:
        sel_cat = st.multiselect(
            "Filter by Category", all_categories, default=all_categories, key="alert_cat_filter"
        )
    with f_col3:
        show_sent = st.radio("Sent Status", ["All", "Sent", "Unsent"], key="alert_sent_filter")

    filtered = df.copy()
    if sel_sev:
        filtered = filtered[filtered["severity"].isin(sel_sev)]
    if sel_cat:
        filtered = filtered[filtered["category"].isin(sel_cat)]
    if show_sent == "Sent":
        filtered = filtered[filtered["sent"] == 1]
    elif show_sent == "Unsent":
        filtered = filtered[filtered["sent"] == 0]

    st.caption(f"Showing **{len(filtered)}** of {total} alerts")

    # ── Alert table ───────────────────────────────────────────────────────────
    st.subheader("Alert Feed")

    if filtered.empty:
        st.info("No alerts match the current filters.")
    else:
        disp = filtered.copy()
        disp["Severity"] = disp["severity"].apply(_severity_badge)
        disp["Sent"] = disp["sent"].apply(_sent_badge)
        disp["Timestamp"] = disp["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        disp["Body Preview"] = disp["body"].fillna("").apply(
            lambda b: (b[:120] + "…") if len(str(b)) > 120 else b
        )
        disp = disp.rename(columns={"category": "Category", "title": "Title", "id": "ID"})
        disp = disp[["ID", "Timestamp", "Severity", "Category", "Title", "Body Preview", "Sent"]]

        st.write(disp.to_html(escape=False, index=False), unsafe_allow_html=True)

    # Expandable body viewer
    with st.expander("View full alert body"):
        if filtered.empty:
            st.write("No alerts to display.")
        else:
            alert_options = {
                f"#{row['id']} — {row['title'][:60]}": row["id"]
                for _, row in filtered.head(50).iterrows()
            }
            selected_title = st.selectbox("Select alert", list(alert_options.keys()), key="alert_body_select")
            selected_id = alert_options[selected_title]
            row = filtered[filtered["id"] == selected_id].iloc[0]
            sev_color = SEVERITY_COLORS.get(row["severity"], "#888")
            st.markdown(
                f"""
                <div style="background:#1A1F2B;padding:16px;border-radius:8px;
                            border-left:4px solid {sev_color};">
                    <div style="font-size:16px;font-weight:700;color:{sev_color}">
                        {row['severity']} — {row['category']}
                    </div>
                    <div style="font-size:18px;font-weight:600;margin:8px 0;color:#fff">
                        {row['title']}
                    </div>
                    <div style="font-size:13px;color:#aaa;margin-bottom:12px">
                        {row['timestamp'].strftime('%Y-%m-%d %H:%M:%S UTC')}
                    </div>
                    <div style="font-size:14px;color:#FAFAFA;white-space:pre-wrap">{row['body'] or '(no body)'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()

    # ── Charts ────────────────────────────────────────────────────────────────
    chart_col1, chart_col2 = st.columns(2)

    # Alerts by category over time
    with chart_col1:
        st.subheader("Alerts by Category Over Time")
        df_time = df.copy()
        df_time["week"] = df_time["timestamp"].dt.to_period("W").apply(lambda p: p.start_time)
        cat_time = (
            df_time.groupby(["week", "category"])
            .size()
            .reset_index(name="count")
        )
        if not cat_time.empty:
            fig_cat = px.bar(
                cat_time,
                x="week",
                y="count",
                color="category",
                template="plotly_dark",
                labels={"week": "Week", "count": "Alert Count", "category": "Category"},
            )
            fig_cat.update_layout(
                plot_bgcolor="#0E1117",
                paper_bgcolor="#0E1117",
                height=340,
                xaxis_tickangle=-45,
                legend_title_text="Category",
                barmode="stack",
            )
            st.plotly_chart(fig_cat, use_container_width=True)
        else:
            st.info("No data for category time chart.")

    # Alerts by severity
    with chart_col2:
        st.subheader("Alerts by Severity")
        sev_counts = df["severity"].value_counts().reset_index()
        sev_counts.columns = ["severity", "count"]
        # Preserve order
        sev_counts["order"] = sev_counts["severity"].map(
            {s: i for i, s in enumerate(SEVERITY_ORDER)}
        ).fillna(99)
        sev_counts = sev_counts.sort_values("order")

        color_seq = [SEVERITY_COLORS.get(s, "#888") for s in sev_counts["severity"]]

        fig_sev = go.Figure(go.Bar(
            x=sev_counts["severity"],
            y=sev_counts["count"],
            marker_color=color_seq,
            text=sev_counts["count"],
            textposition="outside",
        ))
        fig_sev.update_layout(
            template="plotly_dark",
            plot_bgcolor="#0E1117",
            paper_bgcolor="#0E1117",
            height=340,
            showlegend=False,
            xaxis_title="Severity",
            yaxis_title="Count",
        )
        st.plotly_chart(fig_sev, use_container_width=True)

    st.divider()

    # ── Cumulative alert trend ────────────────────────────────────────────────
    st.subheader("Cumulative Alert Volume")

    df_cum = df[["timestamp"]].copy().sort_values("timestamp")
    df_cum["cumulative"] = range(1, len(df_cum) + 1)

    fig_cum = go.Figure(go.Scatter(
        x=df_cum["timestamp"],
        y=df_cum["cumulative"],
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(30,136,229,0.15)",
        line=dict(color="#1E88E5", width=2),
        name="Cumulative Alerts",
    ))
    fig_cum.update_layout(
        template="plotly_dark",
        plot_bgcolor="#0E1117",
        paper_bgcolor="#0E1117",
        height=260,
        showlegend=False,
        xaxis_title="",
        yaxis_title="Total Alerts",
    )
    st.plotly_chart(fig_cum, use_container_width=True)
