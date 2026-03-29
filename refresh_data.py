"""
refresh_data.py — SA Algal Bloom Monitor automated data refresh

Runs all 7 data scripts in order with:
  - CSV hash-based change detection for ground_truth
  - File backup/restore so a bad run never overwrites good data
  - GeoJSON/JSON validation before accepting new output
  - refresh_log.json persistence (per-source status + timestamps)
  - Never crashes even if all 7 scripts fail

Usage:
    python refresh_data.py              # run standalone
    from refresh_data import run_refresh  # called by api/main.py
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))


# ── Path helpers ───────────────────────────────────────────────────────────────
def rp(*parts):
    return os.path.join(ROOT, *parts)


CSV_PATH      = rp("data_ingestion", "sa_bloom_data.csv")
LOG_PATH      = rp("data", "refresh_log.json")
HEATMAP_PATH  = rp("data", "indices",   "bloom_heatmap_latest.geojson")
FORECAST_PATH = rp("data", "forecasts", "forecast_latest.json")
SAFETY_PATH   = rp("data", "beach_safety_scores.json")
CURRENTS_PATH = rp("data", "ocean",     "currents.json")


# ── Refresh log ────────────────────────────────────────────────────────────────
def _load_log():
    try:
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"last_refresh_attempt": None, "sources": {}}


def _save_log(log):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        print(f"  [WARN] could not save refresh log: {e}")


# ── CSV hash (change detection) ────────────────────────────────────────────────
def _csv_hash():
    try:
        with open(CSV_PATH, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return None


def _stored_csv_hash(log):
    return log.get("sources", {}).get("ground_truth", {}).get("csv_hash")


# ── File backup / restore ──────────────────────────────────────────────────────
def _backup(path):
    try:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
    except Exception:
        pass
    return None


def _restore(path, data):
    if data is None:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        print(f"  [RESTORE] kept previous {os.path.basename(path)}")
    except Exception as e:
        print(f"  [WARN] could not restore {path}: {e}")


# ── Validators ─────────────────────────────────────────────────────────────────
def _valid_geojson(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return (d.get("type") == "FeatureCollection"
                and len(d.get("features", [])) >= 1)
    except Exception:
        return False


def _valid_forecast(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        snaps = d.get("snapshots", {})
        return bool(snaps) and any(
            len(v.get("features", [])) > 0 for v in snaps.values()
        )
    except Exception:
        return False


def _valid_json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return bool(d)
    except Exception:
        return False


# ── Script runner ──────────────────────────────────────────────────────────────
def _run(script_rel, timeout=120):
    """Run a script via subprocess with project root as CWD.
    Returns (returncode, combined_output_string).
    """
    result = subprocess.run(
        [sys.executable, rp(script_rel)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=timeout,
    )
    return result.returncode, result.stdout + result.stderr


# ── DB helpers (for display in log messages) ───────────────────────────────────
def _db_karenia_stats():
    """Return (count, latest_date_str) from KareniaReadings, or (0, 'unknown')."""
    try:
        sys.path.insert(0, ROOT)
        from db_config import get_connection  # noqa: PLC0415
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*), MAX(recorded_at) FROM KareniaReadings")
        row  = cur.fetchone()
        conn.close()
        count = row[0] or 0
        date  = str(row[1])[:10] if row[1] else "unknown"
        return count, date
    except Exception:
        return 0, "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN REFRESH FUNCTION
# ══════════════════════════════════════════════════════════════════════════════
def run_refresh():
    """
    Run all 7 data scripts in order.
    Returns a dict suitable for a JSON API response.
    Never raises — all errors are caught and logged.
    """
    now     = datetime.now().isoformat()
    log     = _load_log()
    sources = log.setdefault("sources", {})
    log["last_refresh_attempt"] = now

    summary       = {}        # returned to caller
    satellite_ok  = False     # gate for bloom_map (step 5)

    print(f"\n{'='*62}")
    print(f"  SA Algal Bloom — Data Refresh   {now}")
    print(f"{'='*62}\n")

    # ── 1. fetch_weather ──────────────────────────────────────────────────────
    try:
        rc, out = _run("data_ingestion/fetch_weather.py", timeout=90)
        if rc != 0:
            raise RuntimeError(out[-400:])
        rows = 0
        for line in out.splitlines():
            if "Total rows inserted:" in line:
                try:
                    rows = int(line.split(":")[-1].strip())
                except ValueError:
                    pass
        msg = f"5 locations, {rows} rows"
        sources["weather"] = {"status": "OK", "last_success": now, "message": msg, "rows": rows}
        summary["weather"] = {"status": "OK", "message": msg}
        print(f"[OK]   weather          - {msg}")
    except Exception as e:
        msg = str(e)[:200]
        sources.setdefault("weather", {}).update({"status": "FAIL", "message": msg})
        summary["weather"] = {"status": "FAIL", "message": msg}
        print(f"[FAIL] weather          - {msg}")

    # ── 2. load_ground_truth (CSV hash change detection) ─────────────────────
    try:
        current_hash = _csv_hash()
        stored_hash  = _stored_csv_hash(log)

        if not os.path.exists(CSV_PATH):
            count, last = _db_karenia_stats()
            msg = f"CSV missing, keeping {count} readings from {last}"
            sources.setdefault("ground_truth", {}).update({"status": "SKIP", "message": msg})
            summary["ground_truth"] = {"status": "SKIP", "message": msg}
            print(f"[SKIP] ground_truth     - {msg}")

        elif current_hash == stored_hash:
            count = sources.get("ground_truth", {}).get("rows") or 0
            last  = sources.get("ground_truth", {}).get("last_date") or "unknown"
            if not count or last == "unknown":
                count, last = _db_karenia_stats()
            msg = f"CSV unchanged, keeping {count} readings from {last}"
            sources.setdefault("ground_truth", {}).update({"status": "SKIP", "message": msg})
            summary["ground_truth"] = {"status": "SKIP", "message": msg}
            print(f"[SKIP] ground_truth     - {msg}")

        else:
            rc, out = _run("data_ingestion/load_ground_truth.py", timeout=60)
            if rc != 0:
                raise RuntimeError(out[-400:])
            rows = 0
            for line in out.splitlines():
                if "Inserted:" in line:
                    try:
                        rows = int(line.split(":")[-1].strip())
                    except ValueError:
                        pass
            last_date = datetime.now().strftime("%Y-%m-%d")
            msg = f"new CSV detected, inserted {rows} readings"
            sources["ground_truth"] = {
                "status":       "OK",
                "last_success": now,
                "message":      msg,
                "rows":         rows,
                "csv_hash":     current_hash,
                "last_date":    last_date,
            }
            summary["ground_truth"] = {"status": "OK", "message": msg}
            print(f"[OK]   ground_truth     - {msg}")

    except Exception as e:
        count, last = _db_karenia_stats()
        msg = f"error loading CSV, keeping {count} readings from {last}"
        sources.setdefault("ground_truth", {}).update({"status": "FAIL", "message": msg})
        summary["ground_truth"] = {"status": "FAIL", "message": msg}
        print(f"[FAIL] ground_truth     - {msg}")

    # ── 3. fetch_satellite (GEE — expected to fail on Render) ─────────────────
    heatmap_backup = _backup(HEATMAP_PATH)
    try:
        rc, out = _run("data_ingestion/fetch_satellite.py", timeout=180)
        if rc == 0 and _valid_geojson(HEATMAP_PATH):
            satellite_ok = True
            try:
                with open(HEATMAP_PATH, encoding="utf-8") as f:
                    feats = len(json.load(f).get("features", []))
            except Exception:
                feats = 0
            msg = f"{feats} GEE pixels written"
            sources["satellite"] = {"status": "OK", "last_success": now, "message": msg}
            summary["satellite"] = {"status": "OK", "message": msg}
            print(f"[OK]   satellite        - {msg}")
        else:
            raise RuntimeError("GEE returned no valid features")
    except Exception as e:
        _restore(HEATMAP_PATH, heatmap_backup)
        prev = (sources.get("satellite", {}).get("last_success") or "")[:10] or "unknown"
        msg  = f"GEE auth error, keeping heatmap from {prev}"
        sources.setdefault("satellite", {}).update({"status": "FAIL", "message": msg})
        summary["satellite"] = {"status": "FAIL", "message": msg}
        print(f"[FAIL] satellite        - {msg}")

    # ── 4. fetch_ocean_currents ────────────────────────────────────────────────
    currents_backup = _backup(CURRENTS_PATH)
    try:
        rc, out = _run("data_ingestion/fetch_ocean_currents.py", timeout=60)
        if rc != 0:
            raise RuntimeError(out[-400:])
        if not os.path.exists(CURRENTS_PATH):
            raise RuntimeError("currents.json not written")
        msg = "current grid updated"
        sources["ocean_currents"] = {"status": "OK", "last_success": now, "message": msg}
        summary["ocean_currents"] = {"status": "OK", "message": msg}
        print(f"[OK]   ocean_currents   - {msg}")
    except Exception as e:
        _restore(CURRENTS_PATH, currents_backup)
        msg = str(e)[:200]
        sources.setdefault("ocean_currents", {}).update({"status": "FAIL", "message": msg})
        summary["ocean_currents"] = {"status": "FAIL", "message": msg}
        print(f"[FAIL] ocean_currents   - {msg}")

    # ── 5. coastal_bloom_map (only if satellite succeeded) ────────────────────
    if satellite_ok:
        bloom_backup = _backup(HEATMAP_PATH)
        try:
            rc, out = _run("data_ingestion/coastal_bloom_map.py", timeout=60)
            if rc == 0 and _valid_geojson(HEATMAP_PATH):
                try:
                    with open(HEATMAP_PATH, encoding="utf-8") as f:
                        feats = len(json.load(f).get("features", []))
                except Exception:
                    feats = 0
                msg = f"{feats} coastal points interpolated"
                sources["bloom_map"] = {"status": "OK", "last_success": now, "message": msg}
                summary["bloom_map"] = {"status": "OK", "message": msg}
                print(f"[OK]   bloom_map       - {msg}")
            else:
                raise RuntimeError(out[-300:])
        except Exception as e:
            _restore(HEATMAP_PATH, bloom_backup)
            msg = str(e)[:200]
            sources.setdefault("bloom_map", {}).update({"status": "FAIL", "message": msg})
            summary["bloom_map"] = {"status": "FAIL", "message": msg}
            print(f"[FAIL] bloom_map       - {msg}")
    else:
        msg = "skipped because satellite failed, keeping old heatmap"
        sources.setdefault("bloom_map", {}).update({"status": "SKIP", "message": msg})
        summary["bloom_map"] = {"status": "SKIP", "message": msg}
        print(f"[SKIP] bloom_map       - {msg}")

    # ── 6. beach_safety_score ─────────────────────────────────────────────────
    safety_backup = _backup(SAFETY_PATH)
    try:
        rc, out = _run("ml_engine/beach_safety_score.py", timeout=90)
        if rc != 0:
            raise RuntimeError(out[-400:])
        if not _valid_json_file(SAFETY_PATH):
            raise RuntimeError("empty or invalid safety scores file")
        with open(SAFETY_PATH, encoding="utf-8") as f:
            n = len(json.load(f).get("scores", []))
        if n == 0:
            raise RuntimeError("safety scores list is empty")
        msg = f"{n} beaches scored"
        sources["beach_safety"] = {"status": "OK", "last_success": now, "message": msg, "count": n}
        summary["beach_safety"] = {"status": "OK", "message": msg}
        print(f"[OK]   beach_safety     - {msg}")
    except Exception as e:
        _restore(SAFETY_PATH, safety_backup)
        msg = str(e)[:200]
        sources.setdefault("beach_safety", {}).update({"status": "FAIL", "message": msg})
        summary["beach_safety"] = {"status": "FAIL", "message": msg}
        print(f"[FAIL] beach_safety     - {msg}")

    # ── 7. particle_tracker (always run) ──────────────────────────────────────
    forecast_backup = _backup(FORECAST_PATH)
    try:
        rc, out = _run("ml_engine/particle_tracker.py", timeout=180)
        if rc != 0:
            raise RuntimeError(out[-400:])
        if not _valid_forecast(FORECAST_PATH):
            raise RuntimeError("forecast file is empty or invalid")
        msg = "800 particles, 72hr forecast ready"
        sources["particle_tracker"] = {"status": "OK", "last_success": now, "message": msg}
        summary["particle_tracker"] = {"status": "OK", "message": msg}
        print(f"[OK]   particle_tracker - {msg}")
    except Exception as e:
        _restore(FORECAST_PATH, forecast_backup)
        msg = str(e)[:200]
        sources.setdefault("particle_tracker", {}).update({"status": "FAIL", "message": msg})
        summary["particle_tracker"] = {"status": "FAIL", "message": msg}
        print(f"[FAIL] particle_tracker - {msg}")

    # ── Save log & print totals ────────────────────────────────────────────────
    _save_log(log)

    ok_n   = sum(1 for v in summary.values() if v["status"] == "OK")
    fail_n = sum(1 for v in summary.values() if v["status"] == "FAIL")
    skip_n = sum(1 for v in summary.values() if v["status"] == "SKIP")

    print(f"\n{'='*62}")
    print(f"  Refresh done: {ok_n} OK  {fail_n} FAIL  {skip_n} SKIP")
    print(f"{'='*62}\n")

    return {
        "refreshed_at": now,
        "ok":           ok_n,
        "fail":         fail_n,
        "skip":         skip_n,
        "sources":      summary,
    }


# ── CLI entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    result = run_refresh()
    sys.exit(0 if result["fail"] == 0 else 1)
