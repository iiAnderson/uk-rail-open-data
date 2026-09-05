-- National totals for one day. Prepend _base_passenger_hours.sql.
--
-- excluded_journeys is the coverage guard's cost: demand on station pairs whose
-- service count in this dataset is too low to be believed, left out rather than
-- attributed to whichever train happened to appear. Watch it — a rising share
-- means the upstream service data is losing coverage, not that the railway
-- improved.
SELECT
    SUM(lost_minutes) / 60.0                                              AS passenger_hours,
    SUM(IF(leg_cancelled, lost_minutes, 0)) / 60.0                        AS hours_cancellations,
    SUM(IF(NOT leg_cancelled, lost_minutes, 0)) / 60.0                    AS hours_delays,
    COUNT(DISTINCT rid)                                                   AS services,
    SUM(passengers)                                                       AS journeys_estimated,
    MAX(x.excluded_pairs)                                                 AS excluded_pairs,
    MAX(x.excluded_journeys)                                              AS excluded_journeys
FROM lost
-- One row, cross joined, so the excluded set is evaluated once rather than
-- once per scalar subquery.
CROSS JOIN (
    SELECT COUNT(*) AS excluded_pairs,
           COALESCE(SUM(daily_journeys), 0) AS excluded_journeys
    FROM pair_load_excluded
) x
