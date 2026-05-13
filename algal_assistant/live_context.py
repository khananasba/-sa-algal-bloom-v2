"""
Live data fetching for the Algal Assistant — direct DB queries.

Queries Supabase directly instead of making HTTP calls back to the API server.
This avoids the single-worker deadlock on Render where the /algal-assistant
handler would block waiting for sub-requests to /cell-counts etc. that the
same worker could never serve.

Kept separate from rag_engine.py to stay within the 300-line rule.
"""
import os
import sys
import logging

logger = logging.getLogger(__name__)

# Ensure project root is on path so db_config is importable
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── Formatters (kept for compatibility) ───────────────────────────────────────

def format_cell_counts(data: dict) -> str:
    readings = data.get("readings", [])
    if not readings:
        return "No cell count readings available."
    groups: dict[str, list[str]] = {"Critical": [], "High": [], "Medium": [], "Low": []}
    for r in readings:
        beach = r.get("beach_name", "Unknown")
        count = r.get("cell_count_per_litre", 0)
        sev   = r.get("severity", "Low")
        groups[sev if sev in groups else "Low"].append(f"  {beach}: {count:,} cells/L")
    lines = [f"Total readings: {len(readings)}"]
    for sev in ("Critical", "High", "Medium", "Low"):
        if groups[sev]:
            lines.append(f"\n{sev} ({len(groups[sev])} beaches):")
            lines.extend(groups[sev])
    return "\n".join(lines)


def format_satellite(data: dict) -> str:
    features    = data.get("features", [])
    data_source = data.get("data_source", "unknown")
    last_updated = data.get("last_updated") or "unknown"
    sat_features = [f for f in features if f.get("properties", {}).get("sfabi") is not None]
    if not sat_features or data_source == "ground_truth_fallback":
        return (
            "SATELLITE DATA — STATUS\n"
            "No current satellite SFABI data available.\n"
            "The bloom heatmap is showing ground truth cell counts as fallback.\n"
            f"Last API update: {last_updated}\n"
            "Note: Use ground truth cell counts above for safety decisions."
        )
    sfabi_vals = [f["properties"]["sfabi"] for f in sat_features]
    sev_counts: dict[str, int] = {}
    for f in sat_features:
        s = f["properties"].get("severity", "Low")
        sev_counts[s] = sev_counts.get(s, 0) + 1
    return (
        "SATELLITE DATA — SUPPORTING CONTEXT\n"
        f"Last satellite pass: {last_updated}\n"
        f"Total coastal pixels sampled: {len(sat_features)}\n"
        f"SFABI range: min {min(sfabi_vals):.4f} max {max(sfabi_vals):.4f} "
        f"mean {sum(sfabi_vals)/len(sfabi_vals):.4f}\n"
        f"High severity pixels (SFABI>0.15): {sev_counts.get('High', 0)}\n"
        f"Medium severity pixels (0.05–0.15): {sev_counts.get('Medium', 0)}\n"
        f"Low severity pixels (0.02–0.05):   {sev_counts.get('Low', 0)}\n"
        "IMPORTANT: Satellite shows bloom signatures only. "
        "Always defer to ground truth cell counts for safety decisions."
    )


# ── Direct DB helpers ─────────────────────────────────────────────────────────

def _db_cell_counts() -> str | None:
    """Query KareniaReadings directly from Supabase."""
    try:
        from db_config import get_connection, adapt_sql
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(adapt_sql("""
            SELECT TOP 50
                beach_name, cell_count_per_litre, severity
            FROM KareniaReadings
            ORDER BY recorded_at DESC
        """))
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return None
        groups: dict[str, list[str]] = {"Critical": [], "High": [], "Medium": [], "Low": []}
        for r in rows:
            beach = r[0] or "Unknown"
            count = r[1] or 0
            sev   = r[2] or "Low"
            groups[sev if sev in groups else "Low"].append(f"  {beach}: {count:,} cells/L")
        lines = [
            "GROUND TRUTH WATER SAMPLING DATA — HIGHEST PRIORITY",
            "Source: SA Government field water sampling — most accurate",
            f"Total readings: {len(rows)}",
        ]
        for sev in ("Critical", "High", "Medium", "Low"):
            if groups[sev]:
                lines.append(f"\n{sev} ({len(groups[sev])} beaches):")
                lines.extend(groups[sev])
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"_db_cell_counts failed: {e}")
        return None


def _db_safety() -> str | None:
    """Compute beach safety scores directly from KareniaReadings."""
    try:
        from db_config import get_connection, adapt_sql
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(adapt_sql("""
            SELECT TOP 15
                beach_name, cell_count_per_litre, severity
            FROM KareniaReadings
            ORDER BY cell_count_per_litre DESC
        """))
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return None
        def _score(c):
            if c >= 50000: return 20, "Danger"
            if c >= 10000: return 42, "Warning"
            if c >= 1000:  return 65, "Caution"
            return 85, "Safe"
        lines = [f"BEACH SAFETY SCORES (calculated from ground truth)\nTop {len(rows)} beaches:"]
        for r in rows:
            sc, lbl = _score(r[1] or 0)
            lines.append(f"  {r[0]}: {sc}/100 [{lbl}] — {(r[1] or 0):,} cells/L")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"_db_safety failed: {e}")
        return None


def _db_weather() -> str | None:
    """Query WeatherReadings directly from Supabase."""
    try:
        from db_config import get_connection, adapt_sql, IS_POSTGRES
        conn   = get_connection()
        cursor = conn.cursor()
        if IS_POSTGRES:
            cursor.execute("""
                SELECT DISTINCT ON (location_name)
                    location_name, wind_speed, sea_surface_temp, wave_height
                FROM weatherreadings
                ORDER BY location_name, recorded_at DESC
                LIMIT 5
            """)
        else:
            cursor.execute("""
                SELECT TOP 5 location_name, wind_speed, sea_surface_temp, wave_height
                FROM WeatherReadings
                ORDER BY recorded_at DESC
            """)
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return None
        lines = ["LIVE COASTAL WEATHER (BOM Open-Meteo)"]
        for r in rows:
            lines.append(
                f"  {r[0]}: wind {r[1]} km/h, SST {r[2]}°C, waves {r[3]} m"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"_db_weather failed: {e}")
        return None


# ── Public entry point ────────────────────────────────────────────────────────

def fetch_live_context(base_url: str = None) -> str:
    """
    Fetch live platform data for the Algal Assistant.

    Queries Supabase directly (no HTTP self-calls) to avoid the single-worker
    deadlock on Render free tier where the API cannot serve sub-requests while
    handling the /algal-assistant request.

    Args:
        base_url: Ignored — kept for backwards compatibility with rag_engine.py.

    Returns:
        Formatted multi-section string. Empty string if DB is unreachable.
    """
    parts: list[str] = []

    cell_str = _db_cell_counts()
    if cell_str:
        parts.append(cell_str)

    safety_str = _db_safety()
    if safety_str:
        parts.append(safety_str)

    weather_str = _db_weather()
    if weather_str:
        parts.append(weather_str)

    if not parts:
        logger.warning("fetch_live_context: all DB queries returned empty — no live data")

    return "\n\n".join(parts)
