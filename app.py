"""
CEG Research Stack — Main Application Entry Point
Constellation Energy Intelligence Dashboard
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.database import init_db

st.set_page_config(
    page_title="CEG Research Stack",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize DB on every startup (idempotent)
init_db()

# ── Sidebar navigation ────────────────────────────────────────────────────────
st.sidebar.title("⚡ CEG Research Stack")
st.sidebar.caption("Constellation Energy Intelligence")

pages = {
    "Fleet Operations": "dashboard.fleet_ops",
    "Power Markets": "dashboard.power_market",
    "Data Center Demand": "dashboard.data_center",
    "Regulatory Tracker": "dashboard.regulatory",
    "Satellite & Physical": "dashboard.satellite_physical",
    "Financial & Insider": "dashboard.financial_insider",
    "Macro Context": "dashboard.macro_context",
    "Composite Scorecard": "dashboard.composite_scorecard",
    "Signal Correlations": "dashboard.signal_correlations",
    "Alert Log": "dashboard.alert_log_page",
}

selection = st.sidebar.radio("Navigate", list(pages.keys()))

# ── Import and render selected page ──────────────────────────────────────────
import importlib

try:
    module = importlib.import_module(pages[selection])
    module.render()
except ModuleNotFoundError as e:
    st.error(
        f"**Page module not found:** `{pages[selection]}`\n\n"
        f"Error: `{e}`\n\n"
        "Ensure all dashboard page files exist in the `dashboard/` directory."
    )
except AttributeError:
    st.error(
        f"**Module `{pages[selection]}` is missing a `render()` function.**\n\n"
        "Each dashboard page must define a top-level `render()` entry point."
    )
except Exception as e:
    st.error(f"**Unexpected error loading page:** {e}")
    st.exception(e)

# ── Sidebar footer ────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.caption("Data refreshed via GitHub Actions")
st.sidebar.caption("Built for Perplexity Stock Pitch Competition")
