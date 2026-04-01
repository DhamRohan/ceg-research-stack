"""SQLite database initialization and connection management."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ceg_research.db")

def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    
    cur.executescript("""
    -- NRC daily reactor power status
    CREATE TABLE IF NOT EXISTS nrc_status (
        date TEXT NOT NULL,
        unit TEXT NOT NULL,
        power_pct REAL,
        fetched_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (date, unit)
    );
    CREATE INDEX IF NOT EXISTS idx_nrc_unit ON nrc_status(unit);
    
    -- EIA monthly generation
    CREATE TABLE IF NOT EXISTS eia_generation (
        period TEXT NOT NULL,
        plant_id INTEGER NOT NULL,
        plant_name TEXT,
        fuel TEXT,
        generation_mwh REAL,
        capacity_factor REAL,
        fetched_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (period, plant_id)
    );
    
    -- PJM LMP data
    CREATE TABLE IF NOT EXISTS pjm_lmp (
        datetime TEXT NOT NULL,
        market TEXT NOT NULL,
        pnode_name TEXT NOT NULL,
        lmp_total REAL,
        lmp_energy REAL,
        lmp_congestion REAL,
        lmp_loss REAL,
        fetched_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (datetime, market, pnode_name)
    );
    CREATE INDEX IF NOT EXISTS idx_pjm_pnode ON pjm_lmp(pnode_name);
    
    -- ERCOT LMP data
    CREATE TABLE IF NOT EXISTS ercot_lmp (
        datetime TEXT NOT NULL,
        settlement_point TEXT NOT NULL,
        lmp REAL,
        fetched_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (datetime, settlement_point)
    );
    
    -- PJM interconnection queue
    CREATE TABLE IF NOT EXISTS pjm_queue (
        queue_number TEXT PRIMARY KEY,
        queue_date TEXT,
        project_name TEXT,
        fuel_type TEXT,
        mw REAL,
        state TEXT,
        county TEXT,
        to_zone TEXT,
        status TEXT,
        poi TEXT,
        first_seen TEXT DEFAULT (date('now')),
        fetched_at TEXT DEFAULT (datetime('now'))
    );
    
    -- FERC eLibrary filings
    CREATE TABLE IF NOT EXISTS ferc_filings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        docket TEXT NOT NULL,
        filing_date TEXT,
        document_type TEXT,
        description TEXT,
        url TEXT,
        fetched_at TEXT DEFAULT (datetime('now')),
        UNIQUE(docket, filing_date, description)
    );
    
    -- SEC EDGAR filings
    CREATE TABLE IF NOT EXISTS edgar_filings (
        accession_no TEXT PRIMARY KEY,
        form_type TEXT,
        file_date TEXT,
        description TEXT,
        url TEXT,
        fetched_at TEXT DEFAULT (datetime('now'))
    );
    
    -- Insider transactions
    CREATE TABLE IF NOT EXISTS insider_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        accession_no TEXT,
        owner_name TEXT,
        owner_title TEXT,
        transaction_date TEXT,
        transaction_code TEXT,
        direction TEXT,
        shares REAL,
        price_per_share REAL,
        value REAL,
        shares_after REAL,
        security_title TEXT,
        fetched_at TEXT DEFAULT (datetime('now')),
        UNIQUE(accession_no, owner_name, transaction_date, transaction_code)
    );
    
    -- Satellite change detection
    CREATE TABLE IF NOT EXISTS satellite_changes (
        date TEXT NOT NULL,
        plant TEXT NOT NULL,
        ndvi_mean REAL,
        ndvi_change REAL,
        alert_triggered INTEGER DEFAULT 0,
        image_path TEXT,
        fetched_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (date, plant)
    );
    
    -- NASA FIRMS thermal anomalies
    CREATE TABLE IF NOT EXISTS firms_thermal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        acq_date TEXT,
        acq_time TEXT,
        latitude REAL,
        longitude REAL,
        bright_ti4 REAL,
        confidence TEXT,
        frp REAL,
        nearest_plant TEXT,
        distance_km REAL,
        fetched_at TEXT DEFAULT (datetime('now'))
    );
    
    -- FRED macro data
    CREATE TABLE IF NOT EXISTS fred_data (
        date TEXT NOT NULL,
        series_id TEXT NOT NULL,
        value REAL,
        fetched_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (date, series_id)
    );
    
    -- Composite signals
    CREATE TABLE IF NOT EXISTS signals (
        date TEXT NOT NULL,
        dimension TEXT NOT NULL,
        signal_name TEXT NOT NULL,
        score REAL,
        raw_value REAL,
        notes TEXT,
        PRIMARY KEY (date, dimension, signal_name)
    );
    
    -- Alert log
    CREATE TABLE IF NOT EXISTS alert_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT DEFAULT (datetime('now')),
        severity TEXT NOT NULL,
        category TEXT,
        title TEXT NOT NULL,
        body TEXT,
        sent INTEGER DEFAULT 0
    );
    
    -- 13F institutional ownership
    CREATE TABLE IF NOT EXISTS institutional_holdings (
        report_date TEXT NOT NULL,
        manager_name TEXT NOT NULL,
        manager_cik TEXT,
        shares REAL,
        value_thousands REAL,
        change_shares REAL,
        change_pct REAL,
        fetched_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (report_date, manager_name)
    );
    """)
    
    conn.commit()
    conn.close()
    return True

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
