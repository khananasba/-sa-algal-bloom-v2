import numpy as np
import json
import os
from datetime import datetime, timedelta

os.makedirs("data/forecasts", exist_ok=True)

class BloomTracker:

    def __init__(self, center_lat=-34.9, center_lon=138.55, radius_deg=0.3):
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.radius_deg = radius_deg
        self.particles  = None
        self.load_currents()
        self.load_weather()

    def load_currents(self):
        path = "data/ocean/currents.json"
        with open(path) as f:
            data = json.load(f)
        self.lats      = np.array(data["lats"])
        self.lons      = np.array(data["lons"])
        self.U         = np.array(data["U"])
        self.V         = np.array(data["V"])
        self.time_steps = data["metadata"]["time_steps"]
        print(f"  Loaded ocean currents: {self.U.shape}")

    def load_weather(self):
        path = "data/satellite/bands_latest.npz"
        # Use simple wind estimate from Open-Meteo data shape
        # In real system this reads from WeatherReadings table
        self.wind_speed_ms  = 6.2   # ~22 km/h typical SA sea breeze
        self.wind_dir_deg   = 195.0 # southwesterly
        print(f"  Wind: {self.wind_speed_ms} m/s @ {self.wind_dir_deg}°")

    def seed_particles(self, n=800):
        """Seed particles inside bloom polygon (circle around Adelaide coast)"""
        angles   = np.random.uniform(0, 2 * np.pi, n)
        radii    = np.random.uniform(0, self.radius_deg, n)
        lats     = self.center_lat + radii * np.sin(angles)
        lons     = self.center_lon + radii * np.cos(angles) * 1.3
        self.particles = np.column_stack([lats, lons])
        print(f"  Seeded {n} particles around ({self.center_lat}, {self.center_lon})")
        return self.particles

    def get_current_velocity(self, lat, lon, time_idx):
        """Interpolate U/V from ocean current grid"""
        t = min(int(time_idx), self.time_steps - 1)
        i = int(np.argmin(np.abs(self.lats - lat)))
        j = int(np.argmin(np.abs(self.lons - lon)))
        i = max(0, min(i, self.U.shape[1] - 1))
        j = max(0, min(j, self.U.shape[2] - 1))
        return float(self.U[t, i, j]), float(self.V[t, i, j])

    def get_wind_drift(self, hour):
        """3% Stokes drift — algae move at 3% of wind speed"""
        drift_speed = self.wind_speed_ms * 0.03
        dir_rad     = np.radians(self.wind_dir_deg)
        u_wind      = drift_speed * np.sin(dir_rad)
        v_wind      = drift_speed * np.cos(dir_rad)
        return u_wind, v_wind

    def diurnal_factor(self, hour):
        """Algae swim up during day, down at night"""
        hour_of_day = hour % 24
        if 6 <= hour_of_day <= 18:
            return 1.3   # daytime — surface currents stronger
        return 0.7       # night — deeper, slower

    def degrees_per_ms(self) -> float:
        """Convert m/s to degrees lat/lon per hour."""
        return 3600 / 111000  # ~0.0324 deg per m/s per hour

    @staticmethod
    def is_on_land(lat: float, lon: float) -> bool:
        """
        Return True if the given coordinate is clearly on land in SA.

        Uses three simple rectangular rules derived from the SA coastline
        geometry.  These are intentionally conservative — they only flag
        positions that are unambiguously inland so that valid nearshore
        ocean cells are never incorrectly blocked.

        Args:
            lat: Latitude in decimal degrees (negative = south).
            lon: Longitude in decimal degrees.

        Returns:
            True if the position is on land; False if it is in the ocean.
        """
        # Fleurieu Peninsula — land east of 138.75°E below -35.5
        if -35.9 < lat < -35.5 and lon > 138.75:
            return True
        # Strict inland east (Mt Lofty Ranges and beyond)
        if -35.5 < lat < -34.5 and lon > 138.8:
            return True
        # Yorke Peninsula narrow land strip
        if -35.0 < lat < -34.0 and 137.9 < lon < 138.1:
            return True
        return False

    def simulate(self, hours=72, timestep=1):
        """Run the full particle simulation"""
        snapshots    = {}
        deg_per_ms   = self.degrees_per_ms()
        particles    = self.particles.copy()
        np.random.seed(7)

        save_at = {0, 6, 12, 24, 48, 72}

        for h in range(0, hours + 1, timestep):
            if h in save_at:
                snapshots[h] = particles.copy()

            if h == hours:
                break

            diurnal = self.diurnal_factor(h)
            u_wind, v_wind = self.get_wind_drift(h)

            new_particles = []
            for lat, lon in particles:
                u_curr, v_curr = self.get_current_velocity(lat, lon, h)

                # Total displacement in degrees
                d_lon = (u_curr * diurnal + u_wind) * deg_per_ms
                d_lat = (v_curr * diurnal + v_wind) * deg_per_ms

                # Add random turbulent diffusion (std halved to 0.0015 so
                # particles spread realistically along the coast, not inland)
                d_lat += np.random.normal(0, 0.0015)
                d_lon += np.random.normal(0, 0.0015)

                new_lat = lat + d_lat
                new_lon = lon + d_lon

                # Keep particles in SA bounding box
                new_lat = np.clip(new_lat, -37.0, -32.0)
                new_lon = np.clip(new_lon, 135.0, 141.0)

                # Land-mask guard: if the proposed position is on land,
                # keep the particle at its previous valid ocean position.
                if BloomTracker.is_on_land(new_lat, new_lon):
                    new_lat, new_lon = lat, lon

                new_particles.append([new_lat, new_lon])

            particles = np.array(new_particles)

        return snapshots

    def to_geojson(self, snapshots, severity="High"):
        """Convert snapshots to GeoJSON FeatureCollection per hour"""
        result = {}
        for hour, positions in snapshots.items():
            features = []
            for lat, lon in positions:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [round(float(lon), 5),
                                        round(float(lat), 5)]
                    },
                    "properties": {
                        "hour":     hour,
                        "severity": severity
                    }
                })
            result[str(hour)] = {
                "type":     "FeatureCollection",
                "features": features
            }
        return result

    def check_zone_intersections(self, snapshots):
        """Check if bloom reaches critical zones"""
        ZONES = [
            {"name": "Adelaide metro beaches",
             "lat_min": -35.05, "lat_max": -34.80,
             "lon_min": 138.45, "lon_max": 138.56},
            {"name": "Port Lincoln tuna farm",
             "lat_min": -34.80, "lat_max": -34.60,
             "lon_min": 135.80, "lon_max": 135.98},
            {"name": "Goolwa desalination zone",
             "lat_min": -35.60, "lat_max": -35.45,
             "lon_min": 138.75, "lon_max": 138.92},
        ]

        alerts = []
        for hour in sorted(snapshots.keys()):
            positions = snapshots[hour]
            for zone in ZONES:
                in_zone = np.sum(
                    (positions[:, 0] >= zone["lat_min"]) &
                    (positions[:, 0] <= zone["lat_max"]) &
                    (positions[:, 1] >= zone["lon_min"]) &
                    (positions[:, 1] <= zone["lon_max"])
                )
                if in_zone >= 20:
                    already = any(
                        a["zone"] == zone["name"] for a in alerts
                    )
                    if not already:
                        alerts.append({
                            "zone":     zone["name"],
                            "hour":     hour,
                            "particles": int(in_zone)
                        })
        return alerts


def run():
    print("=== Running 72-Hour Bloom Particle Tracker ===\n")
    np.random.seed(42)

    print("Initialising tracker...")
    tracker = BloomTracker(
        center_lat=-34.92,
        center_lon=138.52,
        radius_deg=0.25
    )

    print("\nSeeding bloom particles...")
    tracker.seed_particles(n=800)

    print("\nRunning 72-hour simulation...")
    snapshots = tracker.simulate(hours=72, timestep=1)

    print("\nParticle positions at each snapshot:")
    for hour, positions in sorted(snapshots.items()):
        center_lat = positions[:, 0].mean()
        center_lon = positions[:, 1].mean()
        spread     = positions[:, 0].std()
        print(f"  T+{hour:2d}h: centre=({center_lat:.3f}, {center_lon:.3f})  spread={spread:.3f}°")

    print("\nChecking critical zone intersections...")
    alerts = tracker.check_zone_intersections(snapshots)
    if alerts:
        for a in alerts:
            print(f"  ALERT: {a['zone']} reached at T+{a['hour']}h ({a['particles']} particles)")
    else:
        print("  No critical zones reached in 72 hours")

    print("\nConverting to GeoJSON...")
    geojson = tracker.to_geojson(snapshots, severity="High")

    out = {
        "generated_at": datetime.now().isoformat(),
        "snapshots":    geojson,
        "alerts":       alerts
    }
    path = "data/forecasts/forecast_latest.json"
    with open(path, "w") as f:
        json.dump(out, f)
    print(f"Saved {path}")

    print("\n=== Particle Tracker DONE ===")
    print("Ready for Step 9 — FastAPI Backend")

if __name__ == "__main__":
    run()
