"""
Composite Signal Scoring Engine
Scores each dimension -2 to +2, computes weighted composite.
"""
import pandas as pd
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

DIMENSION_WEIGHTS = {
    "nuclear_ops": 0.30,
    "power_markets": 0.25,
    "data_center_demand": 0.20,
    "regulatory": 0.10,
    "financial_insider": 0.10,
    "physical_validation": 0.05,
}

LABELS = {
    (1.0, 2.0): "Strong Bull",
    (0.5, 1.0): "Moderate Bull",
    (0.0, 0.5): "Neutral",
    (-0.5, 0.0): "Cautious",
    (-2.0, -0.5): "Bearish",
}

def score_nuclear_ops() -> dict:
    """Score nuclear operations dimension."""
    conn = get_conn()
    
    # Fleet capacity factor from last 30 days
    cf = pd.read_sql_query("""
        SELECT AVG(power_pct) as avg_cf FROM nrc_status
        WHERE date >= date('now', '-30 days')
    """, conn).iloc[0]["avg_cf"]
    
    # Check for any unit outage
    outages = pd.read_sql_query("""
        SELECT COUNT(*) as n FROM nrc_status
        WHERE date = (SELECT MAX(date) FROM nrc_status) AND power_pct < 10
    """, conn).iloc[0]["n"]
    
    conn.close()
    
    if cf is None:
        return {"dimension": "nuclear_ops", "score": 0, "raw_value": None, "notes": "No data"}
    
    if outages > 0:
        score = -2.0
        notes = f"Unplanned outage detected ({outages} units <10%)"
    elif cf > 92:
        score = 2.0
        notes = f"Fleet CF {cf:.1f}% — excellent"
    elif cf > 85:
        score = 1.0
        notes = f"Fleet CF {cf:.1f}% — good"
    elif cf > 80:
        score = 0.0
        notes = f"Fleet CF {cf:.1f}% — average"
    else:
        score = -1.0
        notes = f"Fleet CF {cf:.1f}% — below target"
    
    return {"dimension": "nuclear_ops", "score": score, "raw_value": cf, "notes": notes}

def score_power_markets() -> dict:
    """Score power markets dimension."""
    conn = get_conn()
    
    # Average LMP last 7 days
    lmp = pd.read_sql_query("""
        SELECT AVG(lmp_total) as avg_lmp FROM pjm_lmp
        WHERE datetime >= datetime('now', '-7 days')
    """, conn).iloc[0]["avg_lmp"]
    
    conn.close()
    
    # BRA at cap = +2 (hardcoded from latest data — $333.44/MW-day)
    bra_score = 2.0  # 2027/2028 cleared at cap
    
    if lmp is None:
        lmp_score = 0.0
    elif lmp > 80:
        lmp_score = 2.0
    elif lmp > 50:
        lmp_score = 1.0
    elif lmp > 30:
        lmp_score = 0.0
    else:
        lmp_score = -1.0
    
    score = (bra_score + lmp_score) / 2
    notes = f"BRA at cap (+2), LMP avg ${lmp:.1f}/MWh" if lmp else "BRA at cap (+2), no recent LMP data"
    
    return {"dimension": "power_markets", "score": round(score, 2), "raw_value": lmp, "notes": notes}

def score_data_center_demand() -> dict:
    """Score data center demand dimension."""
    conn = get_conn()
    
    # Count recent load entries in queue near CEG
    queue = pd.read_sql_query("""
        SELECT COUNT(*) as n, COALESCE(SUM(mw), 0) as total_mw FROM pjm_queue
        WHERE (fuel_type LIKE '%load%' OR fuel_type LIKE '%Load%')
          AND first_seen >= date('now', '-90 days')
    """, conn).iloc[0]
    
    # FERC co-location docket activity
    ferc = pd.read_sql_query("""
        SELECT COUNT(*) as n FROM ferc_filings
        WHERE docket IN ('EL24-49', 'EL25-20', 'EL25-49')
          AND filing_date >= date('now', '-30 days')
    """, conn).iloc[0]["n"]
    
    conn.close()
    
    total_mw = queue["total_mw"]
    n_entries = queue["n"]
    
    if total_mw > 500:
        score = 2.0
    elif total_mw > 200:
        score = 1.0
    elif n_entries > 0:
        score = 0.5
    else:
        score = 0.0
    
    # Bonus for active FERC proceedings
    if ferc > 0:
        score = min(score + 0.5, 2.0)
    
    notes = f"{n_entries} load entries ({total_mw:.0f} MW) near CEG, {ferc} FERC filings"
    return {"dimension": "data_center_demand", "score": round(score, 2), "raw_value": total_mw, "notes": notes}

def score_regulatory() -> dict:
    """Score regulatory dimension."""
    conn = get_conn()
    
    # Recent FERC filings
    ferc_count = pd.read_sql_query("""
        SELECT COUNT(*) as n FROM ferc_filings
        WHERE filing_date >= date('now', '-30 days')
    """, conn).iloc[0]["n"]
    
    conn.close()
    
    # Base positive: co-location order was favorable + SLR approvals
    score = 1.0  # Baseline positive regulatory environment
    notes = "Favorable co-location order (Dec 2025), SLR approvals proceeding"
    
    if ferc_count > 5:
        score += 0.5
        notes += f"; {ferc_count} recent FERC filings"
    
    return {"dimension": "regulatory", "score": min(round(score, 2), 2.0), "raw_value": ferc_count, "notes": notes}

def score_financial_insider() -> dict:
    """Score financial/insider dimension."""
    conn = get_conn()
    
    trades = pd.read_sql_query("""
        SELECT transaction_code, COALESCE(SUM(value), 0) as total_value
        FROM insider_trades
        WHERE transaction_date >= date('now', '-180 days')
          AND transaction_code IN ('P', 'S')
        GROUP BY transaction_code
    """, conn)
    
    conn.close()
    
    buys = trades[trades["transaction_code"] == "P"]["total_value"].sum() if not trades.empty else 0
    sells = trades[trades["transaction_code"] == "S"]["total_value"].sum() if not trades.empty else 0
    
    net = buys - sells
    if net > 100000:
        score = 1.0
        notes = f"Net insider buying: ${net:,.0f} (6mo)"
    elif net > 0:
        score = 0.5
        notes = f"Slight net buying: ${net:,.0f} (6mo)"
    elif net > -100000:
        score = 0.0
        notes = f"Neutral insider activity: ${net:,.0f} (6mo)"
    else:
        score = -1.0
        notes = f"Net insider selling: ${net:,.0f} (6mo)"
    
    return {"dimension": "financial_insider", "score": score, "raw_value": net, "notes": notes}

def score_physical_validation() -> dict:
    """Score physical world validation dimension."""
    conn = get_conn()
    
    changes = pd.read_sql_query("""
        SELECT COUNT(*) as n_alerts FROM satellite_changes
        WHERE alert_triggered = 1 AND date >= date('now', '-30 days')
    """, conn).iloc[0]["n_alerts"]
    
    thermal = pd.read_sql_query("""
        SELECT COUNT(*) as n FROM firms_thermal
        WHERE acq_date >= date('now', '-7 days')
    """, conn).iloc[0]["n"]
    
    conn.close()
    
    if changes > 0:
        score = 1.0
        notes = f"Construction activity detected ({changes} NDVI alerts)"
    elif thermal > 0:
        score = 0.5
        notes = f"Thermal activity ({thermal} detections)"
    else:
        score = 0.0
        notes = "No physical activity signals"
    
    return {"dimension": "physical_validation", "score": score, "raw_value": changes, "notes": notes}

def compute_composite() -> dict:
    """Compute full composite signal scorecard."""
    scores = [
        score_nuclear_ops(),
        score_power_markets(),
        score_data_center_demand(),
        score_regulatory(),
        score_financial_insider(),
        score_physical_validation(),
    ]
    
    composite = sum(
        s["score"] * DIMENSION_WEIGHTS.get(s["dimension"], 0)
        for s in scores
    )
    composite = round(composite, 3)
    
    # Label
    label = "Neutral"
    for (lo, hi), lbl in LABELS.items():
        if lo <= composite < hi:
            label = lbl
            break
    if composite >= 2.0:
        label = "Strong Bull"
    elif composite <= -2.0:
        label = "Bearish"
    
    # Convergence flag: 3+ dimensions with same sign and score >= 1.0
    strong_bull = sum(1 for s in scores if s["score"] >= 1.0)
    strong_bear = sum(1 for s in scores if s["score"] <= -1.0)
    convergence = "BULLISH CONVERGENCE" if strong_bull >= 3 else (
        "BEARISH CONVERGENCE" if strong_bear >= 3 else "No convergence"
    )
    
    return {
        "scores": scores,
        "composite": composite,
        "label": label,
        "convergence": convergence,
        "timestamp": datetime.now().isoformat()
    }

def save_scores(result: dict) -> int:
    conn = get_conn()
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    for s in result["scores"]:
        try:
            conn.execute(
                """INSERT OR REPLACE INTO signals
                   (date, dimension, signal_name, score, raw_value, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (today, s["dimension"], s["dimension"], s["score"],
                 s.get("raw_value"), s.get("notes", ""))
            )
            count += 1
        except Exception:
            pass
    # Save composite
    conn.execute(
        """INSERT OR REPLACE INTO signals
           (date, dimension, signal_name, score, raw_value, notes)
           VALUES (?, 'composite', 'composite', ?, NULL, ?)""",
        (today, result["composite"], f"{result['label']} | {result['convergence']}")
    )
    conn.commit()
    conn.close()
    return count

def get_score_history(days: int = 90) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(f"""
        SELECT * FROM signals
        WHERE date >= date('now', '-{days} days')
        ORDER BY date
    """, conn)
    conn.close()
    return df

def run():
    print(f"[{datetime.now()}] Computing composite signal scores...")
    result = compute_composite()
    count = save_scores(result)
    
    print(f"  Composite: {result['composite']:.3f} ({result['label']})")
    print(f"  Convergence: {result['convergence']}")
    for s in result["scores"]:
        print(f"    {s['dimension']:25s}: {s['score']:+.1f}  ({s['notes']})")
    
    return result

if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
