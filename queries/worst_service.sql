-- The single train that cost passengers the most time. Prepend _base_passenger_hours.sql.
SELECT
    t.rid,
    t.toc,
    t.passenger_hours,
    n.train_id,
    n.cancellation_status,
    COALESCE(og.station_name, n.origin_tpl)      AS origin_name,
    COALESCE(dg.station_name, n.destination_tpl) AS destination_name,
    n.origin_sched_dep
FROM (
    SELECT rid, toc, SUM(lost_minutes) / 60.0 AS passenger_hours
    FROM lost
    GROUP BY rid, toc
    ORDER BY passenger_hours DESC
    LIMIT 1
) t
JOIN uk_rail.normalised_v1 n ON n.rid = t.rid AND {date_filter}
LEFT JOIN uk_rail.tiplocs og ON n.origin_tpl = og.tiploc_code
LEFT JOIN uk_rail.tiplocs dg ON n.destination_tpl = dg.tiploc_code
