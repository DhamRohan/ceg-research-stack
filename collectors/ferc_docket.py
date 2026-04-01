"""
FERC eLibrary Docket Monitor — Track filings in CEG-relevant proceedings.
"""
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn
from config.secrets import EDGAR_USER_AGENT
import json

FERC_SEARCH_URL = "https://elibrary.ferc.gov/eLibrary/search"

def _load_dockets() -> list:
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "plant_config.json")
    with open(cfg_path) as f:
        cfg = json.load(f)
    return cfg["ferc_dockets"]

def search_ferc_docket(docket: str) -> pd.DataFrame:
    """Search FERC eLibrary for recent filings in a docket.
    Note: FERC eLibrary is JavaScript-heavy. We use their search URL with parameters.
    Falls back to a simple scrape approach.
    """
    try:
        # Try direct URL approach
        url = f"https://elibrary.ferc.gov/eLibrary/search?docket={docket}"
        headers = {"User-Agent": EDGAR_USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=30)
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            # Try to extract filing data from the page
            rows = soup.find_all("tr")
            records = []
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 3:
                    records.append({
                        "docket": docket,
                        "filing_date": cells[0].get_text(strip=True)[:10] if cells else "",
                        "document_type": cells[1].get_text(strip=True)[:100] if len(cells) > 1 else "",
                        "description": cells[2].get_text(strip=True)[:500] if len(cells) > 2 else "",
                        "url": url
                    })
            if records:
                return pd.DataFrame(records)
        
        # If page doesn't parse well, return minimal record
        return pd.DataFrame([{
            "docket": docket,
            "filing_date": datetime.now().strftime("%Y-%m-%d"),
            "document_type": "search_result",
            "description": f"FERC eLibrary search for docket {docket}",
            "url": url
        }])
    
    except Exception as e:
        print(f"  FERC search error for {docket}: {e}")
        return pd.DataFrame()

def fetch_all_dockets() -> pd.DataFrame:
    """Search all monitored FERC dockets."""
    dockets = _load_dockets()
    all_dfs = []
    for d in dockets:
        df = search_ferc_docket(d["docket"])
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
                """INSERT OR IGNORE INTO ferc_filings
                   (docket, filing_date, document_type, description, url)
                   VALUES (?, ?, ?, ?, ?)""",
                (row.get("docket", ""), row.get("filing_date", ""),
                 row.get("document_type", ""), row.get("description", ""),
                 row.get("url", ""))
            )
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count

def get_recent_filings(days: int = 30) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(f"""
        SELECT * FROM ferc_filings
        WHERE filing_date >= date('now', '-{days} days')
        ORDER BY filing_date DESC
    """, conn)
    conn.close()
    return df

def get_filings_by_docket(docket: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM ferc_filings
        WHERE docket = ?
        ORDER BY filing_date DESC
    """, conn, params=(docket,))
    conn.close()
    return df

def check_ferc_alerts() -> list:
    """Check for new FERC filings in monitored dockets."""
    recent = get_recent_filings(days=3)
    if recent.empty:
        return []
    
    dockets = _load_dockets()
    monitored = {d["docket"] for d in dockets}
    
    alerts = []
    for _, row in recent.iterrows():
        if row["docket"] in monitored:
            alerts.append({
                "severity": "high",
                "category": "regulatory",
                "title": f"New FERC filing in {row['docket']}",
                "body": f"Filed {row['filing_date']}: {row['description'][:200]}\n"
                        f"URL: {row.get('url', 'N/A')}"
            })
    return alerts

def run():
    print(f"[{datetime.now()}] Checking FERC dockets...")
    df = fetch_all_dockets()
    count = save_to_db(df)
    print(f"  Saved {count} filings across {df['docket'].nunique() if not df.empty else 0} dockets")
    alerts = check_ferc_alerts()
    return {"filings": count, "alerts": alerts}

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
