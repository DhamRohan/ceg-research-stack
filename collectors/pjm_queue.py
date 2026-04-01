"""
PJM Interconnection Queue Collector — Download, diff, and filter for load near CEG plants.
"""
import pandas as pd
import requests
from math import radians, cos, sin, asin, sqrt
from datetime import datetime
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

QUEUE_URL = "https://www.pjm.com/-/media/DotCom/planning/interconnection-agreements/queue/activequeue.xlsx"

CEG_COUNTIES = {
    "Will": "Braidwood", "Ogle": "Byron", "Calvert": "Calvert Cliffs",
    "DeWitt": "Clinton", "Grundy": "Dresden", "LaSalle": "LaSalle",
    "Montgomery": "Limerick", "Oswego": "Nine Mile Point",
    "York": "Peach Bottom", "Rock Island": "Quad Cities",
    "Wayne": "Ginna", "Dauphin": "Crane (TMI-1)"
}

CEG_TO_ZONES = ["COMED", "PECO", "PPL", "BGE", "PSEG"]

def _load_plants() -> dict:
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "plant_config.json")
    with open(cfg_path) as f:
        return json.load(f)["plants"]

def haversine(lat1, lon1, lat2, lon2) -> float:
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 2 * 6371 * asin(sqrt(a))

def download_queue() -> pd.DataFrame:
    """Download the PJM active interconnection queue spreadsheet."""
    raw_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    os.makedirs(raw_dir, exist_ok=True)
    
    filepath = os.path.join(raw_dir, "pjm_queue_latest.xlsx")
    
    try:
        resp = requests.get(QUEUE_URL, timeout=120)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        
        # Try reading — PJM sometimes changes sheet names
        try:
            df = pd.read_excel(filepath, engine="openpyxl")
        except Exception:
            df = pd.read_excel(filepath, sheet_name=0, engine="openpyxl")
        
        return df
    except Exception as e:
        print(f"  PJM queue download error: {e}")
        return pd.DataFrame()

def filter_load_projects(df: pd.DataFrame) -> pd.DataFrame:
    """Filter queue to load-type projects."""
    if df.empty:
        return df
    
    # Find the fuel/type column (PJM changes names)
    fuel_col = None
    for c in df.columns:
        cl = str(c).lower()
        if "fuel" in cl or "type" in cl and "project" in cl:
            fuel_col = c
            break
    
    if fuel_col is None:
        # Try broader search
        for c in df.columns:
            if "fuel" in str(c).lower():
                fuel_col = c
                break
    
    if fuel_col:
        load_df = df[df[fuel_col].astype(str).str.contains("load|storage|battery", case=False, na=False)]
    else:
        load_df = df  # Return all if can't find filter column
    
    return load_df

def filter_near_ceg(df: pd.DataFrame) -> pd.DataFrame:
    """Filter projects in CEG counties or TO zones."""
    if df.empty:
        return df
    
    # Find county column
    county_col = None
    for c in df.columns:
        if "county" in str(c).lower():
            county_col = c
            break
    
    # Find TO column
    to_col = None
    for c in df.columns:
        cl = str(c).lower()
        if "transmission" in cl and "owner" in cl:
            to_col = c
            break
        if cl == "to" or "trans" in cl:
            to_col = c
            break
    
    state_col = None
    for c in df.columns:
        if "state" in str(c).lower():
            state_col = c
            break
    
    mask = pd.Series(False, index=df.index)
    
    if county_col:
        for county in CEG_COUNTIES:
            mask = mask | df[county_col].astype(str).str.contains(county, case=False, na=False)
    
    if to_col:
        for zone in CEG_TO_ZONES:
            mask = mask | df[to_col].astype(str).str.contains(zone, case=False, na=False)
    
    return df[mask]

def save_to_db(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    
    conn = get_conn()
    count = 0
    
    # Map columns dynamically
    col_map = {}
    for c in df.columns:
        cl = str(c).lower()
        if "queue" in cl and ("number" in cl or "no" in cl or "#" in cl):
            col_map["queue_number"] = c
        elif "queue" in cl and "date" in cl:
            col_map["queue_date"] = c
        elif "project" in cl and "name" in cl:
            col_map["project_name"] = c
        elif "fuel" in cl or ("type" in cl and "project" in cl):
            col_map["fuel_type"] = c
        elif cl in ("mw", "capacity") or "mw" in cl:
            col_map["mw"] = c
        elif "state" in cl and len(cl) < 10:
            col_map["state"] = c
        elif "county" in cl:
            col_map["county"] = c
        elif "status" in cl:
            col_map["status"] = c
    
    qn_col = col_map.get("queue_number")
    if not qn_col:
        # Use first column as identifier
        qn_col = df.columns[0]
    
    for _, row in df.iterrows():
        try:
            qn = str(row.get(qn_col, ""))
            if not qn:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO pjm_queue
                   (queue_number, queue_date, project_name, fuel_type, mw, state, county, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (qn,
                 str(row.get(col_map.get("queue_date", ""), ""))[:10],
                 str(row.get(col_map.get("project_name", ""), ""))[:200],
                 str(row.get(col_map.get("fuel_type", ""), "")),
                 pd.to_numeric(row.get(col_map.get("mw", ""), None), errors="coerce"),
                 str(row.get(col_map.get("state", ""), "")),
                 str(row.get(col_map.get("county", ""), "")),
                 str(row.get(col_map.get("status", ""), "")))
            )
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count

def get_load_near_ceg() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM pjm_queue
        WHERE fuel_type LIKE '%load%' OR fuel_type LIKE '%Load%'
              OR fuel_type LIKE '%Storage%' OR fuel_type LIKE '%Battery%'
        ORDER BY queue_date DESC
    """, conn)
    conn.close()
    return df

def get_new_entries(days: int = 7) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(f"""
        SELECT * FROM pjm_queue
        WHERE first_seen >= date('now', '-{days} days')
        ORDER BY first_seen DESC
    """, conn)
    conn.close()
    return df

def check_queue_alerts() -> list:
    """Check for new large load entries near CEG plants."""
    new = get_new_entries(days=7)
    if new.empty:
        return []
    
    alerts = []
    for _, row in new.iterrows():
        mw = row.get("mw", 0) or 0
        if mw > 50:
            alerts.append({
                "severity": "medium",
                "category": "data_center",
                "title": f"New {mw:.0f} MW load in PJM queue: {row.get('project_name', 'Unknown')[:60]}",
                "body": f"State: {row.get('state', 'N/A')}, County: {row.get('county', 'N/A')}, "
                        f"Queue #: {row.get('queue_number', 'N/A')}"
            })
    return alerts

def run():
    print(f"[{datetime.now()}] Downloading PJM interconnection queue...")
    full_queue = download_queue()
    print(f"  Total queue entries: {len(full_queue)}")
    
    load = filter_load_projects(full_queue)
    print(f"  Load-type projects: {len(load)}")
    
    near_ceg = filter_near_ceg(full_queue)
    count = save_to_db(near_ceg)
    print(f"  Near-CEG entries saved: {count}")
    
    alerts = check_queue_alerts()
    return {"total": len(full_queue), "load": len(load), "near_ceg": count, "alerts": alerts}

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
