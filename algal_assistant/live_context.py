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


def format_satellite(data: dict) -> str:
    """
    Format live satellite bloom data from /api/bloom-heatmap.

    Args:
        data: JSON response from /api/bloom-heatmap (GeoJSON FeatureCollection).

    Returns:
        Human-readable string with SFABI stats and severity breakdown,
        or a note if no real satellite data is available.
    """
    features = data.get("features", [])
    data_source = data.get("data_source", "unknown")
    last_updated = data.get("last_updated") or "unknown"

    # Only process real Sentinel-2 pixels (sfabi != null)
    sat_features = [f for f in features if f.get("properties", {}).get("sfabi") is not None]

    if not sat_features or data_source == "ground_truth_fallback":
        return (
            "SATELLITE DATA — SENTINEL-2 STATUS\n"
            "Satellite: No current Sentinel-2 SFABI data available.\n"
            "The bloom heatmap is showing ground truth cell counts as fallback.\n"
            "Satellite imagery refreshes daily via GitHub Actions at 2am UTC.\n"
            f"Last API update: {last_updated}\n"
            "Note: Use ground truth cell counts above for safety decisions."
        )

    sfabi_vals = [f["properties"]["sfabi"] for f in sat_features]
    sev_counts = {"High": 0, "Medium": 0, "Low": 0}
    for f in sat_features:
        sev = f["properties"].get("severity", "Low")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1

    return (
        "SATELLITE DATA — SENTINEL-2 SFABI (SUPPORTING CONTEXT)\n"
        f"Source: Real Sentinel-2 satellite imagery via Google Earth Engine\n"
        f"Last satellite pass: {last_updated}\n"
        f"Total coastal pixels sampled: {len(sat_features)}\n"
        f"SFABI range: min {min(sfabi_vals):.4f} max {max(sfabi_vals):.4f} "
        f"mean {sum(sfabi_vals)/len(sfabi_vals):.4f}\n"
        f"High severity bloom pixels (SFABI>0.15): {sev_counts['High']}\n"
        f"Medium severity pixels (SFABI 0.05-0.15): {sev_counts['Medium']}\n"
        f"Low severity pixels (SFABI 0.02-0.05): {sev_counts['Low']}\n"
        "IMPORTANT: Satellite SFABI shows bloom signatures but cannot measure\n"
        "exact Karenia cell counts. Always defer to ground truth data above."
    )


def fetch_live_context(base_url: str) -> str:
    """
    Fetch live platform data from the API in data-priority order.

    Priority:
      1. Ground truth cell counts  (HIGHEST — SA Gov field sampling)
      2. Beach safety scores        (derived from ground truth)
      3. Live weather               (BOM Open-Meteo)
      4. Satellite SFABI            (Sentinel-2 via GEE — supporting only)

    Args:
        base_url: API base URL e.g. https://sa-algal-bloom-v2.onrender.com/api

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

    # PRIORITY 4 — Live satellite data from /api/bloom-heatmap
    try:
        r = requests.get(base_url + "/bloom-heatmap", timeout=5)
        r.raise_for_status()
        parts.append(format_satellite(r.json()))
    except Exception as e:
        logger.warning(f"fetch_live_context: bloom-heatmap failed: {e}")
        parts.append(
            "SATELLITE DATA — SENTINEL-2 STATUS\n"
            "Satellite API unavailable. Consult SA Health directly for latest conditions."
        )

    return "\n\n".join(parts)
