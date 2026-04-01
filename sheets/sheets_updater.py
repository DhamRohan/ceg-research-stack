"""
Google Sheets Sync Module
Pushes key data summaries to a shared Google Sheet for stakeholder visibility.
"""
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn
from config.secrets import GOOGLE_SHEET_ID, get_google_service_account_info

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

TABS = {
    "Fleet Status":     "fleet_status",
    "Power Markets":    "power_markets",
    "Signal Scorecard": "signal_scorecard",
    "Insider Trades":   "insider_trades",
    "Alert Log":        "alert_log",
    "EIA Generation":   "eia_generation",
    "FERC Dockets":     "ferc_dockets",
}


def get_gspread_client() -> gspread.Client:
    """Authenticate and return gspread client."""
    sa_info = get_google_service_account_info()
    if not sa_info:
        raise ValueError("No Google service account credentials found")
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return gspread.authorize(creds)


def get_or_create_worksheet(spreadsheet, title: str, rows: int = 1000, cols: int = 20):
    """Get existing worksheet or create a new one."""
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def clear_and_write(ws, df: pd.DataFrame):
    """Clear worksheet and write dataframe with headers."""
    ws.clear()
    if df.empty:
        ws.update([["No data"]], value_input_option="RAW")
        return
    # Convert to strings to avoid serialization issues
    df = df.fillna("")
    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    ws.update(data, value_input_option="RAW")
    
    # Format header row
    try:
        ws.format("1:1", {
            "backgroundColor": {"red": 0.1, "green": 0.1, "blue": 0.18},
            "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True, "fontSize": 10},
        })
    except Exception:
        pass


def sync_fleet_status(spreadsheet):
    """Sync NRC fleet status tab."""
    conn = get_conn()
    df = pd.read_sql_query("""
        WITH latest AS (
            SELECT unit, power_pct, date as latest_date
            FROM nrc_status
            WHERE date = (SELECT MAX(date) FROM nrc_status)
        ),
        avg7 AS (
            SELECT unit, ROUND(AVG(power_pct), 1) as avg_7d
            FROM nrc_status WHERE date >= date('now', '-7 days')
            GROUP BY unit
        ),
        avg30 AS (
            SELECT unit, ROUND(AVG(power_pct), 1) as avg_30d
            FROM nrc_status WHERE date >= date('now', '-30 days')
            GROUP BY unit
        )
        SELECT l.unit as "Unit", l.power_pct as "Current %", l.latest_date as "Date",
               COALESCE(a7.avg_7d, l.power_pct) as "7-Day Avg",
               COALESCE(a30.avg_30d, l.power_pct) as "30-Day Avg",
               CASE WHEN l.power_pct < 10 THEN 'OUTAGE'
                    WHEN l.power_pct < 80 THEN 'REDUCED'
                    ELSE 'NORMAL' END as "Status"
        FROM latest l
        LEFT JOIN avg7 a7 ON l.unit = a7.unit
        LEFT JOIN avg30 a30 ON l.unit = a30.unit
        ORDER BY l.unit
    """, conn)
    conn.close()
    ws = get_or_create_worksheet(spreadsheet, "Fleet Status")
    clear_and_write(ws, df)
    return len(df)


def sync_power_markets(spreadsheet):
    """Sync PJM LMP summary tab."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT pnode_name as "Node",
               ROUND(AVG(lmp_total), 2) as "Avg LMP ($/MWh)",
               ROUND(MAX(lmp_total), 2) as "Max LMP",
               ROUND(MIN(lmp_total), 2) as "Min LMP",
               COUNT(*) as "Observations",
               MAX(datetime) as "Latest Data"
        FROM pjm_lmp
        WHERE datetime >= datetime('now', '-7 days')
        GROUP BY pnode_name
        ORDER BY "Avg LMP ($/MWh)" DESC
    """, conn)
    conn.close()
    ws = get_or_create_worksheet(spreadsheet, "Power Markets")
    clear_and_write(ws, df)
    return len(df)


def sync_signal_scorecard(spreadsheet):
    """Sync composite signal scorecard tab."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT date as "Date",
               dimension as "Dimension",
               signal_name as "Signal",
               ROUND(score, 2) as "Score",
               raw_value as "Raw Value",
               notes as "Notes"
        FROM signals
        WHERE date >= date('now', '-30 days')
        ORDER BY date DESC, dimension
    """, conn)
    conn.close()
    ws = get_or_create_worksheet(spreadsheet, "Signal Scorecard")
    clear_and_write(ws, df)
    return len(df)


def sync_insider_trades(spreadsheet):
    """Sync insider trades tab."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT owner_name as "Insider",
               owner_title as "Title",
               transaction_date as "Date",
               CASE transaction_code
                   WHEN 'P' THEN 'BUY' WHEN 'S' THEN 'SELL'
                   WHEN 'A' THEN 'AWARD' WHEN 'M' THEN 'EXERCISE'
                   ELSE transaction_code END as "Action",
               shares as "Shares",
               price_per_share as "Price",
               value as "Value ($)",
               security_title as "Security"
        FROM insider_trades
        ORDER BY transaction_date DESC
        LIMIT 100
    """, conn)
    conn.close()
    ws = get_or_create_worksheet(spreadsheet, "Insider Trades")
    clear_and_write(ws, df)
    return len(df)


def sync_alert_log(spreadsheet):
    """Sync alert log tab."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT timestamp as "Time",
               severity as "Severity",
               category as "Category",
               title as "Title",
               body as "Details",
               CASE sent WHEN 1 THEN 'Yes' ELSE 'No' END as "Email Sent"
        FROM alert_log
        ORDER BY timestamp DESC
        LIMIT 200
    """, conn)
    conn.close()
    ws = get_or_create_worksheet(spreadsheet, "Alert Log")
    clear_and_write(ws, df)
    return len(df)


def sync_eia_generation(spreadsheet):
    """Sync EIA generation data tab."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT period as "Period",
               plant_name as "Plant",
               generation_mwh as "Generation (MWh)",
               capacity_factor as "Capacity Factor (%)"
        FROM eia_generation
        ORDER BY period DESC, plant_name
        LIMIT 200
    """, conn)
    conn.close()
    ws = get_or_create_worksheet(spreadsheet, "EIA Generation")
    clear_and_write(ws, df)
    return len(df)


def sync_ferc_dockets(spreadsheet):
    """Sync FERC docket filings tab."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT docket as "Docket",
               filing_date as "Filed",
               document_type as "Type",
               description as "Description",
               url as "URL"
        FROM ferc_filings
        ORDER BY filing_date DESC
        LIMIT 100
    """, conn)
    conn.close()
    ws = get_or_create_worksheet(spreadsheet, "FERC Dockets")
    clear_and_write(ws, df)
    return len(df)


def run():
    """Sync all tabs to Google Sheets."""
    print(f"[{datetime.now()}] Syncing to Google Sheets...")
    
    if not GOOGLE_SHEET_ID:
        print("  WARNING: No Google Sheet ID configured")
        return {"synced": 0}
    
    try:
        gc = get_gspread_client()
        spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
    except Exception as e:
        print(f"  ERROR connecting to Google Sheets: {e}")
        return {"synced": 0, "error": str(e)}
    
    synced = {}
    sync_functions = [
        ("Fleet Status", sync_fleet_status),
        ("Power Markets", sync_power_markets),
        ("Signal Scorecard", sync_signal_scorecard),
        ("Insider Trades", sync_insider_trades),
        ("Alert Log", sync_alert_log),
        ("EIA Generation", sync_eia_generation),
        ("FERC Dockets", sync_ferc_dockets),
    ]
    
    for tab_name, sync_fn in sync_functions:
        try:
            count = sync_fn(spreadsheet)
            synced[tab_name] = count
            print(f"  ✓ {tab_name}: {count} rows")
        except Exception as e:
            synced[tab_name] = f"ERROR: {e}"
            print(f"  ✗ {tab_name}: {e}")
    
    # Update a summary cell on the first sheet
    try:
        main_ws = spreadsheet.sheet1
        main_ws.update(
            [[f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"]],
            "A1",
            value_input_option="RAW"
        )
    except Exception:
        pass
    
    return {"synced": synced}


if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
