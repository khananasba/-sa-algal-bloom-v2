"""
cron_trigger.py — Called by the Render Cron Job service.

Wakes the web service (handles cold start) then triggers the data refresh.
Requires environment variable: REFRESH_KEY
"""

import os
import sys
import time

import requests

API_BASE    = "https://sa-algal-bloom.onrender.com/api"
REFRESH_KEY = os.environ.get("REFRESH_KEY", "")
WAKE_TRIES  = 5
WAKE_DELAY  = 15   # seconds between wake attempts
HTTP_TIMEOUT = 300  # seconds for the actual refresh call


def wake_service():
    """Ping /api/health until the service responds (handles Render cold start)."""
    print("Waking up web service...")
    for attempt in range(1, WAKE_TRIES + 1):
        try:
            r = requests.get(f"{API_BASE}/health", timeout=30)
            if r.status_code == 200:
                print(f"  Service awake after {attempt} attempt(s): {r.json()}")
                return True
        except Exception as e:
            print(f"  Attempt {attempt}/{WAKE_TRIES}: {e}")
        if attempt < WAKE_TRIES:
            time.sleep(WAKE_DELAY)
    print("  Service did not wake in time.")
    return False


def trigger_refresh():
    """POST /api/refresh with the refresh key."""
    print("Triggering data refresh...")
    r = requests.post(
        f"{API_BASE}/refresh",
        headers={"X-Refresh-Key": REFRESH_KEY},
        timeout=HTTP_TIMEOUT,
    )
    print(f"  HTTP {r.status_code}")
    try:
        data = r.json()
        ok   = data.get("ok", 0)
        fail = data.get("fail", 0)
        skip = data.get("skip", 0)
        print(f"  Result: {ok} OK  {fail} FAIL  {skip} SKIP")
        for src, info in data.get("sources", {}).items():
            tag = info.get("status", "?")
            msg = info.get("message", "")
            print(f"  [{tag}] {src}: {msg}")
    except Exception:
        print(f"  Response: {r.text[:500]}")
    return r.status_code == 200


if __name__ == "__main__":
    if not REFRESH_KEY:
        print("ERROR: REFRESH_KEY environment variable is not set")
        sys.exit(1)

    awake = wake_service()
    if not awake:
        print("WARNING: proceeding with refresh attempt anyway...")

    success = trigger_refresh()
    sys.exit(0 if success else 1)
