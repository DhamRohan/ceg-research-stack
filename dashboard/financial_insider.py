"""
Financial & Insider Activity — Dashboard Page 6
Displays insider trades, EDGAR filings, and institutional holdings.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta


# ── helpers ──────────────────────────────────────────────────────────────────

_CODE_MAP = {"P": "BUY", "S": "SELL", "A": "AWARD", "M": "EXERCISE", "G": "GIFT", "F": "TAX_WITHHOLD"}
_CODE_COLOR = {"BUY": "#00C853", "SELL": "#FF1744", "AWARD": "#448AFF", "EXERCISE": "#FFD600",
               "GIFT": "#BA68C8", "TAX_WITHHOLD": "#78909C"}


def _badge(action: str) -> str:
    color = _CODE_COLOR.get(action, "#888")
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{action}</span>'


def _fmt_currency(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:,.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:,.1f}K"
    return f"${v:,.2f}"


def _fmt_shares(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v):,.0f}"


# ── data loaders ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _load_insider_trades() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT owner_name, owner_title, transaction_date, transaction_code,
               direction, shares, price_per_share, value, shares_after, security_title
        FROM insider_trades
        ORDER BY transaction_date DESC
        LIMIT 500
    """, conn)
    conn.close()
    return df


@st.cache_data(ttl=300)
def _load_six_month_summary() -> dict:
    conn = get_conn()
    cutoff = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    df = pd.read_sql_query(f"""
        SELECT transaction_code, COALESCE(SUM(value), 0) AS total_value
        FROM insider_trades
        WHERE transaction_date >= '{cutoff}'
          AND transaction_code IN ('P', 'S')
        GROUP BY transaction_code
    """, conn)
    conn.close()
    buy_val = df.loc[df["transaction_code"] == "P", "total_value"].sum()
    sell_val = df.loc[df["transaction_code"] == "S", "total_value"].sum()
    return {"buy": buy_val, "sell": sell_val, "net": buy_val - sell_val}


@st.cache_data(ttl=300)
def _load_monthly_volumes() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT
            strftime('%Y-%m', transaction_date) AS month,
            transaction_code,
            COALESCE(SUM(value), 0) AS total_value
        FROM insider_trades
        WHERE transaction_code IN ('P', 'S')
          AND transaction_date >= date('now', '-18 months')
        GROUP BY month, transaction_code
        ORDER BY month
    """, conn)
    conn.close()
    return df


@st.cache_data(ttl=300)
def _load_edgar_filings() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT accession_no, form_type, file_date, description, url
        FROM edgar_filings
        ORDER BY file_date DESC
        LIMIT 100
    """, conn)
    conn.close()
    return df


@st.cache_data(ttl=300)
def _load_institutional_holdings() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT manager_name, report_date, shares, value_thousands,
               change_shares, change_pct
        FROM institutional_holdings
        ORDER BY value_thousands DESC
        LIMIT 50
    """, conn)
    conn.close()
    return df


# ── render ───────────────────────────────────────────────────────────────────

def render():
    st.header("Financial & Insider Activity")

    # ── KPI metrics ──────────────────────────────────────────────────────────
    summary = _load_six_month_summary()
    net = summary["net"]
    net_dir = "↑" if net > 0 else ("↓" if net < 0 else "—")
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Net Insider Activity (6 mo)",
        _fmt_currency(abs(net)),
        delta=f"{net_dir} {'Net Buy' if net >= 0 else 'Net Sell'}",
        delta_color="normal" if net >= 0 else "inverse",
    )
    col2.metric("Total Buy Value (6 mo)", _fmt_currency(summary["buy"]))
    col3.metric("Total Sell Value (6 mo)", _fmt_currency(summary["sell"]))

    st.divider()

    # ── Insider trades table ─────────────────────────────────────────────────
    st.subheader("Recent Insider Transactions")
    trades_df = _load_insider_trades()

    if trades_df.empty:
        st.info("No insider trade data yet — run collectors first.")
    else:
        # Map codes to action labels
        trades_df["action"] = trades_df["transaction_code"].map(_CODE_MAP).fillna(
            trades_df["transaction_code"]
        )

        # Filter controls
        action_opts = sorted(trades_df["action"].unique().tolist())
        sel_actions = st.multiselect(
            "Filter by action", action_opts, default=action_opts, key="insider_action_filter"
        )
        filtered = trades_df[trades_df["action"].isin(sel_actions)]

        display = filtered[[
            "owner_name", "owner_title", "transaction_date", "action",
            "shares", "price_per_share", "value", "security_title"
        ]].copy()
        display.columns = ["Name", "Title", "Date", "Action", "Shares", "Price", "Value", "Security"]
        display["Shares"] = display["Shares"].apply(_fmt_shares)
        display["Price"] = display["Price"].apply(lambda v: f"${float(v):,.2f}" if pd.notna(v) else "—")
        display["Value"] = display["Value"].apply(_fmt_currency)
        display["Action"] = display["Action"].apply(_badge)

        # Render with HTML for colored badges
        st.write(
            display.to_html(escape=False, index=False),
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Monthly buy vs sell bar chart ────────────────────────────────────────
    st.subheader("Monthly Insider Buy vs Sell Volume")
    monthly = _load_monthly_volumes()

    if monthly.empty:
        st.info("No monthly volume data yet — run collectors first.")
    else:
        monthly["label"] = monthly["transaction_code"].map({"P": "Buy", "S": "Sell"}).fillna(monthly["transaction_code"])
        monthly["total_value_m"] = monthly["total_value"] / 1_000_000

        fig = px.bar(
            monthly,
            x="month",
            y="total_value_m",
            color="label",
            barmode="group",
            color_discrete_map={"Buy": "#00C853", "Sell": "#FF1744"},
            labels={"month": "Month", "total_value_m": "Value ($M)", "label": "Type"},
            template="plotly_dark",
        )
        fig.update_layout(
            plot_bgcolor="#0E1117",
            paper_bgcolor="#0E1117",
            legend_title_text="Transaction",
            xaxis_tickangle=-45,
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── EDGAR filings ────────────────────────────────────────────────────────
    st.subheader("Recent SEC / EDGAR Filings")
    edgar_df = _load_edgar_filings()

    if edgar_df.empty:
        st.info("No EDGAR filing data yet — run collectors first.")
    else:
        _FORM_COLORS = {
            "4": "#1E88E5",
            "SC 13G": "#7B1FA2",
            "SC 13G/A": "#AB47BC",
            "SC 13D": "#E53935",
            "10-K": "#00897B",
            "10-Q": "#00ACC1",
            "8-K": "#F4511E",
            "DEF 14A": "#6D4C41",
            "S-3": "#546E7A",
        }

        def form_badge(form):
            color = _FORM_COLORS.get(form, "#546E7A")
            return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{form}</span>'

        disp = edgar_df.copy()
        disp["form_type"] = disp["form_type"].apply(form_badge)
        disp["url"] = disp["url"].apply(
            lambda u: f'<a href="{u}" target="_blank" style="color:#1E88E5">View</a>' if pd.notna(u) and u else "—"
        )
        disp = disp.rename(columns={
            "accession_no": "Accession No.",
            "form_type": "Form Type",
            "file_date": "Filed Date",
            "description": "Description",
            "url": "Link",
        })
        st.write(disp.to_html(escape=False, index=False), unsafe_allow_html=True)

    st.divider()

    # ── Institutional holdings ───────────────────────────────────────────────
    st.subheader("Institutional Holdings (13-F)")
    inst_df = _load_institutional_holdings()

    if inst_df.empty:
        st.info("No institutional holdings data yet — run collectors first.")
    else:
        disp = inst_df.copy()
        disp["shares"] = disp["shares"].apply(_fmt_shares)
        disp["value_thousands"] = disp["value_thousands"].apply(
            lambda v: _fmt_currency(float(v) * 1000) if pd.notna(v) else "—"
        )
        disp["change_shares"] = disp["change_shares"].apply(
            lambda v: (f"+{_fmt_shares(v)}" if float(v) >= 0 else _fmt_shares(v)) if pd.notna(v) else "—"
        )
        disp["change_pct"] = disp["change_pct"].apply(
            lambda v: f"{float(v):+.2f}%" if pd.notna(v) else "—"
        )
        disp = disp.rename(columns={
            "manager_name": "Manager",
            "report_date": "Report Date",
            "shares": "Shares",
            "value_thousands": "Value",
            "change_shares": "Δ Shares",
            "change_pct": "Δ %",
        })
        st.dataframe(disp, use_container_width=True, hide_index=True)
