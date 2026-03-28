"""
db_config.py — database connection that auto-switches between backends.

Rules:
  DATABASE_URL set   → PostgreSQL (Supabase / any Postgres)
  DATABASE_URL unset → SQL Server (localhost\\SQLEXPRESS, Windows auth)

Usage in every Python file:
    from db_config import get_connection, adapt_sql, ph
"""
import os
import re

# Load .env file automatically so scripts work without manually exporting vars
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.getenv("DATABASE_URL")
IS_POSTGRES = bool(DATABASE_URL)

# Parameterised-query placeholder: %s (psycopg2) vs ? (pyodbc)
PH = "%s" if IS_POSTGRES else "?"


def get_connection():
    """Return a live DB connection for the current environment."""
    if IS_POSTGRES:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    else:
        import pyodbc
        return pyodbc.connect(
            "DRIVER={ODBC Driver 17 for SQL Server};"
            "SERVER=localhost\\SQLEXPRESS;"
            "DATABASE=AlgalBloomDB;"
            "Trusted_Connection=yes;"
        )


def adapt_sql(sql: str) -> str:
    """
    Translate SQL Server-specific syntax to PostgreSQL when running online.
    Currently handles:
      SELECT TOP N ...  →  SELECT ... LIMIT N
    Leave SQL unchanged when running locally against SQL Server.
    """
    if not IS_POSTGRES:
        return sql
    match = re.search(r"\bSELECT\s+TOP\s+(\d+)\b", sql, re.IGNORECASE)
    if match:
        limit_val = match.group(1)
        sql = re.sub(r"\bSELECT\s+TOP\s+\d+\b", "SELECT", sql, flags=re.IGNORECASE)
        sql = sql.rstrip().rstrip(";") + f"\nLIMIT {limit_val}"
    return sql


def ph(n: int) -> str:
    """Return n comma-separated placeholders, e.g. ph(3) → '%s, %s, %s' or '?, ?, ?'."""
    return ", ".join([PH] * n)
