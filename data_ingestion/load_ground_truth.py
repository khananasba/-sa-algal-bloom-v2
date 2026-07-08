import csv
import re
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection, adapt_sql, ph
from datetime import datetime
from collections import defaultdict

# ── File paths ────────────────────────────────────────────────────────────────
# Site registry with GPS coords (SiteName, Latitude, Longitude)
SITES_CSV = 'data_ingestion/sa_bloom_data.csv'
# Old bloom readings (Site_Description, Date_Sample_Collected, Result_Name, Result_Label)
OLD_READINGS_CSV = 'data_ingestion/old_sa_bloom_data.csv'
# New comprehensive CSV downloaded from SA Gov HAB monitoring
NEW_READINGS_CSV = 'data/HarmfulAlgalBloom_MonitoringSites_6667060387850926547.csv'

# Only ingest readings from this date onwards
CUTOFF = datetime(2025, 6, 1)

# Result_Name values we care about (in priority order for safety)
# We ingest ALL of these and keep the highest-risk reading per site
PRIORITY_RESULTS = [
    'Algae - Total',
    'Blue Green Algae - Total',
    'Green Algae - Total',
    'Toxin producing BGA - Total',
    'Geosmin-MIB producing BGA - Total',
    'Diatoms - Total',
]

# Individual dangerous species we also track
DANGEROUS_SPECIES = [
    'karenia',
    'cylindrospermopsis',
    'nodularia',
    'microcystis',
    'dolichospermum',
    'aphanizomenon',
    'raphidiopsis',
]


def build_coords_from_sites(sites_csv: str) -> dict:
    """
    Build site-name -> (lat, lon) lookup from the SA Gov site registry CSV.

    Args:
        sites_csv: Path to sa_bloom_data.csv (columns: SiteName, Latitude, Longitude).

    Returns:
        Dict mapping site name strings to (lat, lon) float tuples.
    """
    coords = {}
    try:
        with open(sites_csv, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                name = row.get('SiteName', '').strip()
                try:
                    lat = float(row['Latitude'])
                    lon = float(row['Longitude'])
                    if name:
                        coords[name] = (lat, lon)
                except (ValueError, KeyError):
                    continue
        print(f'Loaded {len(coords)} site coordinates from {sites_csv}')
    except FileNotFoundError:
        print(f'WARNING: {sites_csv} not found — no GPS coords available')
    return coords


def find_coords(site_name: str, coords: dict) -> tuple | None:
    """
    Match a site name against the coords dict using exact then partial match.

    Args:
        site_name: Site name from the readings CSV.
        coords:    Dict of site_name -> (lat, lon).

    Returns:
        (lat, lon) tuple or None if no match found.
    """
    if site_name in coords:
        return coords[site_name]
    name_lower = site_name.lower()
    for key, latlon in coords.items():
        if key.lower() in name_lower or name_lower in key.lower():
            return latlon
    return None


def parse_cell_count(label: str) -> int:
    """
    Extract a cell count integer from a Result_Label text value.

    Handles formats like:
        "1,100 Cells/L"    -> 1100
        "6,000 Cells/L"    -> 6000
        "1,610,000 Cells/L" -> 1610000
        "804,000,000 Cells/L" -> 804000000
        "50 Cells/L"        -> 50
        "Not detected"      -> 0
        "Potentially Detected" -> 0
        "Detected"          -> 0
        "Abundant"          -> 0

    Args:
        label: Raw text from the Result_Label column.

    Returns:
        Integer cell count, or 0 if not a numeric reading.
    """
    if not label or not label.strip():
        return 0
    if 'cells/l' not in label.lower():
        return 0
    # Strip commas from numbers then extract digits
    digits = re.sub(r',', '', label)
    match = re.search(r'(\d+)', digits)
    return int(match.group(1)) if match else 0


def parse_date(date_str: str) -> datetime | None:
    """
    Parse a date string in D/MM/YYYY or YYYY-MM-DD format to a datetime.

    Args:
        date_str: Raw date string from the CSV.

    Returns:
        datetime object or None if parsing fails.
    """
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def is_relevant_result(result_name: str) -> bool:
    """Check if a Result_Name is one we want to ingest."""
    if not result_name:
        return False
    # Check totals
    if result_name in PRIORITY_RESULTS:
        return True
    # Check dangerous individual species
    rn_lower = result_name.lower()
    for species in DANGEROUS_SPECIES:
        if species in rn_lower:
            return True
    return False


def get_severity(cell_count: int) -> str:
    """Assign severity based on cell count thresholds."""
    if cell_count >= 50000:
        return 'Critical'
    elif cell_count >= 10000:
        return 'High'
    elif cell_count >= 1000:
        return 'Medium'
    else:
        return 'Low'


def process_csv(csv_path: str, coords: dict, label: str) -> dict:
    """
    Process a single CSV file and return a dict of site -> best reading.

    Args:
        csv_path:  Path to the CSV file.
        coords:    Site name -> (lat, lon) mapping.
        label:     Human label for logging (e.g., 'old CSV', 'new CSV').

    Returns:
        Dict of site_name -> {dt, val, result_name, source} for the
        highest-risk latest reading per site.
    """
    print(f'\nProcessing {label}: {csv_path}')

    try:
        with open(csv_path, encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        print(f'  WARNING: {csv_path} not found — skipping')
        return {}

    print(f'  Total rows in CSV: {len(rows)}')

    # Collect relevant readings
    relevant = []
    for r in rows:
        result_name = r.get('Result_Name', '')
        if not is_relevant_result(result_name):
            continue
        dt = parse_date(r.get('Date_Sample_Collected', ''))
        if dt is None or dt < CUTOFF:
            continue
        cell_count = parse_cell_count(r.get('Result_Label', ''))
        if cell_count <= 0:
            continue
        r['_dt'] = dt
        r['_cell_count'] = cell_count
        r['_result_name'] = result_name
        relevant.append(r)

    print(f'  Relevant readings from {CUTOFF.date()} onwards: {len(relevant)}')

    # Keep the highest cell count per site (across all dates and result types)
    # This gives stakeholders the most cautious safety view
    best: dict = {}
    for r in relevant:
        site = r.get('Site_Description', '').strip()
        if not site:
            continue
        val = r['_cell_count']
        dt = r['_dt']
        result_name = r['_result_name']

        existing = best.get(site)
        if existing is None:
            best[site] = {
                'dt': dt, 'val': val,
                'result_name': result_name, 'source': label,
            }
        else:
            # Prefer higher cell count, or more recent date if tied
            if val > existing['val'] or (val == existing['val'] and dt > existing['dt']):
                best[site] = {
                    'dt': dt, 'val': val,
                    'result_name': result_name, 'source': label,
                }

    print(f'  Unique sites with data: {len(best)}')
    return best


def run() -> None:
    """
    Load SA Gov algal bloom readings from both old and new CSVs into KareniaReadings.

    Processes ALL relevant algal species (not just Karenia) for comprehensive
    dashboard coverage. Keeps the highest-risk reading per site.
    """
    coords = build_coords_from_sites(SITES_CSV)

    print(f'Filtering to readings from {CUTOFF.date()} onwards...')
    print(f'Tracking {len(PRIORITY_RESULTS)} total categories + '
          f'{len(DANGEROUS_SPECIES)} dangerous species')

    # Process both CSVs
    old_data = process_csv(OLD_READINGS_CSV, coords, 'SA_Gov_Old_CSV')
    new_data = process_csv(NEW_READINGS_CSV, coords, 'SA_Gov_New_CSV')

    # Merge: new data takes priority, but keep old data for sites not in new
    merged = {}
    merged.update(old_data)
    for site, data in new_data.items():
        existing = merged.get(site)
        if existing is None or data['val'] > existing['val']:
            merged[site] = data

    print(f'\nMerged unique sites: {len(merged)}')

    # Insert into database
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM KareniaReadings')

    inserted = 0
    skipped = 0
    for site, data in merged.items():
        coord = find_coords(site, coords)
        if coord is None:
            skipped += 1
            continue
        lat, lon = coord
        val = data['val']
        dt = data['dt']
        sev = get_severity(val)
        source = f"{data['source']}|{data['result_name']}"
        cur.execute(
            f'INSERT INTO KareniaReadings'
            f'(recorded_at,beach_name,latitude,longitude,cell_count_per_litre,severity,source)'
            f' VALUES({ph(7)})',
            (dt, site, lat, lon, val, sev, source),
        )
        inserted += 1

    conn.commit()
    conn.close()
    print(f'\nInserted: {inserted} readings')
    print(f'Skipped (no coords): {skipped}')

    # Summary query
    conn2 = get_connection()
    cur2 = conn2.cursor()
    cur2.execute(
        'SELECT severity, COUNT(*) FROM KareniaReadings'
        ' GROUP BY severity ORDER BY COUNT(*) DESC'
    )
    print('\nSeverity breakdown:')
    for r in cur2.fetchall():
        print(f'  {r[0]}: {r[1]}')
    cur2.execute(adapt_sql(
        'SELECT TOP 10 beach_name, cell_count_per_litre, severity, recorded_at'
        ' FROM KareniaReadings ORDER BY cell_count_per_litre DESC'
    ))
    print('\nTop 10 readings:')
    for r in cur2.fetchall():
        print(f'  {r[0]}: {r[1]:,} cells/L — {r[2]} — {str(r[3])[:10]}')
    conn2.close()
    print('\nGround Truth layer updated with comprehensive algal bloom data.')


if __name__ == '__main__':
    run()
