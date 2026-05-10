"""
Live data fetching and prompt formatting helpers for the Algal Assistant.

Kept separate from rag_engine.py to stay within the 300-line rule.
"""
import logging
import requests

logger = logging.getLogger(__name__)


def format_cell_counts(data: dict) -> str:
    """
    Format cell count readings grouped by severity bucket.

    Args:
        data: JSON response from /api/cell-counts.

    Returns:
        Human-readable multi-line string grouped Critical / High / Medium / Low.
    """
    readings = data.get("readings", [])
    if not readings:
        return "No cell count readings available."

    groups: dict[str, list[str]] = {"Critical": [], "High": [], "Medium": [], "Low": []}
    for r in readings:
        beach = r.get("beach_name", "Unknown")
        count = r.get("cell_count_per_litre", 0)
        sev = r.get("severity", "Low")
        entry = f"  {beach}: {count:,} cells/L"
        groups[sev if sev in groups else "Low"].append(entry)

    lines = [f"Total readings: {len(readings)}"]
    for sev in ("Critical", "High", "Medium", "Low"):
        if groups[sev]:
            lines.append(f"\n{sev} ({len(groups[sev])} beaches):")
            lines.extend(groups[sev])
    return "\n".join(lines)


def fetch_live_context(base_url: str) -> str:
    """
    Fetch live platform data from the API in data-priority order.

    Priority:
      1. Ground truth cell counts  (HIGHEST — SA Gov field sampling)
      2. Beach safety scores        (derived from ground truth)
      3. Live weather               (BOM Open-Meteo)
      4. Satellite note             (static block)

    Args:
        base_url: API base URL e.g. http://localhost:8000/api

    Returns:
        Formatted string. Empty string if the API is unreachable.
    """
    parts: list[str] = []

    # PRIORITY 1 — Ground truth cell counts
    try:
        r = requests.get(base_url + "/cell-counts", timeout=5)
        r.raise_for_status()
        parts.append(
            "GROUND TRUTH WATER SAMPLING DATA — HIGHEST PRIORITY\n"
            "Source: SA Government field water sampling — most accurate\n"
            + format_cell_counts(r.json())
        )
    except Exception as e:
        logger.warning(f"fetch_live_context: cell-counts failed: {e}")

    # PRIORITY 2 — Beach safety scores
    try:
        r = requests.get(base_url + "/beach-safety", timeout=5)
        r.raise_for_status()
        scores = r.json().get("scores", [])[:10]
        lines = [f"BEACH SAFETY SCORES (calculated from ground truth)\n"
                 f"Top {len(scores)} beaches by safety score:"]
        for s in scores:
            lines.append(
                f"  {s.get('beach')}: {s.get('score')}/100 [{s.get('label')}]"
                f" — {s.get('cell_count', 0):,} cells/L"
            )
        parts.append("\n".join(lines))
    except Exception as e:
        logger.warning(f"fetch_live_context: beach-safety failed: {e}")

    # PRIORITY 3 — Live weather
    try:
        r = requests.get(base_url + "/weather", timeout=5)
        r.raise_for_status()
        readings = r.json().get("readings", [])[:5]
        lines = ["LIVE COASTAL WEATHER (BOM Open-Meteo)"]
        for w in readings:
            lines.append(
                f"  {w.get('location_name')}: wind {w.get('wind_speed')} km/h,"
                f" SST {w.get('sea_surface_temp')}°C,"
                f" waves {w.get('wave_height')} m"
            )
        parts.append("\n".join(lines))
    except Exception as e:
        logger.warning(f"fetch_live_context: weather failed: {e}")

    # PRIORITY 4 — Satellite (static block, always appended)
    parts.append(
        "SATELLITE DATA — SUPPORTING CONTEXT ONLY\n"
        "Sentinel-2 satellite pass May 8 2026.\n"
        "SFABI min 0.0202 max 0.4358 mean 0.1440.\n"
        "High severity bloom areas detected from space via SFABI above 0.15.\n"
        "Note: Ground truth cell counts above take priority over satellite readings."
    )

    return "\n\n".join(parts)
