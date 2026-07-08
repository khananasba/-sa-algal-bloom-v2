from db_config import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute("SELECT beach_name, cell_count_per_litre, severity, source, recorded_at FROM KareniaReadings WHERE beach_name ILIKE '%henley%'")
for row in cur.fetchall():
    print(row)
conn.close()
