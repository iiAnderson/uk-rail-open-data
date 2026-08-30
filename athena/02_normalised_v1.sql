-- normalised_v1 — one row per train service.
--
-- This is the table you want for almost everything. It is ~6 MB per day
-- (about 30,000 services), against ~4 GB per day for the raw location feed,
-- so a query over the whole history scans under 3 GB.
--
-- Partitioned by SERVICE date (taken from the first 8 characters of `rid`),
-- not by the date the message was ingested.

CREATE EXTERNAL TABLE IF NOT EXISTS uk_rail.normalised_v1 (
  rid                       string,   -- service id: YYYYMMDD + unique id
  service_date              string,   -- YYYYMMDD
  toc                       string,   -- operator code, e.g. GW, SE, VT
  train_id                  string,   -- headcode, e.g. 1S49
  passenger                 boolean,
  origin_tpl                string,
  origin_sched_dep          string,
  destination_tpl           string,
  destination_sched_arr     string,
  num_sched_stops           int,
  num_act_stops             int,
  cancellation_status       string,   -- 'ran' | 'cancelled' | 'partially_cancelled'
  cancel_reason             string,
  delay_reason              string,
  cancellation_ts           string,
  minutes_before_origin_dep int,      -- how far ahead of departure it was cancelled
  origin_delay_mins         int,
  destination_delay_mins    int,
  avg_delay_mins            double,
  max_delay_mins            int,
  stops_on_time             int,      -- 0-5 mins late
  stops_minor_delay         int,      -- 5-15
  stops_moderate_delay      int,      -- 15-30
  stops_major_delay         int,      -- 30+
  avg_loading               double,   -- percent full, where the operator reports it
  loading_0_20              int,
  loading_20_40             int,
  loading_40_60             int,
  loading_60_80             int,
  loading_80_100            int,
  -- One entry per station called at, in scheduled order.
  -- Lets you filter by station without joining the location tables:
  --   CROSS JOIN UNNEST(stops) AS t(stop) WHERE stop.tpl = 'BRSTLTM'
  stops                     array<struct<
                              tpl:        string,
                              arr_sched:  string,
                              dep_sched:  string,
                              arr_act:    string,
                              dep_act:    string,
                              arr_delay:  int,
                              dep_delay:  int,
                              cancelled:  boolean>>
)
PARTITIONED BY (
  year  string,
  month string,
  day   string
)
STORED AS PARQUET
LOCATION 's3://darwin-connect/normalised/v1/'
TBLPROPERTIES ('parquet.compression' = 'SNAPPY');
