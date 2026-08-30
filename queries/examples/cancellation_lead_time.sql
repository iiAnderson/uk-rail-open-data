-- The ghost timetable: how much of the advertised service is deleted before the day.
--
-- Self-contained — run it directly, no base file needed.
--
-- normalised_v1.minutes_before_origin_dep records how far ahead of departure a
-- cancellation was made. Services cancelled far enough in advance effectively
-- never appear in the timetable passengers see, and are treated differently in
-- official statistics from those cancelled on the day.
--
-- Scans one month, about 190 MB.

SELECT
    CASE
        WHEN minutes_before_origin_dep IS NULL       THEN 'unknown'
        WHEN minutes_before_origin_dep >= 10080      THEN 'over a week ahead'
        WHEN minutes_before_origin_dep >= 1440       THEN '1-7 days ahead'
        WHEN minutes_before_origin_dep >= 180        THEN '3-24 hours ahead'
        WHEN minutes_before_origin_dep >= 60         THEN '1-3 hours ahead'
        WHEN minutes_before_origin_dep >= 0          THEN 'under an hour'
        ELSE 'after departure time'
    END                                              AS lead_time,
    COUNT(*)                                         AS services,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM uk_rail.normalised_v1
WHERE year = '2026' AND month = '08'
  AND passenger = true
  AND cancellation_status = 'cancelled'
GROUP BY 1
ORDER BY services DESC
