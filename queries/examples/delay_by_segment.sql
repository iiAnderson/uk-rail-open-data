-- Where the railway manufactures delay, segment by segment.
--
-- Self-contained — run it directly, no base file needed.
--
-- For each consecutive pair of stops, the difference between the delay on
-- arrival at the second and the delay on departure from the first is the time
-- the train lost (or recovered) on that stretch of track. Aggregated nationally
-- this finds the segments that actually generate lateness, rather than the
-- stations where it happens to be measured.
--
-- A negative median means the segment usually recovers time, which is a sign of
-- padding in the timetable rather than good performance.
--
-- Scans one day, about 6 MB.

WITH ordered_stops AS (
    SELECT
        n.rid,
        n.toc,
        stop.tpl,
        stop.dep_delay,
        stop.arr_delay,
        ROW_NUMBER() OVER (
            PARTITION BY n.rid
            ORDER BY COALESCE(stop.dep_sched, stop.arr_sched)
        ) AS seq
    FROM uk_rail.normalised_v1 n
    CROSS JOIN UNNEST(n.stops) AS t(stop)
    WHERE n.year = '2026' AND n.month = '08' AND n.day = '29'
      AND n.passenger = true
      AND n.cancellation_status = 'ran'
      AND (stop.arr_sched IS NOT NULL OR stop.dep_sched IS NOT NULL)
),
segments AS (
    SELECT
        a.tpl AS from_tpl,
        b.tpl AS to_tpl,
        b.arr_delay - a.dep_delay AS delay_added_mins
    FROM ordered_stops a
    JOIN ordered_stops b
      ON a.rid = b.rid
     AND b.seq = a.seq + 1
    WHERE a.dep_delay IS NOT NULL
      AND b.arr_delay IS NOT NULL
)
SELECT
    COALESCE(f.station_name, from_tpl) AS from_station,
    COALESCE(t.station_name, to_tpl)   AS to_station,
    COUNT(*)                                        AS trains,
    ROUND(APPROX_PERCENTILE(delay_added_mins, 0.5), 1) AS median_minutes_added,
    ROUND(SUM(delay_added_mins) / 60.0, 1)          AS train_hours_added
FROM segments
LEFT JOIN uk_rail.tiplocs f ON segments.from_tpl = f.tiploc_code
LEFT JOIN uk_rail.tiplocs t ON segments.to_tpl   = t.tiploc_code
GROUP BY from_tpl, to_tpl, f.station_name, t.station_name
HAVING COUNT(*) >= 20
ORDER BY train_hours_added DESC
LIMIT 50
