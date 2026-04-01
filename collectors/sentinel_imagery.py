"""
Copernicus Sentinel-2 Collector — Change detection at CEG plant sites.
Uses Sentinel Hub APIs via the Copernicus Data Space Ecosystem.
"""
import numpy as np
from datetime import datetime, timedelta
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn
from config.secrets import COPERNICUS_CLIENT_ID, COPERNICUS_CLIENT_SECRET

def _load_plants() -> dict:
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "plant_config.json")
    with open(cfg_path) as f:
        return json.load(f)["plants"]

def _get_sh_config():
    """Configure Sentinel Hub with CDSE credentials."""
    try:
        from sentinelhub import SHConfig
        config = SHConfig()
        config.sh_client_id = COPERNICUS_CLIENT_ID
        config.sh_client_secret = COPERNICUS_CLIENT_SECRET
        config.sh_token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
        config.sh_base_url = "https://sh.dataspace.copernicus.eu"
        return config
    except ImportError:
        print("  WARNING: sentinelhub not installed")
        return None

def fetch_ndvi_for_plant(plant_key: str, plant_data: dict, 
                          target_date: str = None, buffer_km: float = 2.0) -> dict:
    """Fetch NDVI statistics for a 2km buffer around a plant."""
    try:
        from sentinelhub import (SentinelHubRequest, SentinelHubStatistical,
                                  DataCollection, MimeType, BBox, CRS, Geometry)
    except ImportError:
        return {"plant": plant_data["name"], "ndvi_mean": None, "error": "sentinelhub not installed"}
    
    config = _get_sh_config()
    if config is None:
        return {"plant": plant_data["name"], "ndvi_mean": None, "error": "No config"}
    
    lat, lon = plant_data["lat"], plant_data["lon"]
    delta_lat = buffer_km / 111.0
    delta_lon = buffer_km / (111.0 * abs(np.cos(np.radians(lat))))
    
    bbox = BBox(
        bbox=[lon - delta_lon, lat - delta_lat, lon + delta_lon, lat + delta_lat],
        crs=CRS.WGS84
    )
    
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")
    
    end_date = target_date
    start_date = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")
    
    # NDVI evalscript
    evalscript = """
    //VERSION=3
    function setup() {
        return {
            input: [{bands: ["B04", "B08", "SCL"], units: "DN"}],
            output: [{id: "ndvi", bands: 1, sampleType: "FLOAT32"}]
        };
    }
    function evaluatePixel(sample) {
        // Mask clouds (SCL: 3=cloud shadow, 8=cloud medium, 9=cloud high, 10=thin cirrus)
        if ([3, 8, 9, 10].includes(sample.SCL)) {
            return {ndvi: [-9999]};
        }
        let ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04 + 0.0001);
        return {ndvi: [ndvi]};
    }
    """
    
    try:
        request = SentinelHubRequest(
            evalscript=evalscript,
            input_data=[
                SentinelHubRequest.input_data(
                    data_collection=DataCollection.SENTINEL2_L2A,
                    time_interval=(start_date, end_date),
                    other_args={"processing": {"upsampling": "BILINEAR"}}
                )
            ],
            responses=[SentinelHubRequest.output_response("ndvi", MimeType.TIFF)],
            bbox=bbox,
            size=[256, 256],
            config=config
        )
        data = request.get_data()[0]
        
        # Compute NDVI stats (excluding masked pixels)
        valid = data[data > -9000]
        if len(valid) == 0:
            return {"plant": plant_data["name"], "ndvi_mean": None, "error": "All pixels cloudy"}
        
        return {
            "plant": plant_data["name"],
            "ndvi_mean": float(np.mean(valid)),
            "ndvi_std": float(np.std(valid)),
            "ndvi_min": float(np.min(valid)),
            "valid_pixels": len(valid),
            "total_pixels": data.size,
            "date": end_date
        }
    except Exception as e:
        return {"plant": plant_data["name"], "ndvi_mean": None, "error": str(e)}

def fetch_rgb_thumbnail(plant_key: str, plant_data: dict, 
                         target_date: str = None) -> bytes:
    """Fetch RGB thumbnail for a plant (for dashboard display)."""
    try:
        from sentinelhub import SentinelHubRequest, DataCollection, MimeType, BBox, CRS
    except ImportError:
        return b""
    
    config = _get_sh_config()
    if config is None:
        return b""
    
    lat, lon = plant_data["lat"], plant_data["lon"]
    buffer_km = 2.0
    delta_lat = buffer_km / 111.0
    delta_lon = buffer_km / (111.0 * abs(np.cos(np.radians(lat))))
    
    bbox = BBox(
        bbox=[lon - delta_lon, lat - delta_lat, lon + delta_lon, lat + delta_lat],
        crs=CRS.WGS84
    )
    
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=15)).strftime("%Y-%m-%d")
    
    evalscript_rgb = """
    //VERSION=3
    function setup() {
        return {input: [{bands: ["B04", "B03", "B02"]}], output: {bands: 3}};
    }
    function evaluatePixel(s) {
        return [3.5*s.B04, 3.5*s.B03, 3.5*s.B02];
    }
    """
    
    try:
        request = SentinelHubRequest(
            evalscript=evalscript_rgb,
            input_data=[
                SentinelHubRequest.input_data(
                    data_collection=DataCollection.SENTINEL2_L2A,
                    time_interval=(start_date, target_date),
                    mosaicking_order="leastCC"
                )
            ],
            responses=[SentinelHubRequest.output_response("default", MimeType.PNG)],
            bbox=bbox,
            size=[512, 512],
            config=config
        )
        return request.get_data()[0]
    except Exception as e:
        print(f"  RGB thumbnail error for {plant_key}: {e}")
        return b""

def compute_ndvi_change(plant_key: str, plant_data: dict) -> dict:
    """Compute NDVI change vs 3-month baseline."""
    now = datetime.now()
    current = fetch_ndvi_for_plant(plant_key, plant_data, now.strftime("%Y-%m-%d"))
    baseline = fetch_ndvi_for_plant(
        plant_key, plant_data,
        (now - timedelta(days=90)).strftime("%Y-%m-%d")
    )
    
    if current.get("ndvi_mean") is not None and baseline.get("ndvi_mean") is not None:
        change = current["ndvi_mean"] - baseline["ndvi_mean"]
        return {
            "plant": plant_data["name"],
            "current_ndvi": current["ndvi_mean"],
            "baseline_ndvi": baseline["ndvi_mean"],
            "ndvi_change": change,
            "alert": abs(change) > 0.15,
            "date": now.strftime("%Y-%m-%d")
        }
    return {"plant": plant_data["name"], "ndvi_change": None, "error": "Insufficient data"}

def save_to_db(results: list) -> int:
    conn = get_conn()
    count = 0
    for r in results:
        if r.get("ndvi_change") is not None:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO satellite_changes
                       (date, plant, ndvi_mean, ndvi_change, alert_triggered)
                       VALUES (?, ?, ?, ?, ?)""",
                    (r.get("date", datetime.now().strftime("%Y-%m-%d")),
                     r["plant"], r.get("current_ndvi"),
                     r["ndvi_change"], 1 if r.get("alert") else 0)
                )
                count += 1
            except Exception:
                pass
    conn.commit()
    conn.close()
    return count

def get_recent_changes() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM satellite_changes
        WHERE date >= date('now', '-30 days')
        ORDER BY date DESC
    """, conn)
    conn.close()
    return df

def check_satellite_alerts() -> list:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM satellite_changes
        WHERE alert_triggered = 1 AND date >= date('now', '-7 days')
    """, conn)
    conn.close()
    
    alerts = []
    for _, row in df.iterrows():
        alerts.append({
            "severity": "low",
            "category": "physical",
            "title": f"NDVI change detected at {row['plant']}",
            "body": f"NDVI change: {row['ndvi_change']:.3f} (threshold: ±0.15). "
                    f"Possible construction or land use change."
        })
    return alerts

def run():
    print(f"[{datetime.now()}] Fetching Sentinel-2 NDVI data...")
    plants = _load_plants()
    results = []
    for key, data in plants.items():
        print(f"  Processing {data['name']}...")
        result = compute_ndvi_change(key, data)
        results.append(result)
    
    count = save_to_db(results)
    print(f"  Saved {count} change detection results")
    alerts = check_satellite_alerts()
    return {"plants_processed": len(results), "saved": count, "alerts": alerts}

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
