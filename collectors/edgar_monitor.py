"""
SEC EDGAR Collector — RSS feeds, EFTS full-text search, Form 4 insider trades, 13F holdings.
"""
import pandas as pd
import requests
import feedparser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn
from config.secrets import EDGAR_USER_AGENT

HEADERS = {"User-Agent": EDGAR_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
CEG_CIK = "0001868275"
CEG_CIK_GEN = "0001168165"
CEG_CUSIP = "21037T109"

# --- RSS Feed Monitoring ---

def fetch_edgar_rss(form_type: str = "") -> pd.DataFrame:
    """Fetch latest CEG filings from EDGAR RSS Atom feed."""
    url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={CEG_CIK}&type={form_type}&dateb=&owner=include&count=40&output=atom"
    )
    try:
        feed = feedparser.parse(url)
        records = []
        for entry in feed.entries:
            records.append({
                "accession_no": entry.get("id", "").split("accession-number=")[-1] if "accession-number=" in entry.get("id", "") else entry.get("id", ""),
                "form_type": entry.get("category", {}).get("term", "") if isinstance(entry.get("category"), dict) else form_type,
                "file_date": entry.get("updated", "")[:10],
                "description": entry.get("title", ""),
                "url": entry.get("link", "")
            })
        return pd.DataFrame(records)
    except Exception as e:
        print(f"  EDGAR RSS error: {e}")
        return pd.DataFrame()

def fetch_all_recent_filings() -> pd.DataFrame:
    """Fetch all recent CEG filings (any type)."""
    return fetch_edgar_rss("")

def fetch_8k_filings() -> pd.DataFrame:
    return fetch_edgar_rss("8-K")

def fetch_form4_filings() -> pd.DataFrame:
    return fetch_edgar_rss("4")

# --- EFTS Full-Text Search ---

def search_efts(query: str, forms: str = "", start_date: str = None, end_date: str = None) -> list:
    """Search EDGAR EFTS for keywords in CEG filings."""
    if not start_date:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    params = {
        "q": query,
        "entity": CEG_CIK,
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
    }
    if forms:
        params["forms"] = forms
    
    try:
        resp = requests.get("https://efts.sec.gov/LATEST/search-index",
                           params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("hits", {}).get("hits", [])
    except Exception as e:
        print(f"  EFTS search error: {e}")
        return []

# --- Form 4 Insider Transaction Parser ---

def get_form4_index() -> pd.DataFrame:
    """Get list of recent Form 4 filings for CEG."""
    url = f"https://data.sec.gov/submissions/CIK{CEG_CIK}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        
        records = []
        for i in range(len(forms)):
            if forms[i] in ("4", "4/A"):
                records.append({
                    "form_type": forms[i],
                    "filing_date": dates[i],
                    "accession_no": accessions[i],
                    "primary_doc": docs[i]
                })
        return pd.DataFrame(records)
    except Exception as e:
        print(f"  Form 4 index error: {e}")
        return pd.DataFrame()

def parse_form4_xml(accession_no: str, primary_doc: str) -> list:
    """Parse a Form 4 XML to extract transactions."""
    acc_nodash = accession_no.replace("-", "")
    xml_url = f"https://www.sec.gov/Archives/edgar/data/{int(CEG_CIK)}/{acc_nodash}/{primary_doc}"
    
    try:
        resp = requests.get(xml_url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
    except Exception:
        return []
    
    issuer = root.find("issuer")
    owner = root.find("reportingOwner")
    owner_name = ""
    owner_title = ""
    if owner:
        oid = owner.find("reportingOwnerId")
        if oid is not None:
            owner_name = oid.findtext("rptOwnerName", default="")
        rel = owner.find("reportingOwnerRelationship")
        if rel is not None:
            owner_title = rel.findtext("officerTitle", default="")
            if not owner_title and rel.findtext("isDirector", default="0") == "1":
                owner_title = "Director"
    
    transactions = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        txn_date = txn.findtext("transactionDate/value", default="")
        txn_code = txn.findtext("transactionCoding/transactionCode", default="")
        shares = txn.findtext("transactionAmounts/transactionShares/value", default="")
        price = txn.findtext("transactionAmounts/transactionPricePerShare/value", default="")
        direction = txn.findtext("transactionAmounts/transactionAcquiredDisposedCode/value", default="")
        shares_after = txn.findtext("postTransactionAmounts/sharesOwnedFollowingTransaction/value", default="")
        sec_title = txn.findtext("securityTitle/value", default="")
        
        sh = float(shares) if shares else None
        pr = float(price) if price else None
        
        transactions.append({
            "accession_no": accession_no,
            "owner_name": owner_name,
            "owner_title": owner_title,
            "transaction_date": txn_date,
            "transaction_code": txn_code,
            "direction": direction,
            "shares": sh,
            "price_per_share": pr,
            "value": (sh * pr) if sh and pr else None,
            "shares_after": float(shares_after) if shares_after else None,
            "security_title": sec_title,
        })
    return transactions

def fetch_insider_transactions(max_filings: int = 30) -> pd.DataFrame:
    """Pull and parse recent CEG Form 4 transactions."""
    index = get_form4_index()
    if index.empty:
        return pd.DataFrame()
    
    index = index.head(max_filings)
    all_txns = []
    for _, row in index.iterrows():
        txns = parse_form4_xml(row["accession_no"], row["primary_doc"])
        all_txns.extend(txns)
        time.sleep(0.15)  # Stay under 10 req/sec
    
    df = pd.DataFrame(all_txns)
    if not df.empty:
        df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    return df

# --- Save Functions ---

def save_filings_to_db(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    conn = get_conn()
    count = 0
    for _, row in df.iterrows():
        try:
            conn.execute(
                """INSERT OR IGNORE INTO edgar_filings 
                   (accession_no, form_type, file_date, description, url)
                   VALUES (?, ?, ?, ?, ?)""",
                (row.get("accession_no", ""), row.get("form_type", ""),
                 row.get("file_date", ""), row.get("description", ""), row.get("url", ""))
            )
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count

def save_insider_trades_to_db(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    conn = get_conn()
    count = 0
    for _, row in df.iterrows():
        try:
            conn.execute(
                """INSERT OR IGNORE INTO insider_trades
                   (accession_no, owner_name, owner_title, transaction_date,
                    transaction_code, direction, shares, price_per_share, value, shares_after, security_title)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row.get("accession_no"), row.get("owner_name"), row.get("owner_title"),
                 str(row.get("transaction_date", ""))[:10], row.get("transaction_code"),
                 row.get("direction"), row.get("shares"), row.get("price_per_share"),
                 row.get("value"), row.get("shares_after"), row.get("security_title"))
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
        SELECT * FROM edgar_filings
        WHERE file_date >= date('now', '-{days} days')
        ORDER BY file_date DESC
    """, conn)
    conn.close()
    return df

def get_insider_trades(days: int = 180) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(f"""
        SELECT * FROM insider_trades
        WHERE transaction_date >= date('now', '-{days} days')
        ORDER BY transaction_date DESC
    """, conn)
    conn.close()
    return df

def check_8k_alerts() -> list:
    """Check for new 8-K filings in last 24 hours."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM edgar_filings
        WHERE form_type LIKE '8-K%' AND file_date >= date('now', '-1 day')
    """, conn)
    conn.close()
    alerts = []
    for _, row in df.iterrows():
        alerts.append({
            "severity": "high",
            "category": "financial",
            "title": f"New CEG 8-K Filing: {row['description'][:80]}",
            "body": f"Filed {row['file_date']}: {row['description']}\n{row.get('url', '')}"
        })
    return alerts

def check_insider_alerts() -> list:
    """Check for significant insider trades."""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM insider_trades
        WHERE transaction_date >= date('now', '-7 days')
          AND transaction_code IN ('P', 'S')
          AND value IS NOT NULL
    """, conn)
    conn.close()
    alerts = []
    for _, row in df.iterrows():
        if row["transaction_code"] == "P" and (row["value"] or 0) > 50000:
            alerts.append({
                "severity": "medium",
                "category": "financial",
                "title": f"Insider BUY: {row['owner_name']} ({row['owner_title']})",
                "body": f"Purchased {row['shares']:.0f} shares at ${row['price_per_share']:.2f} (${row['value']:,.0f})"
            })
        elif row["transaction_code"] == "S" and (row["value"] or 0) > 500000:
            alerts.append({
                "severity": "medium",
                "category": "financial",
                "title": f"Insider SALE: {row['owner_name']} ({row['owner_title']})",
                "body": f"Sold {row['shares']:.0f} shares at ${row['price_per_share']:.2f} (${row['value']:,.0f})"
            })
    return alerts

def run():
    print(f"[{datetime.now()}] Fetching EDGAR data...")
    
    # All filings RSS
    filings = fetch_all_recent_filings()
    f_count = save_filings_to_db(filings)
    print(f"  Filings: {f_count} saved")
    
    # 8-K specifically
    eights = fetch_8k_filings()
    e_count = save_filings_to_db(eights)
    print(f"  8-K filings: {e_count} saved")
    
    # Insider trades
    insiders = fetch_insider_transactions(max_filings=20)
    i_count = save_insider_trades_to_db(insiders)
    print(f"  Insider transactions: {i_count} saved")
    
    alerts = check_8k_alerts() + check_insider_alerts()
    return {"filings": f_count, "insiders": i_count, "alerts": alerts}

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
