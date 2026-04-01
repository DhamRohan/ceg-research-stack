"""Satellite & Physical Validation dashboard page."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.database import get_conn

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import json
from datetime import datetime, timedelta

PLANT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "plant_config.json")


def _load_plant_config():
    with open(PLANT_CONFIG_PATH) as f:
        return json.load(f)


def _build_plant_locations(cfg: dict) -> pd.DataFrame:
    """Build a dataframe of plant lat/lon from plant_config.json."""
    rows = []
    for key, plant in cfg.get("plants", {}).items():
        lat = plant.get("lat")
        lon = plant.get("lon")
        if lat is None or lon is None:
            continue
        rows.append({
            "plant_key": key,
            "name": plant.get("name", key),
            "state": plant.get("state", ""),
            "lat": lat,
            "lon": lon,
            "net_mw": plant.get("net_mw", 0),
            "reactor_type": plant.get("reactor_type", ""),
            "slr_status": plant.get("slr_status", ""),
        })
    return pd.DataFrame(rows)


def render():
    st.header("Satellite & Physical Validation")

    conn = get_conn()
    cfg = _load_plant_config()

    cutoff_30d = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    cutoff_7d = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    # ── Load satellite data ────────────────────────────────────────────────────
    df_sat = pd.read_sql_query(
        """
        SELECT date, plant, ndvi_mean, ndvi_change, alert_triggered, image_path
        FROM satellite_changes
        ORDER BY date DESC
        """,
        conn,
    )

    # ── Load FIRMS thermal ─────────────────────────────────────────────────────
    df_firms = pd.read_sql_query(
        f"""
        SELECT id, acq_date, acq_time, latitude, longitude,
               bright_ti4, confidence, frp, nearest_plant, distance_km
        FROM firms_thermal
        WHERE acq_date >= '{cutoff_7d}'
        ORDER BY acq_date DESC, acq_time DESC
        """,
        conn,
    )

    # ── Metrics ────────────────────────────────────────────────────────────────
    ndvi_alerts_30d = 0
    if not df_sat.empty:
        df_sat_30d = df_sat[df_sat["date"] >= cutoff_30d]
        ndvi_alerts_30d = int(df_sat_30d["alert_triggered"].sum()) if not df_sat_30d.empty else 0

    thermal_7d = len(df_firms)
    plants_monitored = len(cfg.get("plants", {}))

    c1, c2, c3 = st.columns(3)
    c1.metric("NDVI Alerts (30d)", str(ndvi_alerts_30d))
    c2.metric("Thermal Detections (7d)", str(thermal_7d))
    c3.metric("Plants Monitored", str(plants_monitored))

    st.divider()

    # ── Map: plant locations + thermal detections ──────────────────────────────
    st.subheader("CEG Plant Locations & Thermal Detections")

    df_plants = _build_plant_locations(cfg)

    fig_map = go.Figure()

    # Plant location markers
    if not df_plants.empty:
        fig_map.add_trace(
            go.Scattermapbox(
                lat=df_plants["lat"].tolist(),
                lon=df_plants["lon"].tolist(),
                mode="markers+text",
                marker=dict(
                    size=14,
                    color="#3498db",
                    opacity=0.85,
                ),
                text=df_plants["name"].tolist(),
                textposition="top center",
                textfont=dict(size=10, color="white"),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "State: %{customdata[0]}<br>"
                    "Net MW: %{customdata[1]:,.0f}<br>"
                    "Type: %{customdata[2]}<br>"
                    "Lat: %{lat:.4f}<br>"
                    "Lon: %{lon:.4f}<extra></extra>"
                ),
                customdata=df_plants[["state", "net_mw", "reactor_type"]].values.tolist(),
                name="CEG Plants",
            )
        )

    # Thermal detection overlays
    if not df_firms.empty:
        df_firms_valid = df_firms.dropna(subset=["latitude", "longitude"])
        if not df_firms_valid.empty:
            # Normalize FRP for marker sizing
            frp_vals = df_firms_valid["frp"].fillna(1.0)
            frp_min, frp_max = frp_vals.min(), frp_vals.max()
            if frp_max > frp_min:
                sizes = 8 + 18 * (frp_vals - frp_min) / (frp_max - frp_min)
            else:
                sizes = [12] * len(df_firms_valid)

            fig_map.add_trace(
                go.Scattermapbox(
                    lat=df_firms_valid["latitude"].tolist(),
                    lon=df_firms_valid["longitude"].tolist(),
                    mode="markers",
                    marker=dict(
                        size=sizes,
                        color="#e74c3c",
                        opacity=0.7,
                    ),
                    hovertemplate=(
                        "<b>Thermal Detection</b><br>"
                        "Date: %{customdata[0]}<br>"
                        "Nearest Plant: %{customdata[1]}<br>"
                        "Distance: %{customdata[2]:.1f} km<br>"
                        "Brightness: %{customdata[3]:.1f} K<br>"
                        "FRP: %{customdata[4]:.1f} MW<br>"
                        "Confidence: %{customdata[5]}<extra></extra>"
                    ),
                    customdata=df_firms_valid[
                        ["acq_date", "nearest_plant", "distance_km", "bright_ti4", "frp", "confidence"]
                    ].fillna("—").values.tolist(),
                    name="Thermal Detections (7d)",
                )
            )

    # Map center: centroid of plant locations
    if not df_plants.empty:
        center_lat = df_plants["lat"].mean()
        center_lon = df_plants["lon"].mean()
    else:
        center_lat, center_lon = 40.5, -83.0  # Approximate US midwest default

    fig_map.update_layout(
        mapbox_style="open-street-map",
        mapbox=dict(
            center=dict(lat=center_lat, lon=center_lon),
            zoom=5,
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=500,
        legend=dict(
            bgcolor="rgba(30,30,30,0.8)",
            font=dict(color="white"),
            x=0.01,
            y=0.99,
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    st.plotly_chart(fig_map, use_container_width=True)

    st.divider()

    # ── NDVI Change Table ──────────────────────────────────────────────────────
    st.subheader("NDVI Change Detection — All Records")

    if df_sat.empty:
        st.info("No satellite change detection data yet.")
    else:
        df_sat_disp = df_sat.copy()
        df_sat_disp["alert_triggered"] = df_sat_disp["alert_triggered"].apply(
            lambda x: "🔴 YES" if x else "—"
        )
        df_sat_disp["ndvi_change"] = df_sat_disp["ndvi_change"].apply(
            lambda x: f"{x:+.4f}" if pd.notna(x) else "—"
        )
        df_sat_disp["ndvi_mean"] = df_sat_disp["ndvi_mean"].apply(
            lambda x: f"{x:.4f}" if pd.notna(x) else "—"
        )

        # Filters
        col_f1, col_f2 = st.columns([2, 1])
        with col_f1:
            plant_filter = st.multiselect(
                "Filter by plant",
                options=sorted(df_sat_disp["plant"].unique().tolist()),
                default=[],
                key="ndvi_plant_filter",
            )
        with col_f2:
            alerts_only = st.checkbox("Show alerts only", key="ndvi_alerts_only")

        df_sat_show = df_sat_disp.copy()
        if plant_filter:
            df_sat_show = df_sat_show[df_sat_show["plant"].isin(plant_filter)]
        if alerts_only:
            df_sat_show = df_sat_show[df_sat_show["alert_triggered"] == "🔴 YES"]

        st.dataframe(
            df_sat_show[["date", "plant", "ndvi_mean", "ndvi_change", "alert_triggered", "image_path"]]
            .rename(columns={
                "date": "Date",
                "plant": "Plant",
                "ndvi_mean": "NDVI Mean",
                "ndvi_change": "NDVI Change",
                "alert_triggered": "Alert",
                "image_path": "Image Path",
            }),
            use_container_width=True,
            hide_index=True,
        )

        # NDVI trend chart if data available
        if not df_sat.empty and len(df_sat) > 1:
            st.subheader("NDVI Trend by Plant")
            df_ndvi_plot = df_sat.dropna(subset=["ndvi_mean"]).copy()
            if not df_ndvi_plot.empty:
                selected_ndvi_plants = plant_filter if plant_filter else sorted(df_ndvi_plot["plant"].unique().tolist())[:5]
                df_ndvi_plot = df_ndvi_plot[df_ndvi_plot["plant"].isin(selected_ndvi_plants)]
                if not df_ndvi_plot.empty:
                    fig_ndvi = px.line(
                        df_ndvi_plot.sort_values("date"),
                        x="date",
                        y="ndvi_mean",
                        color="plant",
                        title="NDVI Mean Over Time",
                        labels={"date": "Date", "ndvi_mean": "NDVI Mean", "plant": "Plant"},
                        template="plotly_dark",
                        markers=True,
                    )
                    fig_ndvi.update_layout(
                        legend=dict(orientation="h", y=-0.25),
                        margin=dict(t=40, b=10),
                    )
                    st.plotly_chart(fig_ndvi, use_container_width=True)

    st.divider()

    # ── FIRMS Thermal Table ────────────────────────────────────────────────────
    st.subheader("NASA FIRMS Thermal Detections — Last 7 Days")

    if df_firms.empty:
        st.info("No thermal anomaly detections in the last 7 days.")
    else:
        df_firms_disp = df_firms.copy()

        # Confidence color coding
        def _conf_label(c):
            cl = str(c).lower()
            if cl in ("high", "h"):
                return "🔴 High"
            elif cl in ("nominal", "n", "medium"):
                return "🟡 Nominal"
            else:
                return "⚪ Low"

        df_firms_disp["confidence"] = df_firms_disp["confidence"].apply(_conf_label)
        df_firms_disp["distance_km"] = df_firms_disp["distance_km"].apply(
            lambda x: f"{x:.2f} km" if pd.notna(x) else "—"
        )
        df_firms_disp["frp"] = df_firms_disp["frp"].apply(
            lambda x: f"{x:.1f} MW" if pd.notna(x) else "—"
        )
        df_firms_disp["bright_ti4"] = df_firms_disp["bright_ti4"].apply(
            lambda x: f"{x:.1f} K" if pd.notna(x) else "—"
        )

        st.dataframe(
            df_firms_disp[[
                "acq_date", "acq_time", "nearest_plant", "distance_km",
                "bright_ti4", "frp", "confidence", "latitude", "longitude"
            ]].rename(columns={
                "acq_date": "Date",
                "acq_time": "Time (UTC)",
                "nearest_plant": "Nearest Plant",
                "distance_km": "Distance",
                "bright_ti4": "Brightness",
                "frp": "FRP",
                "confidence": "Confidence",
                "latitude": "Lat",
                "longitude": "Lon",
            }),
            use_container_width=True,
            hide_index=True,
        )

    conn.close()
