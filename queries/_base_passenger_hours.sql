-- Base CTEs for the passenger-hours metric.
--
-- This file is not run on its own. site/aggregate/aggregate.py prepends it to
-- each of the aggregation queries beside it (national.sql, by_operator.sql, ...),
-- which pick up where this leaves off by selecting from `lost`.
--
-- ---------------------------------------------------------------------------
-- THE IDEA
--
-- Every published rail statistic counts trains: percentage cancelled, percentage
-- on time. Trains are not the thing being wasted — people's time is. A four
-- minute delay to a packed commuter service destroys more human time than a whole
-- day of cancellations on a quiet branch line, and train-counting cannot see it.
--
-- So: weight every delayed or cancelled leg by the number of people who actually
-- travel it, and express the result in hours.
--
-- ---------------------------------------------------------------------------
-- HOW A PASSENGER LOAD IS ESTIMATED
--
-- odm_v1 gives annual journeys between each station pair. Divide by 365 for a
-- daily figure, then divide by the number of services offering that pair that
-- day. If 40,000 people a year travel Reading to Paddington and 120 trains a day
-- serve it, each train carries roughly 0.9 of those journeys.
--
-- This is an estimate, not a headcount. It assumes demand spreads evenly across
-- the services that offer a pair, which under-weights the peak and over-weights
-- the middle of the day. It is stable and consistent across operators, which is
-- what makes it useful for comparison.
--
-- ---------------------------------------------------------------------------
-- HOW LOST TIME IS COUNTED
--
--   Delayed leg      passengers x minutes late on arrival
--   Cancelled leg    passengers x wait for the next service on that pair,
--                    which is (operating day / services that day), capped
--
-- The cancellation rule charges displacement rather than a flat penalty: losing
-- one of 120 Reading-Paddington trains costs each passenger a few minutes, while
-- losing one of four trains to a rural station costs them the cap.
--
-- ---------------------------------------------------------------------------
-- Placeholders, substituted by aggregate.py:
--   {date_filter}         partition predicate, e.g. year='2026' AND month='08' AND day='29'
--   {odm_financial_year}  ODM partition to weight with, e.g. 20242025
--   {operating_day_mins}  length of the service day in minutes (default 1080 = 05:00-23:00)
--   {wait_cap_mins}       longest wait charged for a cancelled leg (default 120)

WITH stops_raw AS (
    SELECT
        n.rid,
        n.toc,
        n.cancellation_status,
        n.cancel_reason,
        n.delay_reason,
        stop.tpl       AS tpl,
        stop.arr_delay AS arr_delay,
        stop.cancelled AS stop_cancelled,
        ROW_NUMBER() OVER (
            PARTITION BY n.rid
            ORDER BY COALESCE(stop.dep_sched, stop.arr_sched)
        ) AS seq
    FROM uk_rail.normalised_v1 n
    CROSS JOIN UNNEST(n.stops) AS t(stop)
    WHERE {date_filter}
      AND n.passenger = true
      -- Drop pass-through timing points. A train that does not stop picks
      -- nobody up, and PASS rows are flagged cancelled when the service is,
      -- which would otherwise inflate every cancellation figure.
      AND (stop.arr_sched IS NOT NULL OR stop.dep_sched IS NOT NULL)
),

-- TIPLOC to CRS. 29 stations span several TIPLOCs, so collapse to one row per
-- (service, station), keeping its earliest position in the route.
stops_crs AS (
    SELECT rid, toc, cancellation_status, cancel_reason, delay_reason,
           crs, arr_delay, stop_cancelled, seq
    FROM (
        SELECT s.*,
               t.crs_code AS crs,
               ROW_NUMBER() OVER (PARTITION BY s.rid, t.crs_code ORDER BY s.seq) AS crs_rn
        FROM stops_raw s
        JOIN uk_rail.tiplocs t ON s.tpl = t.tiploc_code
        WHERE t.crs_code <> ''
    )
    WHERE crs_rn = 1
),

-- Every directed origin -> destination pair a service actually offers.
legs AS (
    SELECT
        a.rid,
        a.toc,
        a.cancel_reason,
        a.delay_reason,
        a.crs AS origin_crs,
        b.crs AS destination_crs,
        GREATEST(COALESCE(b.arr_delay, 0), 0) AS arr_delay_mins,
        (COALESCE(a.stop_cancelled, false)
         OR COALESCE(b.stop_cancelled, false)
         OR a.cancellation_status = 'cancelled') AS leg_cancelled
    FROM stops_crs a
    JOIN stops_crs b
      ON a.rid = b.rid
     AND b.seq > a.seq
),

-- How many services offer each pair today. This is the divisor that turns an
-- annual journey total into a per-train passenger load.
service_frequency AS (
    SELECT origin_crs, destination_crs, COUNT(DISTINCT rid) AS services_today
    FROM legs
    GROUP BY origin_crs, destination_crs
),

-- Annual journeys between each station pair, as a daily average.
odm_daily AS (
    SELECT origin_crs, destination_crs, SUM(journeys) / 365.0 AS daily_journeys
    FROM uk_rail.odm_v1
    WHERE financial_year = '{odm_financial_year}'
    GROUP BY origin_crs, destination_crs
),

-- One row per leg, carrying its estimated passenger load and the time it cost them.
lost AS (
    SELECT
        l.rid,
        l.toc,
        l.origin_crs,
        l.destination_crs,
        l.leg_cancelled,
        COALESCE(l.cancel_reason, l.delay_reason) AS reason,
        COALESCE(o.daily_journeys, 0) / f.services_today AS passengers,
        CASE
            WHEN l.leg_cancelled
                THEN (COALESCE(o.daily_journeys, 0) / f.services_today)
                     * LEAST({operating_day_mins} / CAST(f.services_today AS DOUBLE),
                             CAST({wait_cap_mins} AS DOUBLE))
            ELSE (COALESCE(o.daily_journeys, 0) / f.services_today)
                 * CAST(l.arr_delay_mins AS DOUBLE)
        END AS lost_minutes
    FROM legs l
    JOIN service_frequency f
      ON l.origin_crs = f.origin_crs
     AND l.destination_crs = f.destination_crs
    LEFT JOIN odm_daily o
      ON l.origin_crs = o.origin_crs
     AND l.destination_crs = o.destination_crs
),

-- One name per CRS code, for labelling.
station_names AS (
    SELECT crs_code AS crs, MIN(station_name) AS station_name
    FROM uk_rail.tiplocs
    WHERE crs_code <> ''
    GROUP BY crs_code
)
