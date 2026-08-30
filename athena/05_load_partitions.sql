-- Partition discovery. Run after creating the tables, and again whenever you
-- want to pick up days added since. MSCK is not supported in Athena engine v3,
-- so partitions are added explicitly.
--
-- normalised_v1 has one partition per day since 2025-01-01, so the simplest
-- approach is partition projection — add this to the table instead of running
-- ALTER for every day:
--
--   ALTER TABLE uk_rail.normalised_v1 SET TBLPROPERTIES (
--     'projection.enabled'          = 'true',
--     'projection.year.type'        = 'integer',
--     'projection.year.range'       = '2025,2030',
--     'projection.year.digits'      = '4',
--     'projection.month.type'       = 'integer',
--     'projection.month.range'      = '1,12',
--     'projection.month.digits'     = '2',
--     'projection.day.type'         = 'integer',
--     'projection.day.range'        = '1,31',
--     'projection.day.digits'       = '2',
--     'storage.location.template'   =
--       's3://darwin-connect/normalised/v1/year=${year}/month=${month}/day=${day}/'
--   );
--
-- With projection enabled you never need to register partitions again.

ALTER TABLE uk_rail.odm_v1 ADD IF NOT EXISTS
  PARTITION (financial_year = '20242025')
  LOCATION 's3://darwin-connect/odm/v1/financial_year=20242025/';
