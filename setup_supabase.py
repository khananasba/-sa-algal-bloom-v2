"""
setup_supabase.py — creates all tables in Supabase by running supabase_schema.sql.
Run once before deploying: python setup_supabase.py
"""
import os
import psycopg2

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("ERROR: DATABASE_URL is not set. Check your .env file.")

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "database", "supabase_schema.sql")

print("Connecting to Supabase PostgreSQL...")
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cursor = conn.cursor()
print("Connected OK.\n")

print(f"Reading schema from {SCHEMA_FILE} ...")
with open(SCHEMA_FILE, encoding="utf-8") as f:
    sql = f.read()

# Split on semicolons and run each statement individually
statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
for stmt in statements:
    try:
        cursor.execute(stmt)
    except Exception as e:
        print(f"  WARNING: {e}")

print("\nVerifying tables were created:")
cursor.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name
""")
tables = [row[0] for row in cursor.fetchall()]
expected = [
    "alerts", "aquacultureleases", "beachsafetyscores",
    "bloomforecasts", "dollaratrisklog", "kareniareadings",
    "waterquality", "weatherreadings",
]
for t in expected:
    status = "OK" if t in tables else "MISSING"
    print(f"  {t:<30} {status}")

print(f"\nAll tables present in Supabase: {set(expected).issubset(set(tables))}")
cursor.close()
conn.close()
print("Done.")
