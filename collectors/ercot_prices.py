"""
ERCOT Price Collector — DAM and RT LMPs for post-Calpine Texas fleet.
Uses ERCOT Public API with OAuth2 authentication.
"""
import pandas as pd
import requests
from datetime import datetime, date, timedelta
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn
from config.secrets import ERCOT_SUBSCRIPTION_KEY, ERCOT_USERNAME, ERCOT_PASSWORD

ERCOT_AUTH_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
ERCOT_API_BASE = "https://api.ercot.com/api/public-reports"

# Calpine/CEG settlement point names to monitor
ERCOT_SETTLEMENT_POINTS = [
    "LZ_NORTH", "LZ_HOUSTON", "LZ_SOUTH", "LZ_WEST",
    "HB_NORTH", "HB_HOUSTON", "HB_SOUTH", "HB_WEST",
]

def _get_ercot_token() -> str:
    """Get ERCOT OAuth2 access token via ROPC flow."""
    if not ERCOT_USERNAME or not ERCOT_PASSWORD:
        print("  WARNING: ERCOT credentials not configured")
        return ""
    
    data = {
        "username": ERCOT_USERNAME,
        "password": ERCOT_PASSWORD,
        "grant_type": "password",
        "scope": f"openid fec253ea-0d06-4272-a5e6-b478baeecd70 offline_access",
        "client_id": "fec253ea-0d06-4272-a5e6-b478baeecd70",
        "response_type": "id_token"
    }
    try:
        resp = requests.post(ERCOT_AUTH_URL, data=data, timeout=30)
        resp.raise_for_status()
        return resp.json().get("access_token", "")
    except Exception as e:
        print(f"  ERCOT auth error: {e}")
        return ""

def fetch_ercot_dam_lmp(target_date: str = None) -> pd.DataFrame:
    """Fetch Day-Ahead Market hourly LMPs from ERCOT."""
    token = _get_ercot_token()
    if not token:
        return pd.DataFrame()
    
    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Ocp-Apim-Subscription-Key": ERCOT_SUBSCRIPTION_KEY
    }
    
    url = f"{ERCOT_API_BASE}/np4-183-cd/dam_hourly_lmp"
    params = {
        "deliveryDateFrom": target_date,
        "deliveryDateTo": target_date,
        "size": 5000
    }
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        records = data.get("data", [])
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        return df
    except Exception as e:
        print(f"  ERCOT DAM fetch error: {e}")
        return pd.DataFrame()

def fetch_ercot_spp(target_date: str = None) -> pd.DataFrame:
    """Fetch Settlement Point Prices from ERCOT."""
    token = _get_ercot_token()
    if not token:
        return pd.DataFrame()
    
    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Ocp-Apim-Subscription-Key": ERCOT_SUBSCRIPTION_KEY
    }
    
    url = f"{ERCOT_API_BASE}/np6-905-cd/spp_node_zone_hub"
    params = {
        "deliveryDateFrom": target_date,
        "deliveryDateTo": target_date,
        "size": 5000
    }
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        records = data.get("data", [])
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        # Filter to relevant settlement points
        if "settlementPoint" in df.columns:
            df = df[df["settlementPoint"].isin(ERCOT_SETTLEMENT_POINTS)]
        return df
    except Exception as e:
        print(f"  ERCOT SPP fetch error: {e}")
        return pd.DataFrame()

def save_to_db(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    conn = get_conn()
    count = 0
    
    sp_col = None
    for c in ["settlementPoint", "settlement_point", "busName"]:
        if c in df.columns:
            sp_col = c
            break
    
    lmp_col = None
    for c in ["settlementPointPrice", "LMP", "lmp", "price"]:
        if c in df.columns:
            lmp_col = c
            break
    
    time_col = None
    for c in ["deliveryDate", "SCEDTimestamp", "delivery_date"]:
        if c in df.columns:
            time_col = c
            break
    
    if not sp_col or not lmp_col or not time_col:
        return 0
    
    for _, row in df.iterrows():
        try:
            hour = row.get("hourEnding", row.get("deliveryHour", ""))
            dt_str = f"{row[time_col]} H{hour}" if hour else str(row[time_col])
            conn.execute(
                """INSERT OR REPLACE INTO ercot_lmp (datetime, settlement_point, lmp)
                   VALUES (?, ?, ?)""",
                (dt_str, row[sp_col], float(row[lmp_col]) if row[lmp_col] else None)
            )
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count

def get_latest_ercot() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT settlement_point, ROUND(AVG(lmp), 2) as avg_lmp,
               ROUND(MAX(lmp), 2) as max_lmp, COUNT(*) as n_obs,
               MAX(datetime) as latest_time
        FROM ercot_lmp
        WHERE datetime >= date('now', '-2 days')
        GROUP BY settlement_point
        ORDER BY settlement_point
    """, conn)
    conn.close()
    return df

def run():
    print(f"[{datetime.now()}] Fetching ERCOT pricing data...")
    dam = fetch_ercot_dam_lmp()
    dam_count = save_to_db(dam)
    print(f"  DAM LMPs: {dam_count} records")
    
    spp = fetch_ercot_spp()
    spp_count = save_to_db(spp)
    print(f"  Settlement prices: {spp_count} records")
    
    return {"dam": dam_count, "spp": spp_count}

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
