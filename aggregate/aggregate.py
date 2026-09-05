"""Build the dashboard's JSON files from Athena.

One run covers one service day. It scans a single partition of normalised_v1
(about 27 MB including the reference tables), so a day costs a fraction of a
penny and the whole thing is designed to run once, unattended, overnight.

Locally:

    python aggregate.py --date 2026-05-16 --results s3://my-bucket/athena/

Straight to a site bucket, which is what the Lambda does:

    python aggregate.py --output s3://my-site-bucket/data --results s3://...

Trend history is accumulated rather than recomputed: each run upserts one point
into trend.json and leaves the rest alone, so the cost of a run does not grow
with the length of the series. Use --backfill to populate it the first time.

    python aggregate.py --backfill 2026-03-18 2026-05-16 --results s3://...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent

# Locally the shared module lives one level up; in the Lambda package it is
# bundled alongside the code. Make both importable.
if not (HERE / "common").is_dir():
    sys.path.insert(0, str(HERE.parent))

from common.aws import Athena, Output  # noqa: E402

# Locally the queries live two levels up; in the Lambda package they are bundled
# alongside the code.
QUERIES = HERE / "queries" if (HERE / "queries").is_dir() else HERE.parent / "queries"

# Only FY2024/25 journey volumes are published. They weight relative demand
# between station pairs; they are not a current traffic estimate. See DATA.md.
ODM_FINANCIAL_YEAR = "20242025"

# A cancelled leg is charged the wait for the next service on that pair:
# operating day divided by services that day, capped. 05:00-23:00 = 1080 minutes.
OPERATING_DAY_MINS = 1080
WAIT_CAP_MINS = 120

# Coverage guard. If dividing a pair's daily demand by the services carrying it
# implies more passengers than a train can hold, the service count is wrong and
# the pair is dropped. See the comment in queries/_base_passenger_hours.sql.
MAX_TRAIN_LOAD = 1000

TOC_NAMES: dict[str, str] = json.loads((HERE / "toc_names.json").read_text())

# Darwin reports delay and cancellation reasons as numeric codes. The same code
# space is used for both, so a code alone does not tell you whether the service
# ran — that comes from cancellation_status.
REASON_CODES: dict[str, str] = json.loads((HERE / "reason_codes.json").read_text())


def reason_text(code: str | None) -> str:
    """Turn a Darwin reason code into readable text."""
    if not code or code == "Not stated":
        return "Not stated"
    return REASON_CODES.get(str(code).strip(), f"Reason code {code}")


def load_sql(name: str, day: date) -> str:
    """Read an aggregation query and prepend the shared base CTEs."""
    base = (QUERIES / "_base_passenger_hours.sql").read_text()
    tail = (QUERIES / f"{name}.sql").read_text()

    # Strip leading comment lines from the tail so the two files join cleanly.
    tail_body = "\n".join(
        line for line in tail.splitlines() if not line.strip().startswith("--")
    ).strip()

    date_filter = f"n.year = '{day:%Y}' AND n.month = '{day:%m}' AND n.day = '{day:%d}'"
    sql = f"{base}\n{tail_body}"
    return sql.format(
        date_filter=date_filter,
        odm_financial_year=ODM_FINANCIAL_YEAR,
        operating_day_mins=OPERATING_DAY_MINS,
        wait_cap_mins=WAIT_CAP_MINS,
        max_train_load=MAX_TRAIN_LOAD,
    )


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def national_hours(athena: Athena, day: date) -> dict[str, Any]:
    """Just the headline totals — used by --backfill, which needs nothing else."""
    rows = athena.query(load_sql("national", day))
    if not rows:
        return {}
    row = rows[0]
    return {
        "passenger_hours": round(_f(row["passenger_hours"])),
        "hours_delays": round(_f(row["hours_delays"])),
        "hours_cancellations": round(_f(row["hours_cancellations"])),
        "services": int(_f(row["services"])),
        "excluded_pairs": int(_f(row.get("excluded_pairs"))),
        "excluded_journeys": round(_f(row.get("excluded_journeys"))),
    }


def operator_hours(athena: Athena, day: date) -> list[dict[str, Any]]:
    """Per-operator totals, ranked. Also feeds the sparkline history."""
    return [
        {
            "toc": row["toc"],
            "name": TOC_NAMES.get(row["toc"], row["toc"]),
            "hours": round(_f(row["passenger_hours"])),
            "per_1k": round(_f(row["hours_per_1k_journeys"]), 1),
        }
        for row in athena.query(load_sql("by_operator", day))
    ]


def build_day(athena: Athena, day: date) -> dict[str, Any]:
    """Everything the dashboard needs for one service day."""
    totals = national_hours(athena, day)
    if not totals or not totals["passenger_hours"]:
        raise RuntimeError(f"no data for {day:%Y-%m-%d} — has the partition been written?")

    operators = operator_hours(athena, day)

    stations = [
        {
            "crs": row["crs"],
            "name": (row["station_name"] or row["crs"]).replace(" Rail Station", ""),
            "hours": round(_f(row["passenger_hours"])),
        }
        for row in athena.query(load_sql("by_station", day))
    ]

    reasons = [
        {
            "code": row["reason"],
            "reason": reason_text(row["reason"]),
            "hours": round(_f(row["passenger_hours"])),
            "pct": round(_f(row["pct_of_hours"]), 1),
        }
        for row in athena.query(load_sql("by_reason", day))
    ]

    worst_rows = athena.query(load_sql("worst_service", day))
    worst = {}
    if worst_rows:
        row = worst_rows[0]
        worst = {
            "rid": row["rid"],
            "train_id": row.get("train_id"),
            "toc": row["toc"],
            "toc_name": TOC_NAMES.get(row["toc"], row["toc"]),
            "origin": (row.get("origin_name") or "").replace(" Rail Station", ""),
            "destination": (row.get("destination_name") or "").replace(" Rail Station", ""),
            "sched_dep": row.get("origin_sched_dep"),
            "status": row.get("cancellation_status"),
            "hours": round(_f(row["passenger_hours"])),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "service_date": f"{day:%Y-%m-%d}",
        **totals,
        "operators": operators[:10],
        "operators_other": {
            "count": max(0, len(operators) - 10),
            "hours": round(sum(_f(o["hours"]) for o in operators[10:])),
        },
        "stations": stations[:8],
        "reasons": reasons[:8],
        "reasons_other": {
            "count": max(0, len(reasons) - 8),
            "pct": round(sum(_f(r["pct"]) for r in reasons[8:]), 1),
        },
        "worst_service": worst,
        "method": {
            "odm_financial_year": ODM_FINANCIAL_YEAR,
            "operating_day_mins": OPERATING_DAY_MINS,
            "wait_cap_mins": WAIT_CAP_MINS,
            "max_train_load": MAX_TRAIN_LOAD,
        },
    }


def upsert_trend(
    output: Output,
    day: date,
    hours: int,
    operators: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Add or replace one point in the trend series, keeping it sorted.

    Each point carries the national total and, where known, the per-operator
    split — which is what the sparklines in the operator table are drawn from.
    Days with no hours are treated as pipeline gaps and left out entirely, so a
    missing partition never renders as a day on which nothing went wrong.
    """
    existing = output.read("trend.json")
    days: list[dict[str, Any]] = json.loads(existing)["days"] if existing else []

    key = f"{day:%Y-%m-%d}"
    days = [d for d in days if d["d"] != key]
    if hours:
        point: dict[str, Any] = {"d": key, "h": hours}
        if operators:
            point["toc"] = {o["toc"]: o["hours"] for o in operators}
        days.append(point)
    days.sort(key=lambda d: d["d"])

    output.write("trend.json", json.dumps({"days": days}, separators=(",", ":")))
    return days


def rolling_average(days: list[dict[str, Any]], upto: date, window: int) -> float:
    key = f"{upto:%Y-%m-%d}"
    history = [d["h"] for d in days if d["d"] <= key][-window:]
    return sum(history) / len(history) if history else 0.0


def run(athena: Athena, output: Output, day: date) -> dict[str, Any]:
    """Build one day and write both files. Shared by the CLI and the Lambda."""
    payload = build_day(athena, day)

    days = upsert_trend(output, day, payload["passenger_hours"], payload["operators"])
    avg_28 = rolling_average(days, day, 28)
    payload["avg_7d"] = round(rolling_average(days, day, 7))
    payload["avg_28d"] = round(avg_28)
    payload["delta_28d_pct"] = round((payload["passenger_hours"] / avg_28 - 1) * 100, 1) if avg_28 else 0.0

    output.write("latest.json", json.dumps(payload, indent=1))
    return payload


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entrypoint. Builds yesterday unless the event names a date.

    Deliberately raises when the partition is missing. A dashboard that quietly
    stops updating is the failure this project already lived through; a failed
    invocation is visible in CloudWatch and can be alarmed on.
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
    payload = run(athena, Output(os.environ["OUTPUT_LOCATION"]), day)
    print(f"{day:%Y-%m-%d}  {payload['passenger_hours']:,} passenger-hours "
          f"({payload['delta_28d_pct']:+.1f}% vs 28-day average)")
    return {
        "service_date": payload["service_date"],
        "passenger_hours": payload["passenger_hours"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Service day to build, YYYY-MM-DD. Defaults to yesterday.")
    parser.add_argument(
        "--backfill",
        nargs=2,
        metavar=("START", "END"),
        help="Fill the trend series between two dates. Writes trend.json only.",
    )
    parser.add_argument(
        "--output",
        default=str(HERE.parent / "site" / "data"),
        help="Directory or s3://bucket/prefix for the JSON files.",
    )
    parser.add_argument("--database", default="uk_rail")
    parser.add_argument("--workgroup", default="primary")
    parser.add_argument("--region", default="eu-west-1")
    parser.add_argument(
        "--results",
        default="",
        help="S3 location for Athena query results. Omit if the workgroup sets its own.",
    )
    args = parser.parse_args()

    athena = Athena(args.database, args.workgroup, args.results, args.region)
    output = Output(args.output)

    if args.backfill:
        start = date.fromisoformat(args.backfill[0])
        end = date.fromisoformat(args.backfill[1])
        day = start
        while day <= end:
            try:
                totals = national_hours(athena, day)
                if totals and totals["passenger_hours"]:
                    upsert_trend(output, day, totals["passenger_hours"], operator_hours(athena, day))
                    print(f"{day:%Y-%m-%d}  {totals['passenger_hours']:>9,} h")
                else:
                    print(f"{day:%Y-%m-%d}        gap — no rows for this partition")
            except RuntimeError as exc:
                print(f"{day:%Y-%m-%d}  {exc}", file=sys.stderr)
            day += timedelta(days=1)
        return 0

    day = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    payload = run(athena, output, day)
    print(f"{day:%Y-%m-%d}  {payload['passenger_hours']:,} passenger-hours  "
          f"({payload['delta_28d_pct']:+.1f}% vs 28-day average)  ->  {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
