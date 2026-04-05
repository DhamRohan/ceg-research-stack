"""
Secrets management — loads from environment variables, Streamlit secrets, or .env file.
In production: GitHub Secrets → GitHub Actions env vars, and Streamlit secrets.toml.
For local dev: create a .env file in the project root.
"""
import os
import json

def _get(key: str, default: str = "") -> str:
    """Try Streamlit secrets first, then env vars, then default."""
    try:
        import streamlit as st
        val = st.secrets.get(key, None)
        if val:
            return str(val)
    except Exception:
        pass
    return os.environ.get(key, default)

# --- API Keys ---
EIA_API_KEY = _get("EIA_API_KEY")
FRED_API_KEY = _get("FRED_API_KEY")
PJM_SUBSCRIPTION_KEY = _get("PJM_SUBSCRIPTION_KEY") or _get("PJM_API_KEY")  # Ocp-Apim-Subscription-Key for api.pjm.com
ERCOT_SUBSCRIPTION_KEY = _get("ERCOT_SUBSCRIPTION_KEY")
ERCOT_USERNAME = _get("ERCOT_USERNAME")
ERCOT_PASSWORD = _get("ERCOT_PASSWORD")
FIRMS_MAP_KEY = _get("FIRMS_MAP_KEY")
COPERNICUS_CLIENT_ID = _get("COPERNICUS_CLIENT_ID")
COPERNICUS_CLIENT_SECRET = _get("COPERNICUS_CLIENT_SECRET")

# --- SEC EDGAR ---
EDGAR_USER_AGENT = _get("EDGAR_USER_AGENT", "Rohan Dham dham0013@umn.edu")

# --- Gmail SMTP ---
GMAIL_ADDRESS = _get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = _get("GMAIL_APP_PASSWORD")
ALERT_RECIPIENT = _get("ALERT_RECIPIENT")

# --- Google Sheets ---
GOOGLE_SHEET_ID = _get("GOOGLE_SHEET_ID")

def get_google_service_account_info() -> dict:
    """Return service account credentials dict."""
    # Try Streamlit secrets (stored as TOML section)
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass
    # Try env var (JSON string)
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        return json.loads(sa_json)
    # Try local file
    sa_path = os.path.join(os.path.dirname(__file__), "service_account.json")
    if os.path.exists(sa_path):
        with open(sa_path) as f:
            return json.load(f)
    return {}

# --- GitHub ---
GITHUB_TOKEN = _get("GITHUB_TOKEN")
GITHUB_REPO = _get("GITHUB_REPO", "DhamRohan/ceg-research-stack")
