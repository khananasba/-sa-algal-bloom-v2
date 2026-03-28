-- ============================================================
-- SA Algal Bloom Monitor — Supabase / PostgreSQL Schema
-- Run this in the Supabase SQL Editor (supabase.com → SQL Editor)
-- ============================================================

CREATE TABLE IF NOT EXISTS WeatherReadings (
    id               SERIAL PRIMARY KEY,
    recorded_at      TIMESTAMP NOT NULL,
    location_name    VARCHAR(100),
    latitude         FLOAT,
    longitude        FLOAT,
    wind_speed       FLOAT,
    wind_direction   FLOAT,
    sea_surface_temp FLOAT,
    solar_radiation  FLOAT,
    wave_height      FLOAT,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS WaterQuality (
    id               SERIAL PRIMARY KEY,
    recorded_at      TIMESTAMP NOT NULL,
    station_name     VARCHAR(100),
    latitude         FLOAT,
    longitude        FLOAT,
    dissolved_oxygen FLOAT,
    ph               FLOAT,
    salinity         FLOAT,
    turbidity        FLOAT,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS KareniaReadings (
    id                   SERIAL PRIMARY KEY,
    recorded_at          TIMESTAMP NOT NULL,
    beach_name           VARCHAR(200),
    latitude             FLOAT,
    longitude            FLOAT,
    cell_count_per_litre INTEGER,
    severity             VARCHAR(20),
    source               VARCHAR(100),
    created_at           TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS BloomForecasts (
    id               SERIAL PRIMARY KEY,
    created_at       TIMESTAMP DEFAULT NOW(),
    forecast_hour    INTEGER,
    particle_geojson TEXT,
    severity         VARCHAR(20),
    sfabi_mean       FLOAT,
    particle_count   INTEGER
);

CREATE TABLE IF NOT EXISTS Alerts (
    id               SERIAL PRIMARY KEY,
    created_at       TIMESTAMP DEFAULT NOW(),
    zone_name        VARCHAR(200),
    severity         VARCHAR(20),
    predicted_hour   INTEGER,
    alert_sent       BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS BeachSafetyScores (
    id               SERIAL PRIMARY KEY,
    recorded_at      TIMESTAMP DEFAULT NOW(),
    beach_name       VARCHAR(200),
    latitude         FLOAT,
    longitude        FLOAT,
    safety_score     FLOAT,
    label            VARCHAR(50),
    cell_count       INTEGER
);

CREATE TABLE IF NOT EXISTS AquacultureLeases (
    id               SERIAL PRIMARY KEY,
    lease_name       VARCHAR(200),
    latitude         FLOAT,
    longitude        FLOAT,
    lease_type       VARCHAR(100),
    status           VARCHAR(50),
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS DollarAtRiskLog (
    id               SERIAL PRIMARY KEY,
    recorded_at      TIMESTAMP DEFAULT NOW(),
    zone_name        VARCHAR(200),
    severity         VARCHAR(20),
    estimated_loss   FLOAT,
    lease_count      INTEGER
);
