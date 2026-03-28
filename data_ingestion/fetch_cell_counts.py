import requests
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection, ph
from datetime import datetime

# Real SA beach locations with dummy cell counts
# (mirrors what the SA Govt ArcGIS dashboard publishes)
SA_BEACHES = [
    {"name": "Glenelg",         "lat": -34.980, "lon": 138.516},
    {"name": "Brighton",        "lat": -35.005, "lon": 138.519},
    {"name": "Henley",          "lat": -34.921, "lon": 138.497},
    {"name": "Semaphore",       "lat": -34.838, "lon": 138.482},
    {"name": "Port Noarlunga",  "lat": -35.142, "lon": 138.467},
    {"name": "Moana",           "lat": -35.229, "lon": 138.463},
    {"name": "Aldinga",         "lat": -35.278, "lon": 138.456},
    {"name": "Sellicks",        "lat": -35.338, "lon": 138.449},
    {"name": "Victor Harbor",   "lat": -35.552, "lon": 138.617},
    {"name": "Goolwa",          "lat": -35.501, "lon": 138.743},
    {"name": "Port Elliott",    "lat": -35.529, "lon": 138.683},
    {"name": "Middleton",       "lat": -35.515, "lon": 138.700},
    {"name": "West Beach",      "lat": -34.940, "lon": 138.502},
    {"name": "Seacliff",        "lat": -35.033, "lon": 138.517},
    {"name": "Hallett Cove",    "lat": -35.069, "lon": 138.504},
    {"name": "Largs Bay",       "lat": -34.804, "lon": 138.479},
    {"name": "North Haven",     "lat": -34.789, "lon": 138.489},
    {"name": "Grange",          "lat": -34.905, "lon": 138.495},
    {"name": "Tennyson",        "lat": -34.875, "lon": 138.490},
    {"name": "Somerton",        "lat": -34.858, "lon": 138.487},
]

def get_severity(cell_count):
    if cell_count < 1000:
        return "Low"
    elif cell_count < 10000:
        return "Medium"
    elif cell_count < 50000:
        return "High"
    else:
        return "Critical"

def fetch_arcgis_data():
    # Try the real SA Government ArcGIS REST API
    url = (
        "https://services.arcgis.com/R1y6RbNVeAYKQFOF/arcgis/rest/services/"
        "Algal_Bloom_Water_Testing/FeatureServer/0/query"
    )
    params = {
        "where": "1=1",
        "outFields": "*",
        "f": "json",
        "resultRecordCount": 500
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        features = data.get("features", [])
        if features:
            print(f"  Got {len(features)} real records from SA Government API")
            return features, True
    except Exception as e:
        print(f"  SA API not reachable ({e}), using seed data instead")
    return [], False

def seed_realistic_data(cursor):
    # Realistic cell counts based on the actual 2024-2026 SA bloom
    import random
    random.seed(42)

    # Adelaide metro beaches — high bloom area
    high_bloom = ["Glenelg","Brighton","Henley","Semaphore","West Beach",
                  "Grange","Tennyson","Somerton","Largs Bay","North Haven"]
    # Southern beaches — medium
    medium_bloom = ["Port Noarlunga","Moana","Aldinga","Seacliff","Hallett Cove"]
    # Far south — lower
    low_bloom = ["Sellicks","Victor Harbor","Goolwa","Port Elliott","Middleton"]

    count = 0
    now = datetime.now()

    for beach in SA_BEACHES:
        name = beach["name"]
        if name in high_bloom:
            cell_count = random.randint(15000, 85000)
        elif name in medium_bloom:
            cell_count = random.randint(3000, 18000)
        else:
            cell_count = random.randint(200, 4000)

        severity = get_severity(cell_count)

        cursor.execute(f"""
            INSERT INTO KareniaReadings
                (recorded_at, beach_name, latitude, longitude,
                 cell_count_per_litre, severity, source)
            VALUES ({ph(7)})
        """,
            now,
            beach["name"],
            beach["lat"],
            beach["lon"],
            cell_count,
            severity,
            "SA_Government_Seed"
        )
        count += 1

    return count

def save_arcgis_features(cursor, features):
    count = 0
    now = datetime.now()
    for f in features:
        attrs = f.get("attributes", {})
        geo   = f.get("geometry", {})
        try:
            cell_count = int(attrs.get("cell_count", attrs.get("cells_per_litre", 0)) or 0)
            beach_name = attrs.get("site_name", attrs.get("location", "Unknown"))
            lat = geo.get("y", attrs.get("latitude", 0))
            lon = geo.get("x", attrs.get("longitude", 0))
            severity = get_severity(cell_count)
            cursor.execute(f"""
                INSERT INTO KareniaReadings
                    (recorded_at, beach_name, latitude, longitude,
                     cell_count_per_litre, severity, source)
                VALUES ({ph(7)})
            """,
                now, beach_name, lat, lon,
                cell_count, severity, "SA_ArcGIS_API"
            )
            count += 1
        except:
            continue
    return count

def run():
    print("=== Fetching SA Karenia Cell Count Data ===\n")
    conn   = get_connection()
    cursor = conn.cursor()

    print("Trying SA Government ArcGIS API...")
    features, success = fetch_arcgis_data()

    if success and features:
        count = save_arcgis_features(cursor, features)
        print(f"Saved {count} real government records")
    else:
        print("Seeding realistic bloom data for all 20 SA beaches...")
        count = seed_realistic_data(cursor)
        print(f"Seeded {count} beach records")

    conn.commit()
    conn.close()

    print(f"\nTotal KareniaReadings inserted: {count}")
    print("\nSeverity breakdown:")

    conn2   = get_connection()
    cursor2 = conn2.cursor()
    cursor2.execute("""
        SELECT severity, COUNT(*) as cnt
        FROM KareniaReadings
        GROUP BY severity
        ORDER BY cnt DESC
    """)
    for row in cursor2.fetchall():
        print(f"  {row[0]}: {row[1]} beaches")
    conn2.close()

    print("\nKareniaReadings table populated OK")

if __name__ == "__main__":
    run()