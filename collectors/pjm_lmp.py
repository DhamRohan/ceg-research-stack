"""
PJM LMP Collector — Direct Data Miner 2 REST API
Hits api.pjm.com/api/v1/ directly with no third-party library.
Requires: PJM_SUBSCRIPTION_KEY env var (free — get from apiportal.pjm.com profile page)

Auth: Ocp-Apim-Subscription-Key header (Azure API Management subscription key)
"""
import requests
import pandas as pd
from datetime import datetime, timedelta, date
import io
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn
from config.secrets import _get

BASE_URL = "https://api.pjm.com/api/v1"
PAGE_SIZE = 10000  # max rows per request

# CEG nuclear pnode IDs in PJM
# Source: PJM Data Miner 2 pnode reference, verified via dataminer2.pjm.com
CEG_PNODES = {
    51291:  "Braidwood",
    51292:  "Braidwood",
    51341:  "Byron",
    51342:  "Byron",
    33092:  "Calvert Cliffs",
    33093:  "Calvert Cliffs",
    34508:  "Clinton",
    50641:  "Dresden",
    50642:  "Dresden",
    50651:  "LaSalle",
    50652:  "LaSalle",
    50521:  "Limerick",
    50522:  "Limerick",
    33138:  "Nine Mile Point",
    33139:  "Nine Mile Point",
    33268:  "Peach Bottom",
    33269:  "Peach Bottom",
    50761:  "Quad Cities",
    50762:  "Quad Cities",
    33143:  "Ginna",
    34998:  "Crane (TMI-1)",  # formerly Three Mile Island Unit 1
    # PJM hubs for market context
    51288:  "AEP-DAYTON HUB",
    51287:  "WESTERN HUB",
    51289:  "EASTERN HUB",
    51290:  "NI HUB",
}

# Hub pnode IDs for market-wide LMP context (always fetch these)
HUB_PNODES = {51287, 51288, 51289, 51290}


def _get_key() -> str | None:
    """Get PJM subscription key from secrets/env."""
    key = _get("PJM_SUBSCRIPTION_KEY")
    if not key:
        # Fallback: also check old name from prior version
        key = _get("PJM_API_KEY")
    return key or None


def _headers() -> dict:
    """Build request headers."""
    key = _get_key()
    h = {
        "Accept": "text/csv",
        "User-Agent": "CEG-Research-Stack/1.0",
    }
    if key:
        h["Ocp-Apim-Subscription-Key"] = key
    return h


def _fetch_feed(endpoint: str, params: dict, label: str = "") -> pd.DataFrame:
    """
    Paginate through a PJM Data Miner 2 feed and return combined DataFrame.
    Returns empty DataFrame on auth failure (no key) or any HTTP error.
    """
    key = _get_key()
    if not key:
        print(f"  WARNING: PJM_SUBSCRIPTION_KEY not set — skipping {label or endpoint}")
        print("  Get your free key at: https://apiportal.pjm.com → Profile → Subscription Keys")
        return pd.DataFrame()

    url = f"{BASE_URL}/{endpoint}"
    params = {**params, "download": "true", "rowCount": PAGE_SIZE, "startRow": 1}
    frames = []

    while True:
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=60)
        except requests.RequestException as e:
            print(f"  ERROR: {label} network error: {e}")
            break

        if resp.status_code == 401:
            print(f"  ERROR: {label} — 401 Unauthorized")
            print("  Your PJM_SUBSCRIPTION_KEY may be wrong or expired.")
            print("  Refresh it at: https://apiportal.pjm.com → Profile → Subscription Keys")
            break

        if resp.status_code == 429:
            print(f"  WARNING: {label} — rate limited (429). Skipping.")
            break

        if not resp.ok:
            print(f"  ERROR: {label} — HTTP {resp.status_code}: {resp.text[:200]}")
            break

        if not resp.content.strip():
            break

        try:
            df = pd.read_csv(io.StringIO(resp.text))
        except Exception as e:
            print(f"  ERROR parsing {label} CSV: {e}")
            break

        if df.empty:
            break

        frames.append(df)

        # Pagination: if we got a full page, fetch next
        if len(df) < PAGE_SIZE:
            break
        params["startRow"] += PAGE_SIZE

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_dayahead_lmp(target_date: date | None = None) -> pd.DataFrame:
    """Fetch day-ahead hourly LMPs for all CEG pnodes."""
    if target_date is None:
        target_date = date.today()

    dt_str = target_date.strftime("%Y-%m-%dT00:00:00")
    pnode_ids = list(CEG_PNODES.keys())

    all_frames = []
    # PJM API accepts one pnode_id per request — batch in groups of ~10
    batch_size = 10
    for i in range(0, len(pnode_ids), batch_size):
        batch = pnode_ids[i:i + batch_size]
        for pnode_id in batch:
            df = _fetch_feed(
                "da_hrl_lmps",
                {"datetime_beginning_ept": dt_str, "pnode_id": pnode_id},
                label=f"DA LMP pnode={pnode_id}"
            )
            if not df.empty:
                df["plant"] = CEG_PNODES[pnode_id]
                df["pnode_id"] = pnode_id
                all_frames.append(df)

    return pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()


def fetch_realtime_lmp(target_date: date | None = None) -> pd.DataFrame:
    """Fetch real-time 5-minute LMPs for all CEG pnodes."""
    if target_date is None:
        target_date = date.today()

    dt_str = target_date.strftime("%Y-%m-%dT00:00:00")
    pnode_ids = list(CEG_PNODES.keys())

    all_frames = []
    for pnode_id in pnode_ids:
        df = _fetch_feed(
            "rt_fivemin_hrl_lmps",
            {"datetime_beginning_ept": dt_str, "pnode_id": pnode_id},
            label=f"RT LMP pnode={pnode_id}"
        )
        if not df.empty:
            df["plant"] = CEG_PNODES[pnode_id]
            df["pnode_id"] = pnode_id
            all_frames.append(df)

    return pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()


def _normalize_and_save(df: pd.DataFrame, market: str) -> int:
    """Normalize column names from PJM CSV format and save to DB."""
    if df.empty:
        return 0

    conn = get_conn()
    count = 0

    # PJM column name mapping (Data Miner 2 CSV headers)
    col_map = {
        "datetime_beginning_ept": "datetime",
        "datetime_beginning_utc": "datetime",
        "pnode_name": "pnode_name",
        "pnode_id": "pnode_id",
        "voltage": "voltage",
        "equipment": "equipment",
        "type": "type",
        "system_energy_price_da": "lmp_energy",
        "system_energy_price_rt": "lmp_energy",
        "total_lmp_da": "lmp_total",
        "total_lmp_rt": "lmp_total",
        "congestion_price_da": "lmp_congestion",
        "congestion_price_rt": "lmp_congestion",
        "marginal_loss_price_da": "lmp_loss",
        "marginal_loss_price_rt": "lmp_loss",
    }

    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # Ensure required columns exist
    if "datetime" not in df.columns:
        print(f"  WARNING: no datetime column in {market} data. Cols: {list(df.columns)}")
        return 0

    if "pnode_name" not in df.columns and "plant" in df.columns:
        df["pnode_name"] = df["plant"]

    for _, row in df.iterrows():
        try:
            conn.execute(
                """INSERT OR REPLACE INTO pjm_lmp
                   (datetime, market, pnode_name, lmp_total, lmp_energy, lmp_congestion, lmp_loss)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(row.get("datetime", "")),
                    market,
                    str(row.get("pnode_name", row.get("plant", ""))),
                    row.get("lmp_total"),
                    row.get("lmp_energy"),
                    row.get("lmp_congestion"),
                    row.get("lmp_loss"),
                )
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
               ROUND(MAX(lmp_total), 2) as max_lmp,
               ROUND(MIN(lmp_total), 2) as min_lmp,
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
    print(f"[{datetime.now()}] Fetching PJM LMP data via Data Miner 2 API...")

    if not _get_key():
        print("  SKIP: PJM_SUBSCRIPTION_KEY not configured.")
        print("  Get your free key: apiportal.pjm.com → sign in → Profile → show Subscription Key")
        return {"da_records": 0, "rt_records": 0, "skipped": True}

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Day-ahead (yesterday's published DA prices are most reliable)
    print(f"  Fetching day-ahead LMPs for {yesterday}...")
    da = fetch_dayahead_lmp(yesterday)
    da_count = _normalize_and_save(da, "DAY_AHEAD")
    print(f"  Day-ahead: {da_count} records saved, "
          f"{da['plant'].nunique() if not da.empty and 'plant' in da.columns else 0} plants")

    # Real-time (today, best-effort — may be partial)
    print(f"  Fetching real-time LMPs for {today}...")
    rt = fetch_realtime_lmp(today)
    rt_count = _normalize_and_save(rt, "REAL_TIME")
    print(f"  Real-time: {rt_count} records saved")

    return {"da_records": da_count, "rt_records": rt_count, "skipped": False}


if __name__ == "__main__":
    from config.database import init_db
    init_db()
    result = run()
    print(result)
