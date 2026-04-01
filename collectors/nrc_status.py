"""
NRC Daily Reactor Power Status Collector
Fetches: https://www.nrc.gov/reading-rm/doc-collections/event-status/reactor-status/powerreactorstatusforlast365days.txt
"""
import pandas as pd
import requests
from datetime import datetime, timedelta
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

NRC_URL = "https://www.nrc.gov/reading-rm/doc-collections/event-status/reactor-status/PowerReactorStatusForLast365Days.txt"

# Map: NRC file unit name (mixed case) -> our canonical name (uppercase)
CEG_UNIT_MAP = {
    "Braidwood 1": "BRAIDWOOD 1", "Braidwood 2": "BRAIDWOOD 2",
    "Byron 1": "BYRON 1", "Byron 2": "BYRON 2",
    "Calvert Cliffs 1": "CALVERT CLIFFS 1", "Calvert Cliffs 2": "CALVERT CLIFFS 2",
    "Clinton 1": "CLINTON 1",
    "Dresden 2": "DRESDEN 2", "Dresden 3": "DRESDEN 3",
    "LaSalle 1": "LASALLE 1", "LaSalle 2": "LASALLE 2",
    "Limerick 1": "LIMERICK 1", "Limerick 2": "LIMERICK 2",
    "Nine Mile Point 1": "NINE MILE POINT 1", "Nine Mile Point 2": "NINE MILE POINT 2",
    "Peach Bottom 2": "PEACH BOTTOM 2", "Peach Bottom 3": "PEACH BOTTOM 3",
    "Quad Cities 1": "QUAD CITIES 1", "Quad Cities 2": "QUAD CITIES 2",
    "Ginna": "GINNA", "R.E. Ginna": "GINNA",
    "Three Mile Island 1": "THREE MILE ISLAND 1",
}
CEG_UNITS = list(set(CEG_UNIT_MAP.values()))

def fetch_nrc_status() -> pd.DataFrame:
    """Fetch NRC reactor status for the last 365 days, filter to CEG units."""
    resp = requests.get(NRC_URL, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    
    lines = resp.text.strip().split("\n")
    records = []
    for line in lines[1:]:  # skip header
        parts = line.split("|")
        if len(parts) >= 3:
            raw_unit = parts[1].strip()
            # Map to canonical name (case-insensitive lookup)
            canonical = CEG_UNIT_MAP.get(raw_unit)
            if not canonical:
                # Try case-insensitive match
                for k, v in CEG_UNIT_MAP.items():
                    if k.upper() == raw_unit.upper():
                        canonical = v
                        break
            if canonical:
                try:
                    power = float(parts[2].strip())
                except (ValueError, IndexError):
                    power = None
                records.append({
                    "date": parts[0].strip(),
                    "unit": canonical,
                    "power_pct": power
                })
    
    df = pd.DataFrame(records)
    if df.empty:
        return df
    
    df["date"] = pd.to_datetime(df["date"], format="mixed").dt.strftime("%Y-%m-%d")
    df = df.drop_duplicates(subset=["date", "unit"], keep="last")
    return df

def save_to_db(df: pd.DataFrame) -> int:
    """Upsert NRC status data into SQLite."""
    if df.empty:
        return 0
    conn = get_conn()
    count = 0
    for _, row in df.iterrows():
        try:
            conn.execute(
                "INSERT OR REPLACE INTO nrc_status (date, unit, power_pct) VALUES (?, ?, ?)",
                (row["date"], row["unit"], row["power_pct"])
            )
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count

def get_latest_status() -> pd.DataFrame:
    """Get the most recent NRC status for all CEG units from DB."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT unit, power_pct, date
        FROM nrc_status
        WHERE date = (SELECT MAX(date) FROM nrc_status)
        ORDER BY unit
    """, conn)
    conn.close()
    return df

def get_fleet_capacity_factor(days: int = 365) -> float:
    """Compute fleet-wide average capacity factor over N days."""
    conn = get_conn()
    df = pd.read_sql_query(f"""
        SELECT AVG(power_pct) as avg_cf
        FROM nrc_status
        WHERE date >= date('now', '-{days} days')
    """, conn)
    conn.close()
    if df.empty or df.iloc[0]["avg_cf"] is None:
        return 0.0
    return round(df.iloc[0]["avg_cf"], 2)

def get_unit_history(unit: str, days: int = 90) -> pd.DataFrame:
    """Get power history for a specific unit."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT date, power_pct FROM nrc_status
        WHERE unit = ? AND date >= date('now', ? || ' days')
        ORDER BY date
    """, conn, params=(unit, f"-{days}"))
    conn.close()
    return df

def get_unit_averages() -> pd.DataFrame:
    """Get current, 7-day, and 30-day averages for all CEG units."""
    conn = get_conn()
    df = pd.read_sql_query("""
        WITH latest AS (
            SELECT unit, power_pct as current_pct, date as latest_date
            FROM nrc_status
            WHERE date = (SELECT MAX(date) FROM nrc_status)
        ),
        avg7 AS (
            SELECT unit, ROUND(AVG(power_pct), 1) as avg_7d
            FROM nrc_status
            WHERE date >= date('now', '-7 days')
            GROUP BY unit
        ),
        avg30 AS (
            SELECT unit, ROUND(AVG(power_pct), 1) as avg_30d
            FROM nrc_status
            WHERE date >= date('now', '-30 days')
            GROUP BY unit
        )
        SELECT l.unit, l.current_pct, l.latest_date,
               COALESCE(a7.avg_7d, l.current_pct) as avg_7d,
               COALESCE(a30.avg_30d, l.current_pct) as avg_30d
        FROM latest l
        LEFT JOIN avg7 a7 ON l.unit = a7.unit
        LEFT JOIN avg30 a30 ON l.unit = a30.unit
        ORDER BY l.unit
    """, conn)
    conn.close()
    return df

def check_outage_alerts() -> list:
    """Check for units that dropped from >90% to <10% in 24 hours."""
    conn = get_conn()
    alerts = []
    df = pd.read_sql_query("""
        WITH recent AS (
            SELECT unit, power_pct, date,
                   LAG(power_pct) OVER (PARTITION BY unit ORDER BY date) as prev_pct
            FROM nrc_status
            WHERE date >= date('now', '-3 days')
        )
        SELECT unit, power_pct, prev_pct, date
        FROM recent
        WHERE prev_pct > 90 AND power_pct < 10
    """, conn)
    conn.close()
    for _, row in df.iterrows():
        alerts.append({
            "severity": "critical",
            "category": "nuclear_ops",
            "title": f"UNPLANNED OUTAGE: {row['unit']}",
            "body": f"{row['unit']} dropped from {row['prev_pct']}% to {row['power_pct']}% on {row['date']}"
        })
    return alerts

def run():
    """Main collection routine."""
    print(f"[{datetime.now()}] Fetching NRC reactor status...")
    df = fetch_nrc_status()
    count = save_to_db(df)
    print(f"  Saved {count} records for {df['unit'].nunique()} CEG units")
    alerts = check_outage_alerts()
    if alerts:
        print(f"  ALERTS: {len(alerts)} outage alerts detected!")
    return {"records": count, "alerts": alerts}

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
