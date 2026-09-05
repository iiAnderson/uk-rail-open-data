# The track-section map

Draws every passenger service onto the physical track it runs over: 2,641
sections of real railway, coloured by how late the trains on them were and how
much of the service was lost.

```bash
pip install -r ../aggregate/requirements.txt

# one day, to a local directory
python tracks/tracks.py --date 2026-09-04 --output ./out \
    --workgroup uk-rail-dashboard-aggregate

# straight to the site bucket, which is what the Lambda does
python tracks/tracks.py --output s3://my-site-bucket/data/tracks \
    --state s3://my-working-bucket/state --workgroup ...
```

With no `--date` it builds yesterday.

## Design

**The expensive part is cached by route.** Which sections a service runs over
depends on its ordered stop sequence, not on the day it ran, and the same routes
recur constantly. So attribution is computed once per distinct route and kept in
`route_sections.json.gz`. A day then costs one query over one partition of
`normalised_v1` — 5.9 MB, under Athena's 10 MB billing minimum, $0.00005 a run.
A year of daily runs is under 2p.

**Everything published is a sum.** A file carries services, services that ran,
summed delay and cancellations — never an average. That is what makes a month
the addition of its days and a year the addition of its months, exactly, with no
re-reading of the source data. The browser does the division.

**Gaps stay gaps.** A day with too few services is a pipeline failure, not a
quiet Tuesday, and is skipped rather than published as a low number. See
[Known gaps](../README.md#known-gaps).

## What lives where

| | |
|---|---|
| `site/tracks/geometry.json` | the drawn network. Committed, served with the site, rebuilt only when the track data changes. |
| `data/tracks/index.json` | which periods exist |
| `data/tracks/day/2026-09-04.json` | one service day |
| `data/tracks/month/2026-09.json` | one calendar month |
| `data/tracks/year/2026.json` | one calendar year |

Day files are kept for the current month, months for a rolling year, years for
good. A period that has been rolled into a coarser one is deleted, so the site
holds about 45 files rather than several hundred. `DAY_RETENTION_MONTHS` and
`MONTH_RETENTION_MONTHS` at the top of `tracks.py` are the knobs.

## Attribution

Two passes, in `attribute.py`:

1. **Direct match** — a section is attributed when the route touches at least
   two of the stations on it, compared as CRS codes because 29 stations span
   several TIPLOCs and Clapham Junction alone has five.
2. **Gap fill** — a fast service stops at neither end of most sections it passes
   through, so consecutive stops are joined by a breadth-first walk of the
   section graph, up to twelve hops.

Both are inferences. A section attributed to a service says the service almost
certainly ran over that track; it is not a signalling record.

### Pass-through timing points

Darwin also records the points a service is scheduled *through*. They matter:
without them, London Liverpool Street to Bethnal Green reads as two services a
day rather than seven hundred, because nothing stops at either end of it.

They live in `locations_v1`, which scans at about 0.5 GB a day against
`normalised_v1`'s 5.9 MB — ninety times the price for something that does not
change day to day. So `--timing-points` reads them during a backfill, folds the
result into the route cache, and the daily job never pays for it:

```bash
python tracks/tracks.py --backfill 2025-01-01 2026-09-04 \
    --timing-points --raw-database darwin-connect \
    --workgroup uk-rail-dashboard-aggregate
```

That is about 280 GB, or **$1.40**, for the whole archive. The query is skipped
for any day whose routes are all already cached, so re-running a backfill costs
almost nothing. Worth repeating over a week or two after a timetable change, when
routes the cache has never seen start running.

`--raw-database` is needed because `services_v1` and `locations_v1` are not among
the three tables `athena/` defines — they are raw message-level data in the same
requester-pays bucket, and nothing else in this repository uses them. See
`timing_points.py` for their locations.

## Cancellations are attributed to the part that was cancelled

A part-cancelled service is one that ran most of its journey and was curtailed —
typically five stops out of thirty-five. Counting it as cancelled everywhere it
was booked to go overstates cancellation about sevenfold, and on a busy day turns
a 2% section into a 39% one.

Darwin flags which stops were lost, so that is what gets attributed: a train
curtailed at Reading is a cancellation west of Reading and a normal, possibly
late, train east of it. Its reported delay counts on the sections it served, and
nowhere else.

## Rebuilding

```bash
python tracks/tracks.py --rebuild 2026-08     # a month, from its days
python tracks/tracks.py --rebuild 2026        # a year, from its months
```

Only possible while the files below still exist. Past that, re-run the days
through Athena — they cost $0.00005 each.

Re-running a day that a period already counts is a no-op rather than a double
count; each period file records the days in it.

## Reference data

| File | Purpose |
|---|---|
| `reference/track_sections.json` | 2,641 sections of track geometry with the stations on them, derived from open railway GIS data |
| `reference/crs.json` | TIPLOC → CRS, built from the `tiplocs` table |
| `reference/crs_overrides.json` | corrections to it, and the infrastructure-only TIPLOCs that appear in track geometry but never in service data |

`crs.json` and `site/tracks/geometry.json` are both produced by:

```bash
python tracks/build_reference.py --workgroup uk-rail-dashboard-aggregate
```

Run that when the track geometry or the station reference data changes, and not
otherwise.
