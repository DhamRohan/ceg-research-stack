"""
PJM LMP Collector using gridstatus library.
Pulls day-ahead and real-time LMPs for CEG nuclear plant nodes.
"""
import pandas as pd
from datetime import datetime, date, timedelta
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

# CEG plant pnode name search patterns — gridstatus returns full pnode names
# We search for these substrings in the Location Name column
CEG_PNODE_PATTERNS = {
    "BRAIDWD": "Braidwood",
    "BYRON": "Byron",
    "CALVERT": "Calvert Cliffs",
    "CLINTON": "Clinton",
    "DRESDEN": "Dresden",
    "LASALLE": "LaSalle",
    "LIMRCK": "Limerick",
    "LIMERICK": "Limerick",
    "NINEMILE": "Nine Mile Point",
    "NINE MILE": "Nine Mile Point",
    "PEACHBOT": "Peach Bottom",
    "PEACH": "Peach Bottom",
    "QUADCIT": "Quad Cities",
    "QUAD": "Quad Cities",
    "GINNA": "Ginna",
    "THREE MILE": "Crane (TMI-1)",
    "TMI": "Crane (TMI-1)"
}

def _get_pjm():
    """Get PJM gridstatus instance. Import here to avoid import errors when gridstatus not installed."""
    try:
        from gridstatus import PJM
        return PJM()
    except ImportError:
        print("  WARNING: gridstatus not installed. Run: pip install gridstatus")
        return None

def _filter_ceg_nodes(df: pd.DataFrame) -> pd.DataFrame:
    """Filter LMP dataframe to only CEG plant nodes."""
    if df.empty or "Location Name" not in df.columns:
        return pd.DataFrame()
    
    mask = pd.Series(False, index=df.index)
    plant_map = pd.Series("", index=df.index)
    
    for pattern, plant_name in CEG_PNODE_PATTERNS.items():
        match = df["Location Name"].str.contains(pattern, case=False, na=False)
        mask = mask | match
        plant_map = plant_map.where(~match, plant_name)
    
    result = df[mask].copy()
    result["plant"] = plant_map[mask]
    return result

def fetch_realtime_lmp(target_date=None) -> pd.DataFrame:
    """Fetch real-time 5-minute LMPs for today."""
    pjm = _get_pjm()
    if pjm is None:
        return pd.DataFrame()
    
    try:
        if target_date is None:
            target_date = "today"
        df = pjm.get_lmp(date=target_date, market="REAL_TIME_5_MIN")
        return _filter_ceg_nodes(df)
    except Exception as e:
        print(f"  Error fetching RT LMP: {e}")
        return pd.DataFrame()

def fetch_dayahead_lmp(target_date=None) -> pd.DataFrame:
    """Fetch day-ahead hourly LMPs."""
    pjm = _get_pjm()
    if pjm is None:
        return pd.DataFrame()
    
    try:
        if target_date is None:
            target_date = "today"
        df = pjm.get_lmp(date=target_date, market="DAY_AHEAD_HOURLY")
        return _filter_ceg_nodes(df)
    except Exception as e:
        print(f"  Error fetching DA LMP: {e}")
        return pd.DataFrame()

def fetch_pjm_load(target_date=None) -> pd.DataFrame:
    """Fetch PJM system load."""
    pjm = _get_pjm()
    if pjm is None:
        return pd.DataFrame()
    try:
        if target_date is None:
            target_date = "today"
        return pjm.get_load(date=target_date)
    except Exception as e:
        print(f"  Error fetching load: {e}")
        return pd.DataFrame()

def save_lmp_to_db(df: pd.DataFrame, market: str) -> int:
    """Save LMP data to SQLite."""
    if df.empty:
        return 0
    conn = get_conn()
    count = 0
    
    # Normalize column names
    time_col = None
    for c in ["Time", "Interval Start", "Datetime"]:
        if c in df.columns:
            time_col = c
            break
    
    lmp_col = None
    for c in ["LMP", "Total LMP", "total_lmp_rt"]:
        if c in df.columns:
            lmp_col = c
            break
    
    energy_col = None
    for c in ["Energy", "Energy Component"]:
        if c in df.columns:
            energy_col = c
            break
    
    congestion_col = None
    for c in ["Congestion", "Congestion Component"]:
        if c in df.columns:
            congestion_col = c
            break
    
    loc_col = "Location Name" if "Location Name" in df.columns else None
    
    if not time_col or not lmp_col or not loc_col:
        return 0
    
    for _, row in df.iterrows():
        try:
            dt = str(row[time_col])
            conn.execute(
                """INSERT OR REPLACE INTO pjm_lmp 
                   (datetime, market, pnode_name, lmp_total, lmp_energy, lmp_congestion)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (dt, market, row[loc_col],
                 row.get(lmp_col), row.get(energy_col), row.get(congestion_col))
            )
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count

def get_latest_lmps() -> pd.DataFrame:
    """Get most recent LMPs from DB, aggregated by plant."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT pnode_name, market,
               ROUND(AVG(lmp_total), 2) as avg_lmp,
               MAX(datetime) as latest_time
        FROM pjm_lmp
        WHERE datetime >= datetime('now', '-24 hours')
        GROUP BY pnode_name, market
        ORDER BY pnode_name, market
    """, conn)
    conn.close()
    return df

def get_lmp_history(pnode_pattern: str, days: int = 30) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT date(datetime) as date,
               ROUND(AVG(lmp_total), 2) as avg_lmp,
               ROUND(MAX(lmp_total), 2) as max_lmp,
               ROUND(MIN(lmp_total), 2) as min_lmp
        FROM pjm_lmp
        WHERE pnode_name LIKE ? AND datetime >= date('now', ? || ' days')
        GROUP BY date(datetime)
        ORDER BY date
    """, conn, params=(f"%{pnode_pattern}%", f"-{days}"))
    conn.close()
    return df

def run():
    print(f"[{datetime.now()}] Fetching PJM LMP data...")
    
    # Day-ahead
    da = fetch_dayahead_lmp()
    da_count = save_lmp_to_db(da, "DAY_AHEAD")
    print(f"  Day-ahead: {da_count} records, {da['plant'].nunique() if not da.empty and 'plant' in da.columns else 0} plants")
    
    # Real-time (may fail outside market hours)
    rt = fetch_realtime_lmp()
    rt_count = save_lmp_to_db(rt, "REAL_TIME")
    print(f"  Real-time: {rt_count} records")
    
    return {"da_records": da_count, "rt_records": rt_count}

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
