"""
EIA Open Data API Collector — Monthly nuclear generation by CEG plant.
"""
import pandas as pd
import requests
from datetime import datetime
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn
from config.secrets import EIA_API_KEY

EIA_BASE = "https://api.eia.gov/v2/electricity/facility-fuel/data"

CEG_PLANT_IDS = {
    880: "Braidwood", 1002: "Byron", 1570: "Calvert Cliffs",
    4110: "Clinton", 3: "Dresden", 6: "LaSalle", 3180: "Limerick",
    2316: "Nine Mile Point", 3179: "Peach Bottom", 869: "Quad Cities",
    7: "Ginna", 2: "Crane (TMI-1)"
}

# Approximate nameplate MW for capacity factor calc
NAMEPLATE_MW = {
    880: 2332, 1002: 2300, 1570: 1745, 4110: 1079, 3: 2000,
    6: 2340, 3180: 2260, 2316: 1890, 3179: 2860, 869: 2000,
    7: 614, 2: 835
}

def fetch_eia_generation(start_period: str = None, end_period: str = None) -> pd.DataFrame:
    """Fetch monthly nuclear generation for CEG plants from EIA API."""
    if not EIA_API_KEY:
        print("  WARNING: No EIA API key configured")
        return pd.DataFrame()
    
    if not start_period:
        start_period = "2023-01"
    if not end_period:
        end_period = datetime.now().strftime("%Y-%m")
    
    params = {
        "api_key": EIA_API_KEY,
        "frequency": "monthly",
        "data[0]": "generation",
        "data[1]": "gross-generation",
        "facets[fuel2002][]": "NUC",
        "start": start_period,
        "end": end_period,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "offset": 0,
        "length": 5000
    }
    
    resp = requests.get(EIA_BASE, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    
    records = data.get("response", {}).get("data", [])
    if not records:
        return pd.DataFrame()
    
    df = pd.DataFrame(records)
    # Filter to CEG plants
    df["plantCode"] = pd.to_numeric(df.get("plantCode", pd.Series()), errors="coerce")
    df = df[df["plantCode"].isin(CEG_PLANT_IDS.keys())].copy()
    
    if df.empty:
        return df
    
    df["plant_name"] = df["plantCode"].map(CEG_PLANT_IDS)
    df["generation_mwh"] = pd.to_numeric(df.get("generation", pd.Series()), errors="coerce")
    
    # Compute capacity factor: CF = generation / (nameplate * hours_in_month)
    df["nameplate_mw"] = df["plantCode"].map(NAMEPLATE_MW)
    df["hours"] = pd.to_datetime(df["period"] + "-01").dt.days_in_month * 24
    df["capacity_factor"] = (df["generation_mwh"] / (df["nameplate_mw"] * df["hours"]) * 100).round(2)
    
    return df[["period", "plantCode", "plant_name", "generation_mwh", "capacity_factor"]].rename(
        columns={"plantCode": "plant_id"}
    )

def save_to_db(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    conn = get_conn()
    count = 0
    for _, row in df.iterrows():
        try:
            conn.execute(
                """INSERT OR REPLACE INTO eia_generation 
                   (period, plant_id, plant_name, fuel, generation_mwh, capacity_factor)
                   VALUES (?, ?, ?, 'NUC', ?, ?)""",
                (row["period"], row["plant_id"], row["plant_name"],
                 row["generation_mwh"], row["capacity_factor"])
            )
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count

def get_latest_generation() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM eia_generation
        WHERE period = (SELECT MAX(period) FROM eia_generation)
        ORDER BY plant_name
    """, conn)
    conn.close()
    return df

def get_plant_history(plant_id: int, months: int = 24) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT period, generation_mwh, capacity_factor
        FROM eia_generation
        WHERE plant_id = ?
        ORDER BY period DESC LIMIT ?
    """, conn, params=(plant_id, months))
    conn.close()
    return df.sort_values("period")

def run():
    print(f"[{datetime.now()}] Fetching EIA nuclear generation data...")
    df = fetch_eia_generation()
    count = save_to_db(df)
    print(f"  Saved {count} records covering {df['plant_name'].nunique() if not df.empty else 0} plants")
    return {"records": count}

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
