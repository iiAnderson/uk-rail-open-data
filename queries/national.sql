-- National totals for one day. Prepend _base_passenger_hours.sql.
SELECT
    SUM(lost_minutes) / 60.0                                              AS passenger_hours,
    SUM(IF(leg_cancelled, lost_minutes, 0)) / 60.0                        AS hours_cancellations,
    SUM(IF(NOT leg_cancelled, lost_minutes, 0)) / 60.0                    AS hours_delays,
    COUNT(DISTINCT rid)                                                   AS services,
    SUM(passengers)                                                       AS journeys_estimated
FROM lost
