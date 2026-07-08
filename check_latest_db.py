from db_config import get_connection, adapt_sql
conn = get_connection()
cursor = conn.cursor()
cursor.execute(adapt_sql("""
    SELECT TOP 50
        beach_name, cell_count_per_litre, severity, recorded_at
    FROM KareniaReadings
    ORDER BY recorded_at DESC
"""))
rows = cursor.fetchall()
print(f"Top 50 count: {len(rows)}")
for r in rows[:10]:
    print(r)
conn.close()
