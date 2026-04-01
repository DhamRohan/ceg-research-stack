"""
Gmail SMTP Alert System
Sends threshold-triggered email alerts for CEG research stack.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn
from config.secrets import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, ALERT_RECIPIENT

# ── Alert Thresholds ──────────────────────────────────────────────────────
THRESHOLDS = {
    "nrc_unplanned_outage": {
        "severity": "critical",
        "category": "nuclear_ops",
        "description": "Any CEG unit drops from >90% to <10% power in 24h",
    },
    "nrc_low_capacity": {
        "severity": "warning",
        "category": "nuclear_ops",
        "threshold": 80.0,
        "description": "Fleet 7-day average capacity factor falls below 80%",
    },
    "pjm_lmp_spike": {
        "severity": "info",
        "category": "power_markets",
        "threshold": 100.0,
        "description": "PJM real-time LMP exceeds $100/MWh at any CEG node",
    },
    "pjm_lmp_negative": {
        "severity": "warning",
        "category": "power_markets",
        "threshold": -5.0,
        "description": "Sustained negative LMP (<-$5/MWh) at CEG nodes",
    },
    "insider_large_trade": {
        "severity": "info",
        "category": "financial",
        "threshold": 500000,
        "description": "Insider trade exceeds $500K (buy or sell)",
    },
    "edgar_new_filing": {
        "severity": "info",
        "category": "financial",
        "description": "New 8-K, 10-Q, 10-K, or SC 13D/G filing detected",
    },
    "firms_thermal_anomaly": {
        "severity": "warning",
        "category": "physical",
        "description": "Thermal anomaly detected within 5km of a CEG plant",
    },
    "satellite_ndvi_change": {
        "severity": "info",
        "category": "physical",
        "threshold": 0.15,
        "description": "NDVI change > 0.15 near a CEG plant (construction activity)",
    },
    "composite_score_shift": {
        "severity": "warning",
        "category": "composite",
        "threshold": 0.5,
        "description": "Composite score changes by > 0.5 in one day",
    },
    "ferc_new_filing": {
        "severity": "info",
        "category": "regulatory",
        "description": "New FERC filing on tracked docket (EL24-49, EL25-20, etc.)",
    },
}


def send_email(subject: str, body_html: str) -> bool:
    """Send an alert email via Gmail SMTP."""
    if not all([GMAIL_ADDRESS, GMAIL_APP_PASSWORD, ALERT_RECIPIENT]):
        print("  WARNING: Gmail SMTP not configured, skipping email")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"CEG Research Stack <{GMAIL_ADDRESS}>"
    msg["To"] = ALERT_RECIPIENT
    msg["Subject"] = subject

    # Plain text fallback
    plain = body_html.replace("<br>", "\n").replace("</p>", "\n").replace("<p>", "")
    import re
    plain = re.sub(r"<[^>]+>", "", plain)
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, ALERT_RECIPIENT, msg.as_string())
        return True
    except Exception as e:
        print(f"  ERROR sending email: {e}")
        return False


def log_alert(severity: str, category: str, title: str, body: str, sent: bool = False) -> int:
    """Log alert to database and optionally send email."""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO alert_log (severity, category, title, body, sent)
           VALUES (?, ?, ?, ?, ?)""",
        (severity, category, title, body, 1 if sent else 0)
    )
    alert_id = cur.lastrowid
    conn.commit()
    conn.close()
    return alert_id


def build_alert_email(alerts: list) -> str:
    """Build HTML email body from alert list."""
    severity_colors = {
        "critical": "#dc2626",
        "warning": "#f59e0b",
        "info": "#3b82f6",
    }
    
    html = f"""
    <html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
    <div style="background: #1a1a2e; color: #fff; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="margin: 0; font-size: 18px;">⚡ CEG Research Stack Alert</h1>
        <p style="margin: 5px 0 0; color: #a0a0c0; font-size: 13px;">{datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
    </div>
    <div style="padding: 20px; background: #f8f9fa; border-radius: 0 0 8px 8px;">
    """

    for alert in alerts:
        sev = alert.get("severity", "info")
        color = severity_colors.get(sev, "#6b7280")
        html += f"""
        <div style="border-left: 4px solid {color}; padding: 12px 16px; margin-bottom: 12px; background: #fff; border-radius: 0 4px 4px 0;">
            <div style="font-size: 11px; text-transform: uppercase; color: {color}; font-weight: 600; letter-spacing: 0.5px;">{sev} — {alert.get('category', 'general')}</div>
            <div style="font-size: 15px; font-weight: 600; margin: 4px 0;">{alert['title']}</div>
            <div style="font-size: 13px; color: #4a5568;">{alert['body']}</div>
        </div>
        """

    html += """
    <p style="font-size: 11px; color: #a0aec0; margin-top: 20px;">
        Constellation Energy (CEG) Research Stack — Automated Alert System<br>
        <a href="https://ceg-research-stack.streamlit.app" style="color: #3b82f6;">Open Dashboard</a>
    </p>
    </div></body></html>
    """
    return html


def check_nrc_alerts() -> list:
    """Check NRC thresholds."""
    from collectors.nrc_status import check_outage_alerts
    alerts = check_outage_alerts()
    
    # Also check fleet CF
    conn = get_conn()
    import pandas as pd
    cf = pd.read_sql_query("""
        SELECT AVG(power_pct) as avg_cf FROM nrc_status
        WHERE date >= date('now', '-7 days')
    """, conn).iloc[0]["avg_cf"]
    conn.close()
    
    if cf is not None and cf < THRESHOLDS["nrc_low_capacity"]["threshold"]:
        alerts.append({
            "severity": "warning",
            "category": "nuclear_ops",
            "title": f"LOW FLEET CAPACITY: {cf:.1f}%",
            "body": f"7-day fleet average capacity factor is {cf:.1f}%, below {THRESHOLDS['nrc_low_capacity']['threshold']}% threshold"
        })
    return alerts


def check_pjm_alerts() -> list:
    """Check PJM LMP thresholds."""
    import pandas as pd
    conn = get_conn()
    alerts = []
    
    # Spike check
    spikes = pd.read_sql_query("""
        SELECT pnode_name, lmp_total, datetime FROM pjm_lmp
        WHERE datetime >= datetime('now', '-6 hours')
          AND lmp_total > ?
        ORDER BY lmp_total DESC LIMIT 5
    """, conn, params=(THRESHOLDS["pjm_lmp_spike"]["threshold"],))
    
    for _, row in spikes.iterrows():
        alerts.append({
            "severity": "info",
            "category": "power_markets",
            "title": f"LMP SPIKE: {row['pnode_name']} ${row['lmp_total']:.1f}/MWh",
            "body": f"PJM real-time LMP at {row['pnode_name']}: ${row['lmp_total']:.1f}/MWh at {row['datetime']}"
        })
    
    # Negative LMP check
    negatives = pd.read_sql_query("""
        SELECT pnode_name, AVG(lmp_total) as avg_lmp, COUNT(*) as hours
        FROM pjm_lmp
        WHERE datetime >= datetime('now', '-6 hours')
          AND lmp_total < ?
        GROUP BY pnode_name
        HAVING hours >= 3
    """, conn, params=(THRESHOLDS["pjm_lmp_negative"]["threshold"],))
    
    for _, row in negatives.iterrows():
        alerts.append({
            "severity": "warning",
            "category": "power_markets",
            "title": f"SUSTAINED NEGATIVE LMP: {row['pnode_name']}",
            "body": f"Avg LMP ${row['avg_lmp']:.1f}/MWh over {row['hours']} hours at {row['pnode_name']}"
        })
    
    conn.close()
    return alerts


def check_insider_alerts() -> list:
    """Check insider trade thresholds."""
    import pandas as pd
    conn = get_conn()
    alerts = []
    
    trades = pd.read_sql_query("""
        SELECT owner_name, transaction_code, value, shares, transaction_date, security_title
        FROM insider_trades
        WHERE transaction_date >= date('now', '-3 days')
          AND ABS(value) > ?
    """, conn, params=(THRESHOLDS["insider_large_trade"]["threshold"],))
    conn.close()
    
    for _, row in trades.iterrows():
        direction = "BUY" if row["transaction_code"] == "P" else "SELL"
        alerts.append({
            "severity": "info",
            "category": "financial",
            "title": f"LARGE INSIDER {direction}: {row['owner_name']}",
            "body": f"{row['owner_name']} {direction} {row['shares']:.0f} shares of {row['security_title']} (${row['value']:,.0f}) on {row['transaction_date']}"
        })
    return alerts


def check_edgar_alerts() -> list:
    """Check for new EDGAR filings in last 24h."""
    import pandas as pd
    conn = get_conn()
    
    filings = pd.read_sql_query("""
        SELECT form_type, file_date, description, url FROM edgar_filings
        WHERE fetched_at >= datetime('now', '-1 day')
          AND form_type IN ('8-K', '10-Q', '10-K', 'SC 13D', 'SC 13G', 'SC 13D/A', 'SC 13G/A', '4', '13F-HR')
        ORDER BY file_date DESC
    """, conn)
    conn.close()
    
    alerts = []
    for _, row in filings.iterrows():
        alerts.append({
            "severity": "info",
            "category": "financial",
            "title": f"NEW SEC FILING: {row['form_type']}",
            "body": f"{row['form_type']} filed {row['file_date']}: {row['description'][:100]}"
        })
    return alerts


def check_thermal_alerts() -> list:
    """Check FIRMS thermal anomaly alerts."""
    import pandas as pd
    conn = get_conn()
    
    detections = pd.read_sql_query("""
        SELECT nearest_plant, COUNT(*) as n, MAX(bright_ti4) as max_bright, MIN(distance_km) as min_dist
        FROM firms_thermal
        WHERE acq_date >= date('now', '-2 days') AND distance_km < 5
        GROUP BY nearest_plant
    """, conn)
    conn.close()
    
    alerts = []
    for _, row in detections.iterrows():
        alerts.append({
            "severity": "warning",
            "category": "physical",
            "title": f"THERMAL ANOMALY near {row['nearest_plant']}",
            "body": f"{row['n']} detections within {row['min_dist']:.1f}km, max brightness {row['max_bright']:.0f}K"
        })
    return alerts


def check_ferc_alerts() -> list:
    """Check for new FERC filings on tracked dockets."""
    import pandas as pd
    conn = get_conn()
    
    filings = pd.read_sql_query("""
        SELECT docket, filing_date, description FROM ferc_filings
        WHERE fetched_at >= datetime('now', '-1 day')
        ORDER BY filing_date DESC
    """, conn)
    conn.close()
    
    alerts = []
    for _, row in filings.iterrows():
        alerts.append({
            "severity": "info",
            "category": "regulatory",
            "title": f"NEW FERC FILING: {row['docket']}",
            "body": f"Docket {row['docket']} ({row['filing_date']}): {row['description'][:120]}"
        })
    return alerts


def check_composite_shift() -> list:
    """Check if composite score shifted significantly."""
    import pandas as pd
    conn = get_conn()
    
    scores = pd.read_sql_query("""
        SELECT date, score FROM signals
        WHERE dimension = 'composite'
        ORDER BY date DESC LIMIT 2
    """, conn)
    conn.close()
    
    alerts = []
    if len(scores) >= 2:
        delta = abs(scores.iloc[0]["score"] - scores.iloc[1]["score"])
        if delta >= THRESHOLDS["composite_score_shift"]["threshold"]:
            direction = "UP" if scores.iloc[0]["score"] > scores.iloc[1]["score"] else "DOWN"
            alerts.append({
                "severity": "warning",
                "category": "composite",
                "title": f"COMPOSITE SCORE SHIFT {direction}: {delta:+.2f}",
                "body": f"Composite moved from {scores.iloc[1]['score']:.2f} to {scores.iloc[0]['score']:.2f} ({direction} {delta:.2f})"
            })
    return alerts


def run_all_checks() -> list:
    """Run all alert checks and return combined alerts."""
    all_alerts = []
    
    checkers = [
        ("NRC", check_nrc_alerts),
        ("PJM", check_pjm_alerts),
        ("Insider", check_insider_alerts),
        ("EDGAR", check_edgar_alerts),
        ("Thermal", check_thermal_alerts),
        ("FERC", check_ferc_alerts),
        ("Composite", check_composite_shift),
    ]
    
    for name, checker in checkers:
        try:
            alerts = checker()
            all_alerts.extend(alerts)
        except Exception as e:
            print(f"  ERROR in {name} alert check: {e}")
    
    return all_alerts


def run():
    """Main alert routine: check all thresholds, log, and send email if any triggers fire."""
    print(f"[{datetime.now()}] Running alert checks...")
    alerts = run_all_checks()
    
    if not alerts:
        print("  No alerts triggered")
        return {"alerts": 0, "sent": False}
    
    print(f"  {len(alerts)} alerts triggered:")
    for a in alerts:
        print(f"    [{a['severity'].upper()}] {a['title']}")
    
    # Log all alerts
    for a in alerts:
        log_alert(a["severity"], a["category"], a["title"], a["body"])
    
    # Build and send email
    subject = f"[CEG Alert] {len(alerts)} signal{'s' if len(alerts) > 1 else ''} — {datetime.now().strftime('%m/%d %H:%M')}"
    
    # Prioritize: if any critical, lead with that
    critical = [a for a in alerts if a["severity"] == "critical"]
    if critical:
        subject = f"🚨 [CEG CRITICAL] {critical[0]['title']}"
    
    html = build_alert_email(alerts)
    sent = send_email(subject, html)
    
    # Update sent status
    if sent:
        conn = get_conn()
        conn.execute("""
            UPDATE alert_log SET sent = 1
            WHERE id IN (
                SELECT id FROM alert_log 
                WHERE sent = 0 
                ORDER BY id DESC LIMIT ?
            )
        """, (len(alerts),))
        conn.commit()
        conn.close()
    
    print(f"  Email {'sent' if sent else 'FAILED'} to {ALERT_RECIPIENT}")
    return {"alerts": len(alerts), "sent": sent}


if __name__ == "__main__":
    from config.database import init_db
    init_db()
    run()
