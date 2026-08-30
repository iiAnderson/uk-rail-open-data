-- Why the time was lost. Prepend _base_passenger_hours.sql.
--
-- Reason codes are sparse: Darwin only supplies one on a minority of services,
-- so a large "Not stated" share is expected and honest. Treat the ranking as
-- relative rather than as a complete account.
SELECT
    COALESCE(NULLIF(reason, ''), 'Not stated')                          AS reason,
    SUM(lost_minutes) / 60.0                                            AS passenger_hours,
    100.0 * SUM(lost_minutes) / NULLIF(SUM(SUM(lost_minutes)) OVER (), 0) AS pct_of_hours
FROM lost
GROUP BY COALESCE(NULLIF(reason, ''), 'Not stated')
ORDER BY passenger_hours DESC
