import pyodbc
import sys

def find_sql_server():
    driver = "ODBC Driver 17 for SQL Server"
    if driver not in pyodbc.drivers():
        for d in pyodbc.drivers():
            if "SQL Server" in d:
                driver = d
                break
    
    candidates = [
        r"localhost\SQLEXPRESS",
        r".\SQLEXPRESS", 
        r"localhost",
        r"(local)",
    ]
    
    for server in candidates:
        try:
            conn = pyodbc.connect(
                f"DRIVER={{{driver}}};SERVER={server};Trusted_Connection=yes;Connection Timeout=3;",
                timeout=3
            )
            conn.close()
            return server, driver
        except:
            continue
    return None, driver

def create_database(server, driver):
    conn = pyodbc.connect(f"DRIVER={{{driver}}};SERVER={server};DATABASE=master;Trusted_Connection=yes;")
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute("""
        IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'AlgalBloomDB')
        CREATE DATABASE AlgalBloomDB
    """)
    print("AlgalBloomDB created OK")
    conn.close()

def create_tables(server, driver):
    conn = pyodbc.connect(f"DRIVER={{{driver}}};SERVER={server};DATABASE=AlgalBloomDB;Trusted_Connection=yes;")
    cursor = conn.cursor()

    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='WeatherReadings' AND xtype='U')
        CREATE TABLE WeatherReadings (
            id               INT PRIMARY KEY IDENTITY(1,1),
            recorded_at      DATETIME NOT NULL,
            location_name    VARCHAR(100),
            latitude         FLOAT,
            longitude        FLOAT,
            wind_speed       FLOAT,
            wind_direction   FLOAT,
            sea_surface_temp FLOAT,
            solar_radiation  FLOAT,
            wave_height      FLOAT,
            created_at       DATETIME DEFAULT GETDATE()
        )
    """)
    print("WeatherReadings - OK")

    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='WaterQuality' AND xtype='U')
        CREATE TABLE WaterQuality (
            id               INT PRIMARY KEY IDENTITY(1,1),
            recorded_at      DATETIME NOT NULL,
            station_name     VARCHAR(100),
            latitude         FLOAT,
            longitude        FLOAT,
            dissolved_oxygen FLOAT,
            ph               FLOAT,
            salinity         FLOAT,
            turbidity        FLOAT,
            created_at       DATETIME DEFAULT GETDATE()
        )
    """)
    print("WaterQuality - OK")

    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='KareniaReadings' AND xtype='U')
        CREATE TABLE KareniaReadings (
            id                   INT PRIMARY KEY IDENTITY(1,1),
            recorded_at          DATETIME NOT NULL,
            beach_name           VARCHAR(200),
            latitude             FLOAT,
            longitude            FLOAT,
            cell_count_per_litre INT,
            severity             VARCHAR(20),
            source               VARCHAR(100),
            created_at           DATETIME DEFAULT GETDATE()
        )
    """)
    print("KareniaReadings - OK")

    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='BloomForecasts' AND xtype='U')
        CREATE TABLE BloomForecasts (
            id               INT PRIMARY KEY IDENTITY(1,1),
            created_at       DATETIME DEFAULT GETDATE(),
            forecast_hour    INT,
            particle_geojson NVARCHAR(MAX),
            severity         VARCHAR(20),
            sfabi_mean       FLOAT,
            particle_count   INT
        )
    """)
    print("BloomForecasts - OK")

    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Alerts' AND xtype='U')
        CREATE TABLE Alerts (
            id               INT PRIMARY KEY IDENTITY(1,1),
            created_at       DATETIME DEFAULT GETDATE(),
            zone_name        VARCHAR(200),
            severity         VARCHAR(20),
            predicted_hour   INT,
            alert_sent       BIT DEFAULT 0
        )
    """)
    print("Alerts - OK")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    print("Finding SQL Server...")
    server, driver = find_sql_server()
    
    if not server:
        print("ERROR: Cannot find SQL Server.")
        print("Open SSMS, copy your server name, paste it here and I will fix.")
        sys.exit(1)
    
    print(f"Found: {server}")
    create_database(server, driver)
    create_tables(server, driver)
    print("")
    print("DONE - All 5 tables created in AlgalBloomDB")