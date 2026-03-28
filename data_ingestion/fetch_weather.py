import requests
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection, ph
from datetime import datetime, timedelta

# SA coastal locations
LOCATIONS = [
    {"name": "Adelaide",        "lat": -34.9, "lon": 138.6},
    {"name": "Port Lincoln",    "lat": -34.7, "lon": 135.9},
    {"name": "Victor Harbor",   "lat": -35.6, "lon": 138.6},
    {"name": "Whyalla",         "lat": -33.0, "lon": 137.6},
    {"name": "Kangaroo Island", "lat": -35.8, "lon": 137.1},
]


def fetch_weather_for_location(location):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":  location["lat"],
        "longitude": location["lon"],
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,shortwave_radiation,wave_height",
        "daily":  "temperature_2m_max,wind_speed_10m_max",
        "past_days": 7,
        "forecast_days": 1,
        "timezone": "Australia/Adelaide"
    }
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()

def save_to_db(location, data):
    conn = get_connection()
    cursor = conn.cursor()

    hourly = data.get("hourly", {})
    times        = hourly.get("time", [])
    wind_speed   = hourly.get("wind_speed_10m", [])
    wind_dir     = hourly.get("wind_direction_10m", [])
    solar        = hourly.get("shortwave_radiation", [])
    wave         = hourly.get("wave_height", [])
    temp         = hourly.get("temperature_2m", [])

    count = 0
    for i, t in enumerate(times):
        try:
            recorded_at = datetime.strptime(t, "%Y-%m-%dT%H:%M")
            cursor.execute(f"""
                INSERT INTO WeatherReadings
                    (recorded_at, location_name, latitude, longitude,
                     wind_speed, wind_direction, sea_surface_temp,
                     solar_radiation, wave_height)
                VALUES ({ph(9)})
            """,
                recorded_at,
                location["name"],
                location["lat"],
                location["lon"],
                wind_speed[i] if i < len(wind_speed) else None,
                wind_dir[i]   if i < len(wind_dir)   else None,
                temp[i]       if i < len(temp)        else None,
                solar[i]      if i < len(solar)       else None,
                wave[i]       if i < len(wave)        else None,
            )
            count += 1
        except Exception as e:
            continue

    conn.commit()
    conn.close()
    return count

def run():
    print("=== Fetching SA Coastal Weather Data ===\n")
    total = 0
    for loc in LOCATIONS:
        try:
            print(f"Fetching {loc['name']}...")
            data  = fetch_weather_for_location(loc)
            count = save_to_db(loc, data)
            print(f"  Saved {count} rows")
            total += count
        except Exception as e:
            print(f"  ERROR for {loc['name']}: {e}")

    print(f"\nTotal rows inserted: {total}")
    print("WeatherReadings table populated OK")

if __name__ == "__main__":
    run()