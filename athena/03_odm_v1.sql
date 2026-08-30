-- odm_v1 — annual passenger journey counts between station pairs.
--
-- This is what turns "minutes late" into "passenger-hours lost": it says how
-- many people actually travel each origin-destination pair. Without it, a
-- cancelled branch-line service looks as costly as a cancelled commuter train.
--
-- Only financial_year=20242025 is currently published. It is used as a stable
-- weighting of relative demand, not as a current traffic estimate — see DATA.md.

CREATE EXTERNAL TABLE IF NOT EXISTS uk_rail.odm_v1 (
  origin_nlc                int,
  origin_crs                string,
  origin_station_name       string,
  origin_station_group      string,
  origin_region             string,
  origin_la                 string,
  destination_nlc           int,
  destination_crs           string,
  destination_station_name  string,
  destination_station_group string,
  destination_region        string,
  destination_la            string,
  journeys                  int
)
PARTITIONED BY (financial_year string)
STORED AS PARQUET
LOCATION 's3://darwin-connect/odm/v1/'
TBLPROPERTIES ('parquet.compression' = 'SNAPPY');
