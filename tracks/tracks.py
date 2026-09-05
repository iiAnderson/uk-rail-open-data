"""Build the track-section map's JSON, one service day at a time.

    python tracks/tracks.py --date 2026-09-04 --output ./out
    python tracks/tracks.py --backfill 2025-01-01 2026-09-04 --timing-points

With no --date it builds yesterday. Each run scans one partition of
normalised_v1 — under Athena's 10 MB billing minimum, so a day costs $0.00005
and a year of daily runs costs under 2p.

Two things keep it that cheap. Attribution is cached by route (see
attribute.py), and every published statistic is a **sum**, so a month is the
addition of its days and a year the addition of its months. Nothing is ever
recomputed from the raw data to produce a longer period.

Averages are deliberately not stored. A file carries services, services that
ran, summed delay and cancellations; the browser divides. Storing a mean would
make the rollups wrong.

Cancellation is recorded against the part of the journey that was actually
lost, not the whole route — see _record. A train curtailed at Reading is a
cancellation west of Reading and a late train east of it.

Output layout, under --output:

    index.json              what periods exist
    day/2026-09-04.json
    month/2026-09.json
    year/2026.json

Day files are kept for the current month, monthlies for a rolling year, and
years for good — see the retention constants below.

--timing-points buys sharper attribution at about ninety times the scan cost,
and is meant for backfills; the result is folded into the route cache so the
daily run never pays for it. See timing_points.py and README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
ROOT = HERE.parent

# Locally the shared module and queries live one level up; in the Lambda package
# they are bundled alongside the code.
if not (HERE / "common").is_dir():
    sys.path.insert(0, str(ROOT))

import timing_points  # noqa: E402
from common.aws import Athena, Output  # noqa: E402
from attribute import Network  # noqa: E402

QUERIES = HERE / "queries" if (HERE / "queries").is_dir() else ROOT / "queries"
REFERENCE = HERE / "reference"

# Retention. Day files exist for the current calendar month; once a month is
# complete its days are already summed into the monthly file and are dropped.
# Months survive a rolling year, then live on only inside their year file.
# Raise DAY_RETENTION_MONTHS to 2 if a day selector holding a single entry on
# the 1st of the month reads badly.
DAY_RETENTION_MONTHS = 1
MONTH_RETENTION_MONTHS = 12

# A normal day is around 23,500 services once Underground and Overground are
# excluded. The pipeline has failed in two ways that both look like a quiet day:
# a truncated partition holding 20-60 services, and a partition of normal row
# count in which every stops array is empty. The second collapses to zero here
# because a service with no calling points has no route. Refuse to publish
# either — a gap must stay a gap rather than render as a day on which nothing
# went wrong. See the known gaps table in the repository README.
#
# Set well below the baseline so that genuinely reduced days — Christmas, a
# strike — still publish. Skipped days are printed, so a real one is visible.
MIN_SERVICES = 12_000

ROUTE_CACHE = "route_sections.json.gz"

# Athena's price, for the running total a backfill prints.
DOLLARS_PER_TB = 5.0


# ---------------------------------------------------------------------------
# Accumulating one section's statistics
# ---------------------------------------------------------------------------
def _blank() -> dict[str, Any]:
    return {
        "s": 0,    # services attributed to this section
        "n": 0,    # of those, the ones that ran with a known delay
        "td": 0.0, # summed average delay over those, minutes
        "x": 0,    # cancelled
        "t": defaultdict(lambda: [0, 0, 0.0, 0]),  # per operator: the same four
        "dr": Counter(),  # delay reason code -> services
        "xr": Counter(),  # cancellation reason code -> services
        "h": Counter(),   # headcode prefix -> services
    }


def _reason(value: Any) -> str | None:
    """Darwin reason codes arrive as strings, sometimes with a decimal tail."""
    if not value:
        return None
    code = str(value).split(".")[0].strip()
    return code if code and code != "nan" else None


def _record(into: dict[str, Any], service: dict[str, Any], lost: bool) -> None:
    """Record one service against one section it was booked to run over.

    *lost* says whether this particular section is on the part of the journey
    that was cancelled. A service curtailed at Reading is a cancellation west of
    Reading and a normal, possibly late, train east of it, and counting it as
    either everywhere would be wrong.
    """
    toc = into["t"][service["toc"]]
    into["s"] += 1
    toc[0] += 1

    if lost:
        into["x"] += 1
        toc[3] += 1
        if service["cancel_reason"]:
            into["xr"][service["cancel_reason"]] += 1
    else:
        # avg_delay_mins covers the stops that were served, which is exactly the
        # part of the journey this branch is about. It is absent on a service
        # that ran nowhere.
        if service["delay"] is not None:
            into["n"] += 1
            into["td"] += service["delay"]
            toc[1] += 1
            toc[2] += service["delay"]
        if service["delay_reason"]:
            into["dr"][service["delay_reason"]] += 1

    if service["headcode"]:
        into["h"][service["headcode"]] += 1


def _encode(sections: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Freeze accumulators into the compact shape the browser reads."""
    out = {}
    for sid, agg in sections.items():
        entry: dict[str, Any] = {
            "s": agg["s"],
            "n": agg["n"],
            "td": round(agg["td"], 1),
            "x": agg["x"],
            "t": {
                toc: [v[0], v[1], round(v[2], 1), v[3]]
                for toc, v in sorted(agg["t"].items())
            },
        }
        for key in ("dr", "xr", "h"):
            if agg[key]:
                entry[key] = dict(agg[key].most_common())
        out[sid] = entry
    return out


def _decode(sections: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The inverse, so a published file can be added to another one."""
    out: dict[str, dict[str, Any]] = {}
    for sid, entry in sections.items():
        agg = _blank()
        agg["s"], agg["n"], agg["td"], agg["x"] = (
            entry["s"], entry["n"], entry["td"], entry["x"],
        )
        for toc, v in entry.get("t", {}).items():
            agg["t"][toc] = list(v)
        for key in ("dr", "xr", "h"):
            agg[key] = Counter(entry.get(key, {}))
        out[sid] = agg
    return out


def _add(base: dict[str, dict[str, Any]], extra: dict[str, dict[str, Any]]) -> None:
    """Add one period's sections into another's, in place."""
    for sid, src in extra.items():
        dst = base.get(sid)
        if dst is None:
            dst = base[sid] = _blank()
        dst["s"] += src["s"]
        dst["n"] += src["n"]
        dst["td"] += src["td"]
        dst["x"] += src["x"]
        for toc, v in src["t"].items():
            target = dst["t"][toc]
            for i in range(4):
                target[i] += v[i]
        for key in ("dr", "xr", "h"):
            dst[key].update(src[key])


# ---------------------------------------------------------------------------
# Reading a day out of Athena
# ---------------------------------------------------------------------------
def fetch_day(athena: Athena, day: date) -> list[dict[str, Any]]:
    sql = (QUERIES / "tracks_routes.sql").read_text().format(
        date_filter=f"n.year = '{day:%Y}' AND n.month = '{day:%m}' AND n.day = '{day:%d}'"
    )
    services = []
    for row in athena.query(sql):
        route = (row["route"] or "").strip()
        if not route:
            continue
        train_id = (row["train_id"] or "").strip()
        try:
            delay = float(row["avg_delay_mins"])
        except (TypeError, ValueError):
            delay = None
        dropped = (row["cancelled_route"] or "").strip()
        services.append({
            "rid": row["rid"],
            "route": tuple(route.split(",")),
            "dropped": tuple(dropped.split(",")) if dropped else (),
            "status": row["cancellation_status"] or "",
            "toc": row["toc"] or "??",
            "headcode": train_id[:2] if len(train_id) >= 2 else None,
            "delay": delay,
            "delay_reason": _reason(row["delay_reason"]),
            "cancel_reason": _reason(row["cancel_reason"]),
        })
    return services


# ---------------------------------------------------------------------------
# Building one day
# ---------------------------------------------------------------------------
def load_network() -> Network:
    track = json.loads((REFERENCE / "track_sections.json").read_text())
    crs = json.loads((REFERENCE / "crs.json").read_text())
    return Network(track["sections"], track["tiploc_to_sections"], crs)


def route_key(route: tuple[str, ...], dropped: bool = False) -> str:
    """Cache key for a route. The cancelled leg of a journey is attributed
    without pass-through enrichment, so it is kept in a separate key space to
    avoid ever being answered with the enriched version of the same stops."""
    prefix = "cancelled:" if dropped else ""
    return hashlib.md5((prefix + ",".join(route)).encode()).hexdigest()


def build_day(
    services: list[dict[str, Any]],
    network: Network,
    cache: dict[str, str],
    passed: dict[str, set[str]] | None = None,
) -> tuple[dict[str, Any], int]:
    """Aggregate a day's services onto sections. Returns (sections, routes solved).

    Normally the cache answers everything and only genuinely new routes are
    attributed. Given *passed* — the timing points each service ran through,
    which only a backfill pays for — every route is re-solved with that sharper
    input and the answer merged into what the cache already holds. Merging
    rather than replacing is deliberate: a service's timing points can be
    incomplete on any given day, so the union across the days a route ran is the
    fullest picture of where it went.
    """
    sections: dict[str, dict[str, Any]] = {}
    solved = 0

    def resolve(route: tuple[str, ...], through: frozenset[str], dropped: bool) -> list[str]:
        nonlocal solved
        key = route_key(route, dropped)
        hit = cache.get(key)

        if hit is not None and (through is None or dropped):
            return hit.split(",") if hit else []

        found = set(network.sections_for_route(route, through or frozenset()))
        if hit:
            found |= set(hit.split(","))
        joined = ",".join(sorted(found))
        if joined != hit:
            cache[key] = joined
            solved += 1
        return joined.split(",") if joined else []

    for service in services:
        through = frozenset(passed.get(service["rid"], ())) if passed is not None else None
        sids = resolve(service["route"], through, False)

        # Which of those sections the service never reached. A wholly cancelled
        # service occasionally arrives with no per-stop flags set at all; it ran
        # nowhere, so the whole route counts as lost.
        if service["dropped"]:
            lost = set(resolve(service["dropped"], None, True))
        elif service["status"] == "cancelled":
            lost = set(sids)
        else:
            lost = set()

        for sid in sids:
            agg = sections.get(sid)
            if agg is None:
                agg = sections[sid] = _blank()
            _record(agg, service, sid in lost)

    return sections, solved


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
def _read(output: Output, kind: str, key: str) -> dict[str, Any] | None:
    raw = output.read(f"{kind}/{key}.json")
    return json.loads(raw) if raw else None


def _write(
    output: Output,
    kind: str,
    key: str,
    days: list[str],
    services: int,
    sections: dict[str, dict[str, Any]],
) -> None:
    payload = {
        "kind": kind,
        "key": key,
        "start": min(days),
        "end": max(days),
        "days": days,
        "services": services,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sections": _encode(sections),
    }
    output.write(f"{kind}/{key}.json", json.dumps(payload, separators=(",", ":")))


def upsert(
    output: Output,
    kind: str,
    key: str,
    day_key: str,
    services: int,
    sections: dict[str, dict[str, Any]],
) -> None:
    """Add one day into a rolling period, unless it is already counted.

    The days list is what makes this idempotent: re-running a day that is
    already in the file leaves it alone rather than double-counting it. Use
    --rebuild to correct one that was wrong.
    """
    existing = _read(output, kind, key)
    if existing and day_key in existing["days"]:
        return

    if existing:
        total = _decode(existing["sections"])
        _add(total, sections)
        days = sorted(existing["days"] + [day_key])
        count = existing["services"] + services
    else:
        total = {}
        _add(total, sections)
        days, count = [day_key], services

    _write(output, kind, key, days, count, total)


def rebuild(output: Output, kind: str, key: str) -> bool:
    """Recompute a period from the files one level below it.

    Only possible while those still exist — a month can be rebuilt from its days
    for as long as they are retained, a year from its months for a rolling year.
    Beyond that, re-run the days through Athena.
    """
    child = "day" if kind == "month" else "month"
    keys = sorted(
        name[len(child) + 1: -len(".json")]
        for name in output.list(f"{child}/")
        if name.endswith(".json")
    )
    parts = [k for k in keys if k.startswith(key)]
    if not parts:
        return False

    total: dict[str, dict[str, Any]] = {}
    days: list[str] = []
    services = 0
    for part in parts:
        payload = _read(output, child, part)
        if not payload:
            continue
        _add(total, _decode(payload["sections"]))
        days.extend(payload["days"])
        services += payload["services"]

    if not days:
        return False
    _write(output, kind, key, sorted(days), services, total)
    return True


# ---------------------------------------------------------------------------
# Retention and the manifest
# ---------------------------------------------------------------------------
def _months_before(key: str, count: int) -> str:
    """The YYYY-MM that is *count* months earlier than *key*."""
    year, month = int(key[:4]), int(key[5:7])
    total = year * 12 + (month - 1) - count
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _keys(output: Output, kind: str) -> list[str]:
    return sorted(
        name[len(kind) + 1: -len(".json")]
        for name in output.list(f"{kind}/")
        if name.endswith(".json")
    )


def prune(output: Output) -> None:
    """Drop periods that have been rolled up into a coarser one.

    Cut-offs are measured from the newest data present rather than from today,
    so a backfill does not delete what it has just written.
    """
    days = _keys(output, "day")
    months = _keys(output, "month")

    if days:
        cutoff = _months_before(days[-1][:7], DAY_RETENTION_MONTHS - 1)
        for key in days:
            if key[:7] < cutoff:
                output.delete(f"day/{key}.json")

    if months:
        cutoff = _months_before(months[-1], MONTH_RETENTION_MONTHS - 1)
        for key in months:
            if key < cutoff:
                output.delete(f"month/{key}.json")


def write_index(output: Output) -> dict[str, Any]:
    days = _keys(output, "day")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest_day": days[-1] if days else None,
        "days": days,
        "months": _keys(output, "month"),
        "years": _keys(output, "year"),
    }
    output.write("index.json", json.dumps(manifest, separators=(",", ":")))
    return manifest


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------
class Gap(Exception):
    """The day is missing or unusable upstream. Publish nothing for it."""


def run(
    athena: Athena,
    output: Output,
    state: Output,
    network: Network,
    day: date,
    raw: Athena | None = None,
    cache: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build one day. Pass *raw* to also read timing points — see timing_points.

    *cache* lets a backfill hold the route cache in memory across days instead
    of reading and rewriting it several hundred times.
    """
    services = fetch_day(athena, day)
    if len(services) < MIN_SERVICES:
        raise Gap(
            f"{len(services):,} services with stops — expected at least "
            f"{MIN_SERVICES:,}. Treating {day:%Y-%m-%d} as a pipeline gap."
        )

    owned = cache is None
    if owned:
        cache = state.read_gzip_json(ROUTE_CACHE) or {}
    before = len(cache)

    # The timing-point query costs about ninety times the rest of the run, so
    # it is skipped when every route this day ran is already attributed. That
    # makes re-running a backfill nearly free.
    passed = None
    if raw is not None and any(route_key(s["route"]) not in cache for s in services):
        passed = timing_points.fetch(raw, day)
    sections, solved = build_day(services, network, cache, passed)
    if owned and (solved or len(cache) != before):
        state.write_gzip_json(ROUTE_CACHE, cache)

    day_key = f"{day:%Y-%m-%d}"
    _write(output, "day", day_key, [day_key], len(services), sections)
    upsert(output, "month", day_key[:7], day_key, len(services), sections)
    upsert(output, "year", day_key[:4], day_key, len(services), sections)

    prune(output)
    write_index(output)

    return {
        "date": day_key,
        "services": len(services),
        "sections": len(sections),
        "routes_solved": solved,
        "cached_routes": len(cache),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entrypoint. Builds yesterday unless the event names a date.

    Raises on a missing partition rather than publishing a zero. A dashboard
    that quietly stops updating is the failure this project already lived
    through; a failed invocation is visible.
    """
    day = (
        date.fromisoformat(event["date"])
        if isinstance(event, dict) and event.get("date")
        else date.today() - timedelta(days=1)
    )
    athena = Athena(
        database=os.environ.get("ATHENA_DATABASE", "uk_rail"),
        workgroup=os.environ["ATHENA_WORKGROUP"],
        results=os.environ.get("ATHENA_RESULTS", ""),
        region=os.environ.get("AWS_REGION", "eu-west-1"),
    )
    summary = run(
        athena,
        Output(os.environ["OUTPUT_LOCATION"]),
        Output(os.environ["STATE_LOCATION"]),
        load_network(),
        day,
    )
    print(json.dumps(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Service day to build, YYYY-MM-DD. Defaults to yesterday.")
    parser.add_argument(
        "--backfill",
        nargs=2,
        metavar=("START", "END"),
        help="Build every day in a range. Skips gaps rather than failing on them.",
    )
    parser.add_argument(
        "--rebuild",
        metavar="PERIOD",
        help="Recompute one YYYY-MM or YYYY from the files below it, then stop.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "site" / "data" / "tracks"),
        help="Directory or s3://bucket/prefix for the JSON files.",
    )
    parser.add_argument(
        "--state",
        default=str(ROOT / ".cache"),
        help="Directory or s3://bucket/prefix for the route cache.",
    )
    parser.add_argument("--database", default="uk_rail")
    parser.add_argument(
        "--timing-points",
        action="store_true",
        help="Also read the points each service passes through, and fold them into "
             "the route cache. Roughly 90x the scan cost, so this is for backfills "
             "and periodic refreshes, not the daily run. See timing_points.py.",
    )
    parser.add_argument(
        "--raw-database",
        default="",
        help="Database holding services_v1 and locations_v1, for --timing-points. "
             "Defaults to --database.",
    )
    parser.add_argument("--workgroup", default="primary")
    parser.add_argument("--region", default="eu-west-1")
    parser.add_argument(
        "--results",
        default="",
        help="S3 location for Athena query results. Omit if the workgroup sets its own.",
    )
    args = parser.parse_args()

    output = Output(args.output)

    if args.rebuild:
        kind = "month" if len(args.rebuild) == 7 else "year"
        if not rebuild(output, kind, args.rebuild):
            print(f"nothing below {args.rebuild} to rebuild from", file=sys.stderr)
            return 1
        write_index(output)
        print(f"rebuilt {kind} {args.rebuild}")
        return 0

    athena = Athena(args.database, args.workgroup, args.results, args.region)
    raw = (
        Athena(args.raw_database or args.database, args.workgroup, args.results, args.region)
        if args.timing_points
        else None
    )
    state = Output(args.state)
    network = load_network()

    days = []
    if args.backfill:
        day = date.fromisoformat(args.backfill[0])
        end = date.fromisoformat(args.backfill[1])
        while day <= end:
            days.append(day)
            day += timedelta(days=1)
    else:
        days = [date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)]

    # A backfill holds the cache open across every day rather than reading and
    # rewriting it hundreds of times, and saves it as it goes so an interrupted
    # run does not throw away the attribution it has already paid for.
    cache = state.read_gzip_json(ROUTE_CACHE) or {} if args.backfill else None

    failed = 0
    scanned = 0
    for day in days:
        try:
            summary = run(athena, output, state, network, day, raw, cache)
            scanned += athena.bytes_scanned + (raw.bytes_scanned if raw else 0)
            print(f"{summary['date']}  {summary['services']:>6,} services  "
                  f"{summary['sections']:>5,} sections  "
                  f"{summary['routes_solved']:>6,} routes solved  "
                  f"{summary['cached_routes']:>7,} cached  "
                  f"${scanned / 1e12 * DOLLARS_PER_TB:>5.2f}")
        except Gap as exc:
            print(f"{day:%Y-%m-%d}  gap — {exc}")
        except Exception as exc:  # noqa: BLE001 — see below
            # A single day failing is not a reason to lose a run that has
            # already paid for hundreds of others. Report it, keep the cache,
            # carry on; the day can be rebuilt for $0.00005. A one-off run
            # still fails loudly, and so does the Lambda.
            print(f"{day:%Y-%m-%d}  FAILED — {type(exc).__name__}: {exc}", file=sys.stderr)
            failed += 1
            if not args.backfill:
                raise
        if cache is not None:
            state.write_gzip_json(ROUTE_CACHE, cache)

    print(f"-> {output}   {scanned / 1e9:,.1f} GB scanned, "
          f"${scanned / 1e12 * DOLLARS_PER_TB:.2f}"
          + (f", {failed} day(s) failed" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
