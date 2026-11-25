CREATE TABLE IF NOT EXISTS fountain_stations (
 code text PRIMARY KEY, title text NOT NULL, district text NOT NULL, cartridge text NOT NULL,
 reserve int NOT NULL CHECK(reserve>=0), in_service boolean NOT NULL
);
CREATE TABLE IF NOT EXISTS service_weeks (
 station text REFERENCES fountain_stations(code), week_of date,
 liters int NOT NULL CHECK(liters>=0), changes int NOT NULL CHECK(changes>=0),
 note text NOT NULL, PRIMARY KEY(station,week_of)
);
CREATE TABLE IF NOT EXISTS replacement_estimates (
 station text PRIMARY KEY REFERENCES fountain_stations(code), history_week date NOT NULL,
 expected real NOT NULL CHECK(expected>=0), upper int NOT NULL CHECK(upper>=0),
 demand_class text NOT NULL CHECK(demand_class IN ('base','busy','festival')),
 exposure real NOT NULL CHECK(exposure>=0), calibration jsonb NOT NULL,
 basis text NOT NULL DEFAULT ''
);
ALTER TABLE replacement_estimates ADD COLUMN IF NOT EXISTS basis text NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS service_rounds (
 code text PRIMARY KEY,district text NOT NULL, service_on date NOT NULL, capacity int NOT NULL CHECK(capacity>0)
);
CREATE TABLE IF NOT EXISTS round_pickups (
 route text REFERENCES service_rounds(code), station text REFERENCES fountain_stations(code),
 quantities int NOT NULL CHECK(quantities>0), planning_week date NOT NULL,
 cartridge text NOT NULL, signed_by text NOT NULL, PRIMARY KEY(route,station),
 UNIQUE(station,planning_week)
);
