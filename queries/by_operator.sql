-- Operator league table. Prepend _base_passenger_hours.sql.
--
-- hours_per_1k_journeys is the column that matters. Ranking by raw hours mostly
-- ranks operators by size; normalising by traffic shows who is actually costing
-- their passengers the most time.
SELECT
    toc,
    SUM(lost_minutes) / 60.0                                                AS passenger_hours,
    SUM(passengers)                                                         AS journeys_estimated,
    1000.0 * (SUM(lost_minutes) / 60.0) / NULLIF(SUM(passengers), 0)        AS hours_per_1k_journeys
FROM lost
WHERE toc IS NOT NULL AND toc <> ''
GROUP BY toc
ORDER BY passenger_hours DESC
