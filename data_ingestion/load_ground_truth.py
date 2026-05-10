import csv
import re
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection, adapt_sql, ph
from datetime import datetime
from collections import defaultdict

# Site registry with GPS coords (SiteName, Latitude, Longitude)
SITES_CSV = 'data_ingestion/sa_bloom_data.csv'
# Bloom readings (Site_Description, Date_Sample_Collected, Result_Name, Result_Label)
READINGS_CSV = 'data_ingestion/old_sa_bloom_data.csv'
CUTOFF = datetime(2025, 9, 1)


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
        "50 Cells/L"        -> 50
        "Not detected"      -> 0
        "Potentially Detected" -> 0
        "Detected"          -> 0

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


def run() -> None:
    """
    Load SA Gov Karenia bloom readings into the KareniaReadings DB table.

    - GPS coordinates sourced from sa_bloom_data.csv (site registry).
    - Bloom readings sourced from old_sa_bloom_data.csv (readings export).
    - Filters to rows where Result_Name contains 'Karenia' (case insensitive).
    - Filters to readings from 2025-09-01 onwards.
    - Keeps only the latest reading per site before inserting.
    """
    coords = build_coords_from_sites(SITES_CSV)

    print(f'Reading bloom readings from {READINGS_CSV}')
    print(f'Filtering to Karenia readings from {CUTOFF.date()} onwards...')

    try:
        with open(READINGS_CSV, encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        print(f'ERROR: Readings file not found: {READINGS_CSV}')
        return

    print(f'Total rows in CSV: {len(rows)}')

    # Filter: Karenia species + date >= CUTOFF + has a cell count
    karenia = []
    for r in rows:
        result_name = r.get('Result_Name', '')
        if 'karenia' not in result_name.lower():
            continue
        dt = parse_date(r.get('Date_Sample_Collected', ''))
        if dt is None or dt < CUTOFF:
            continue
        cell_count = parse_cell_count(r.get('Result_Label', ''))
        if cell_count <= 0:
            continue
        r['_dt'] = dt
        r['_cell_count'] = cell_count
        karenia.append(r)

    print(f'Karenia readings from {CUTOFF.date()} onwards with cell count > 0: {len(karenia)}')

    # Keep only the latest reading per site
    latest: dict = defaultdict(lambda: {'dt': datetime(2000, 1, 1), 'val': 0})
    for r in karenia:
        site = r['Site_Description'].strip()
        if r['_dt'] > latest[site]['dt']:
            latest[site] = {'dt': r['_dt'], 'val': r['_cell_count']}

    print(f'Unique sites with recent Karenia data: {len(latest)}')

    conn = get_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM KareniaReadings')

    inserted = 0
    skipped = 0
    for site, data in latest.items():
        coord = find_coords(site, coords)
        if coord is None:
            print(f'  SKIP (no coords): {site}')
            skipped += 1
            continue
        lat, lon = coord
        val = data['val']
        dt = data['dt']
        if val >= 50000:
            sev = 'Critical'
        elif val >= 10000:
            sev = 'High'
        elif val >= 1000:
            sev = 'Medium'
        else:
            sev = 'Low'
        cur.execute(
            f'INSERT INTO KareniaReadings'
            f'(recorded_at,beach_name,latitude,longitude,cell_count_per_litre,severity,source)'
            f' VALUES({ph(7)})',
            (dt, site, lat, lon, val, sev, 'SA_Gov_CSV'),
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
    print('\nGround Truth layer updated. Other layers not affected.')


if __name__ == '__main__':
    run()
