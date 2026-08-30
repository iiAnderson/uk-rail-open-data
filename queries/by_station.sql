-- Where lost time lands. Prepend _base_passenger_hours.sql.
--
-- Attributed to the DESTINATION station — the place passengers arrived late at,
-- which is where the time was actually lost. This is not the same as the station
-- where the disruption started, which the data does not directly identify.
SELECT
    l.destination_crs                AS crs,
    COALESCE(s.station_name, l.destination_crs) AS station_name,
    SUM(l.lost_minutes) / 60.0       AS passenger_hours
FROM lost l
LEFT JOIN station_names s ON l.destination_crs = s.crs
GROUP BY l.destination_crs, s.station_name
ORDER BY passenger_hours DESC
LIMIT 20
