"""
NASA FIRMS Collector — Near-real-time VIIRS thermal anomalies within 2km of CEG plants.
"""
import pandas as pd
import requests
from math import radians, cos, sin, asin, sqrt
from datetime import datetime
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn
from config.secrets import FIRMS_MAP_KEY

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# Load plant coordinates
def _load_plants() -> dict:
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "plant_config.json")
    with open(cfg_path) as f:
        cfg = json.load(f)
    return cfg["plants"]

def haversine(lat1, lon1, lat2, lon2) -> float:
    """Distance in km between two points."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 2 * 6371 * asin(sqrt(a))

def fetch_firms_for_plant(plant_key: str, plant_data: dict, days: int = 2) -> pd.DataFrame:
    """Fetch VIIRS NRT data for a 4km buffer around a plant."""
    if not FIRMS_MAP_KEY:
        return pd.DataFrame()
    
    lat, lon = plant_data["lat"], plant_data["lon"]
    buffer = 0.04  # ~4km
    bbox = f"{lon-buffer},{lat-buffer},{lon+buffer},{lat+buffer}"
    
    url = f"{FIRMS_BASE}/{FIRMS_MAP_KEY}/VIIRS_SNPP_NRT/{bbox}/{days}"
    
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200 and resp.text.strip():
            from io import StringIO
            df = pd.read_csv(StringIO(resp.text))
            if not df.empty:
                df["nearest_plant"] = plant_data["name"]
                df["plant_lat"] = lat
                df["plant_lon"] = lon
                # Compute distance to plant
                if "latitude" in df.columns and "longitude" in df.columns:
                    df["distance_km"] = df.apply(
                        lambda r: haversine(r["latitude"], r["longitude"], lat, lon), axis=1
                    )
                    df = df[df["distance_km"] <= 2.0]  # Only within 2km
            return df
        return pd.DataFrame()
    except Exception as e:
        print(f"  FIRMS error for {plant_key}: {e}")
        return pd.DataFrame()

def fetch_all_plants(days: int = 2) -> pd.DataFrame:
    """Fetch FIRMS data for all CEG plants."""
    plants = _load_plants()
    all_dfs = []
    for key, data in plants.items():
        df = fetch_firms_for_plant(key, data, days)
        if not df.empty:
            all_dfs.append(df)
    
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
                """INSERT INTO firms_thermal
                   (acq_date, acq_time, latitude, longitude, bright_ti4,
                    confidence, frp, nearest_plant, distance_km)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row.get("acq_date", ""), str(row.get("acq_time", "")),
                 row.get("latitude"), row.get("longitude"),
                 row.get("bright_ti4"), row.get("confidence", ""),
                 row.get("frp"), row.get("nearest_plant", ""),
                 row.get("distance_km"))
            )
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count

def get_recent_thermal(days: int = 7) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(f"""
        SELECT * FROM firms_thermal
        WHERE acq_date >= date('now', '-{days} days')
        ORDER BY acq_date DESC, acq_time DESC
    """, conn)
    conn.close()
    return df

def check_thermal_alerts() -> list:
    """Check for non-fire thermal anomalies near plants."""
    recent = get_recent_thermal(days=2)
    if recent.empty:
        return []
    
    alerts = []
    for plant in recent["nearest_plant"].unique():
        plant_df = recent[recent["nearest_plant"] == plant]
        if len(plant_df) > 0:
            alerts.append({
                "severity": "low",
                "category": "physical",
                "title": f"Thermal anomaly near {plant}",
                "body": f"{len(plant_df)} VIIRS detection(s) within 2km. "
                        f"Avg brightness: {plant_df['bright_ti4'].mean():.1f}K. "
                        f"Check for industrial activity."
            })
    return alerts

def run():
    print(f"[{datetime.now()}] Fetching NASA FIRMS thermal data...")
    df = fetch_all_plants(days=2)
    count = save_to_db(df)
    print(f"  Saved {count} thermal detections near {df['nearest_plant'].nunique() if not df.empty else 0} plants")
    alerts = check_thermal_alerts()
    return {"detections": count, "alerts": alerts}

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
