"""
FRED API Collector — Macro indicators for utility/nuclear valuation context.
"""
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn
from config.secrets import FRED_API_KEY

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

UTILITY_SERIES = {
    "DGS10": {"name": "10Y Treasury", "freq": "d"},
    "DGS2": {"name": "2Y Treasury", "freq": "d"},
    "T10Y2Y": {"name": "Yield Curve 10Y-2Y", "freq": "d"},
    "BAMLC0A4CBBB": {"name": "BBB Corp OAS", "freq": "d"},
    "FEDFUNDS": {"name": "Fed Funds Rate", "freq": "m"},
    "DCOILWTICO": {"name": "WTI Crude Oil", "freq": "d"},
    "NATURALGAS": {"name": "Henry Hub Gas", "freq": "m"},
    "CPIAUCSL": {"name": "CPI YoY", "freq": "m"},
    "INDPRO": {"name": "Industrial Production", "freq": "m"},
    "VIXCLS": {"name": "VIX", "freq": "d"},
}

def fetch_fred_series(series_id: str, start_date: str = None, 
                      units: str = "lin") -> pd.DataFrame:
    """Fetch a single FRED series."""
    if not FRED_API_KEY:
        print("  WARNING: No FRED API key")
        return pd.DataFrame()
    
    if not start_date:
        start_date = "2020-01-01"
    
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": datetime.now().strftime("%Y-%m-%d"),
        "units": units,
    }
    
    try:
        resp = requests.get(FRED_BASE, params=params, timeout=30)
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        
        records = []
        for o in obs:
            if o["value"] != ".":
                records.append({
                    "date": o["date"],
                    "series_id": series_id,
                    "value": float(o["value"])
                })
        return pd.DataFrame(records)
    except Exception as e:
        print(f"  FRED error for {series_id}: {e}")
        return pd.DataFrame()

def fetch_all_series(start_date: str = "2020-01-01") -> pd.DataFrame:
    """Fetch all utility-relevant FRED series."""
    all_dfs = []
    for series_id, meta in UTILITY_SERIES.items():
        # Use YoY% for CPI
        units = "pc1" if series_id == "CPIAUCSL" else "lin"
        df = fetch_fred_series(series_id, start_date=start_date, units=units)
        if not df.empty:
            all_dfs.append(df)
        time.sleep(0.6)  # Stay under 2 req/sec
    
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()

def save_to_db(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    conn = get_conn()
    count = 0
    for _, row in df.iterrows():
        try:
            conn.execute(
                "INSERT OR REPLACE INTO fred_data (date, series_id, value) VALUES (?, ?, ?)",
                (row["date"], row["series_id"], row["value"])
            )
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count

def get_latest_values() -> pd.DataFrame:
    """Get the most recent observation for each FRED series."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT f.series_id, f.date, f.value
        FROM fred_data f
        INNER JOIN (
            SELECT series_id, MAX(date) as max_date
            FROM fred_data
            GROUP BY series_id
        ) latest ON f.series_id = latest.series_id AND f.date = latest.max_date
        ORDER BY f.series_id
    """, conn)
    conn.close()
    
    # Add friendly names
    df["name"] = df["series_id"].map({k: v["name"] for k, v in UTILITY_SERIES.items()})
    return df

def get_series_history(series_id: str, days: int = 365) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT date, value FROM fred_data
        WHERE series_id = ? AND date >= date('now', ? || ' days')
        ORDER BY date
    """, conn, params=(series_id, f"-{days}"))
    conn.close()
    return df

def get_rate_snapshot() -> dict:
    """Get current rates + 30-day change for key indicators."""
    latest = get_latest_values()
    snapshot = {}
    for _, row in latest.iterrows():
        sid = row["series_id"]
        hist = get_series_history(sid, days=35)
        change_30d = None
        if len(hist) >= 2:
            old_val = hist.iloc[0]["value"]
            new_val = hist.iloc[-1]["value"]
            change_30d = round(new_val - old_val, 3)
        
        snapshot[sid] = {
            "name": row.get("name", sid),
            "value": row["value"],
            "date": row["date"],
            "change_30d": change_30d
        }
    return snapshot

def check_rate_alerts() -> list:
    """Check if 10Y Treasury moved >50bps in 30 days."""
    alerts = []
    hist = get_series_history("DGS10", days=35)
    if len(hist) >= 2:
        change = hist.iloc[-1]["value"] - hist.iloc[0]["value"]
        if abs(change) > 0.50:
            direction = "ROSE" if change > 0 else "FELL"
            alerts.append({
                "severity": "medium",
                "category": "macro",
                "title": f"10Y Treasury {direction} {abs(change):.0f}bps in 30 days",
                "body": f"10Y moved from {hist.iloc[0]['value']:.2f}% to {hist.iloc[-1]['value']:.2f}%. "
                        f"Large rate moves affect utility multiples."
            })
    return alerts

def run():
    print(f"[{datetime.now()}] Fetching FRED macro data...")
    df = fetch_all_series()
    count = save_to_db(df)
    print(f"  Saved {count} observations across {df['series_id'].nunique() if not df.empty else 0} series")
    alerts = check_rate_alerts()
    return {"records": count, "alerts": alerts}

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
