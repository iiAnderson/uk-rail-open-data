"""Read the timing points services are scheduled *through*, not just stop at.

A section between two stations that a fast service does not call at — London
Liverpool Street to Bethnal Green, say — is invisible to stop-based matching,
and gap-fill only partly recovers it. Without this, those sections read as all
but unused; with it they carry the several hundred services a day they really do.

The cost is why it is not part of the daily job. locations_v1 holds one row per
timing point per message and scans at about 0.5 GB a day against normalised_v1's
5.9 MB. Ninety times the price, for something that does not change: the points a
route runs through are a property of the route, not of the day. So it is read
once over a historical range, folded into the route cache, and never read again.

The two tables are in the same requester-pays bucket as everything else but are
not among the three that athena/ defines — they are raw message-level data and
nothing else here needs them:

    services_v1   s3://darwin-connect/services/v1/    partitioned year/month/day
    locations_v1  s3://darwin-connect/locations/v1/   partitioned year/month/day

Both are partitioned by the date a message was ingested rather than the date the
service ran, which is why the filters below reach a day either side.
"""

from __future__ import annotations

from datetime import date, timedelta

from common.aws import Athena

PASS_SQL = """
WITH target AS (
    SELECT DISTINCT rid
    FROM normalised_v1
    WHERE {normalised_filter}
      AND passenger = true
      AND toc NOT IN ('LT', 'LO')
),
messages AS (
    SELECT s.rid, s.update_id
    FROM services_v1 s
    INNER JOIN target t ON s.rid = t.rid
    WHERE {services_filter}
)
SELECT m.rid, array_join(array_agg(DISTINCT l.tpl), ',') AS passed
FROM locations_v1 l
INNER JOIN messages m ON l.service_update_id = m.update_id
WHERE {locations_filter}
  AND l.type = 'PASS'
  AND l.time_type = 'SCHED'
GROUP BY m.rid
"""


def _raw_filter(day: date, alias: str) -> str:
    start, end = day - timedelta(days=1), day + timedelta(days=1)
    years = ", ".join(f"'{y}'" for y in sorted({start.year, end.year}))
    return (
        f"{alias}.year IN ({years}) AND "
        f"CAST({alias}.year || {alias}.month || {alias}.day AS INTEGER) "
        f"BETWEEN {start:%Y%m%d} AND {end:%Y%m%d}"
    )


def fetch(athena: Athena, day: date) -> dict[str, set[str]]:
    """Timing points each service was scheduled through, keyed by service id."""
    sql = PASS_SQL.format(
        normalised_filter=f"year = '{day:%Y}' AND month = '{day:%m}' AND day = '{day:%d}'",
        services_filter=_raw_filter(day, "s"),
        locations_filter=_raw_filter(day, "l"),
    )
    passed = {}
    for row in athena.query(sql):
        tpls = (row["passed"] or "").strip()
        if tpls:
            passed[row["rid"]] = set(tpls.split(","))
    return passed
