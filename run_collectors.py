#!/usr/bin/env python3
"""
Master Collector Runner
Orchestrates all data collection, signal scoring, alerting, and Sheets sync.
Called by GitHub Actions on cron schedules.

Usage:
    python run_collectors.py daily      # NRC, PJM, ERCOT, EDGAR, FIRMS, alerts
    python run_collectors.py weekly     # EIA, FERC, PJM queue, Sentinel, Sheets sync
    python run_collectors.py monthly    # FRED macro, full Sheets sync
    python run_collectors.py all        # Everything
"""
import sys
import os
import traceback
from datetime import datetime

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.database import init_db

def run_module(name: str, run_fn):
    """Run a module's run() function with error handling."""
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    try:
        result = run_fn()
        print(f"  ✓ {name} complete: {result}")
        return True, result
    except Exception as e:
        print(f"  ✗ {name} FAILED: {e}")
        traceback.print_exc()
        return False, str(e)


def run_daily():
    """Daily collection: real-time & near-real-time data sources."""
    results = {}
    
    # NRC reactor status
    from collectors.nrc_status import run as nrc_run
    results["nrc"] = run_module("NRC Reactor Status", nrc_run)
    
    # PJM LMP prices
    from collectors.pjm_lmp import run as pjm_run
    results["pjm_lmp"] = run_module("PJM LMP Prices", pjm_run)
    
    # ERCOT prices
    from collectors.ercot_prices import run as ercot_run
    results["ercot"] = run_module("ERCOT Prices", ercot_run)
    
    # SEC EDGAR filings + insider trades
    from collectors.edgar_monitor import run as edgar_run
    results["edgar"] = run_module("SEC EDGAR Monitor", edgar_run)
    
    # NASA FIRMS thermal
    from collectors.firms_thermal import run as firms_run
    results["firms"] = run_module("NASA FIRMS Thermal", firms_run)
    
    # Signal scoring
    from processors.signal_scorer import run as score_run
    results["signals"] = run_module("Signal Scorer", score_run)
    
    # Alert checks
    from alerts.email_alert import run as alert_run
    results["alerts"] = run_module("Alert System", alert_run)
    
    return results


def run_weekly():
    """Weekly collection: slower-updating data sources."""
    results = {}
    
    # EIA generation
    from collectors.eia_generation import run as eia_run
    results["eia"] = run_module("EIA Generation", eia_run)
    
    # FERC docket filings
    from collectors.ferc_docket import run as ferc_run
    results["ferc"] = run_module("FERC Docket Monitor", ferc_run)
    
    # PJM interconnection queue
    from collectors.pjm_queue import run as queue_run
    results["pjm_queue"] = run_module("PJM Queue Monitor", queue_run)
    
    # Sentinel satellite imagery
    from collectors.sentinel_imagery import run as sentinel_run
    results["sentinel"] = run_module("Sentinel Imagery", sentinel_run)
    
    # Signal scoring (refresh)
    from processors.signal_scorer import run as score_run
    results["signals"] = run_module("Signal Scorer", score_run)
    
    # Sheets sync
    from sheets.sheets_updater import run as sheets_run
    results["sheets"] = run_module("Google Sheets Sync", sheets_run)
    
    return results


def run_monthly():
    """Monthly collection: macro data & full sync."""
    results = {}
    
    # FRED macro
    from collectors.fred_macro import run as fred_run
    results["fred"] = run_module("FRED Macro Data", fred_run)
    
    # Full sheets sync
    from sheets.sheets_updater import run as sheets_run
    results["sheets"] = run_module("Google Sheets Full Sync", sheets_run)
    
    return results


def run_all():
    """Run everything."""
    results = {}
    results.update(run_daily())
    results.update(run_weekly())
    results.update(run_monthly())
    return results


def main():
    print(f"\n{'#'*60}")
    print(f"  CEG Research Stack — Collector Runner")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}")
    
    # Initialize database
    init_db()
    
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    
    dispatch = {
        "daily": run_daily,
        "weekly": run_weekly,
        "monthly": run_monthly,
        "all": run_all,
    }
    
    if mode not in dispatch:
        print(f"Unknown mode: {mode}. Use: daily, weekly, monthly, all")
        sys.exit(1)
    
    print(f"\n  Mode: {mode.upper()}")
    results = dispatch[mode]()
    
    # Summary
    print(f"\n{'#'*60}")
    print(f"  SUMMARY — {mode.upper()}")
    print(f"{'#'*60}")
    successes = sum(1 for ok, _ in results.values() if ok)
    failures = sum(1 for ok, _ in results.values() if not ok)
    print(f"  Successes: {successes}")
    print(f"  Failures:  {failures}")
    
    if failures > 0:
        print("\n  Failed modules:")
        for name, (ok, result) in results.items():
            if not ok:
                print(f"    - {name}: {result}")
    
    # Exit with error code if any failures
    sys.exit(1 if failures > 0 else 0)


if __name__ == "__main__":
    main()
