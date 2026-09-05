-- One row per passenger service for a single day, with the route it took.
--
-- Standalone: unlike the by_* queries this is not prepended with
-- _base_passenger_hours.sql. The track map is a different metric.
--
-- The route is the whole point. Which physical track sections a service runs
-- over is a property of its ordered stop sequence, not of the day, so the job
-- caches attribution by route and never needs stop-level rows. That is the
-- difference between ~30k rows a day and ~450k.
--
-- Only genuine calling points count: stops carries pass-through timing points
-- with no scheduled time, which are not stations the service stopped at.
-- LT (London Underground) and LO (London Overground) are excluded to match the
-- published dataset.
--
-- cancelled_route is the part of the journey that did not happen. A
-- part-cancelled service is one that ran most of its route and was curtailed —
-- typically five stops out of thirty-five — so treating it as cancelled
-- everywhere it was booked to go overstates cancellation several-fold. The
-- per-stop flag says which end was lost, and that is what gets attributed.

SELECT
  n.rid,
  n.toc,
  n.train_id,
  n.cancellation_status,
  n.avg_delay_mins,
  n.cancel_reason,
  n.delay_reason,
  array_join(
    transform(
      filter(n.stops, s -> s.arr_sched IS NOT NULL OR s.dep_sched IS NOT NULL),
      s -> s.tpl
    ),
    ','
  ) AS route,
  array_join(
    transform(
      filter(
        n.stops,
        s -> s.cancelled AND (s.arr_sched IS NOT NULL OR s.dep_sched IS NOT NULL)
      ),
      s -> s.tpl
    ),
    ','
  ) AS cancelled_route
FROM normalised_v1 n
WHERE {date_filter}
  AND n.passenger = true
  AND n.toc NOT IN ('LT', 'LO')
  AND cardinality(n.stops) > 0
