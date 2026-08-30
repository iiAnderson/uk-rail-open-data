-- tiplocs — station reference data.
--
-- The service data identifies stations by TIPLOC (an operational code such as
-- BRSTLTM). Public-facing codes are CRS (BRI). This table maps between them and
-- carries station names and grid coordinates.
--
-- Note: 29 stations span several TIPLOCs — Clapham Junction has five. Always
-- group by CrsCode and use COUNT(DISTINCT rid), or you will double-count.

CREATE EXTERNAL TABLE IF NOT EXISTS uk_rail.tiplocs (
  atco_code             string,
  tiploc_code           string,
  crs_code              string,
  station_name          string,
  station_name_lang     string,
  grid_type             string,
  easting               string,
  northing              string,
  creation_datetime     string,
  modification_datetime string,
  revision_number       string,
  modification          string
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
  'separatorChar' = ',',
  'quoteChar'     = '"'
)
STORED AS TEXTFILE
LOCATION 's3://darwin-connect/tiplocs/'
TBLPROPERTIES ('skip.header.line.count' = '1');
