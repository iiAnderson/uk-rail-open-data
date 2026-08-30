"""Build the dashboard's JSON files from Athena.

One run covers one service day. It scans a single partition of normalised_v1
(about 6 MB), so a day costs a fraction of a penny and the whole thing is
designed to run once, overnight, from cron or a scheduled Lambda.

    python aggregate.py --date 2026-08-29 --results s3://my-bucket/athena/

Trend history is accumulated rather than recomputed: each run upserts one point
into data/trend.json and leaves the rest alone. Use --backfill to fill it in the
first time.

    python aggregate.py --backfill 2025-01-01 2026-08-29 --results s3://...
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import boto3

HERE = Path(__file__).parent
QUERIES = HERE.parent.parent / "queries"
DEFAULT_OUTPUT = HERE.parent / "data"

# Only FY2024/25 journey volumes are published. They weight relative demand
# between station pairs; they are not a current traffic estimate. See DATA.md.
ODM_FINANCIAL_YEAR = "20242025"

# A cancelled leg is charged the wait for the next service on that pair:
# operating day divided by services that day, capped. 05:00-23:00 = 1080 minutes.
OPERATING_DAY_MINS = 1080
WAIT_CAP_MINS = 120

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


class Athena:
    """Minimal synchronous Athena client."""

    def __init__(self, database: str, workgroup: str, results: str, region: str) -> None:
        self._client = boto3.client("athena", region_name=region)
        self._database = database
        self._workgroup = workgroup
        self._results = results

    def query(self, sql: str) -> list[dict[str, Any]]:
        execution_id = self._client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": self._database},
            WorkGroup=self._workgroup,
            ResultConfiguration={"OutputLocation": self._results},
        )["QueryExecutionId"]

        while True:
            execution = self._client.get_query_execution(QueryExecutionId=execution_id)
            state = execution["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(1)

        if state != "SUCCEEDED":
            reason = execution["QueryExecution"]["Status"].get("StateChangeReason", state)
            raise RuntimeError(f"Athena query {state}: {reason}")

        return list(self._rows(execution_id))

    def _rows(self, execution_id: str) -> Iterator[dict[str, Any]]:
        paginator = self._client.get_paginator("get_query_results")
        header: list[str] | None = None

        for page in paginator.paginate(QueryExecutionId=execution_id):
            rows = page["ResultSet"]["Rows"]
            if header is None:
                header = [c.get("VarCharValue", "") for c in rows[0]["Data"]]
                rows = rows[1:]
            for row in rows:
                values = [c.get("VarCharValue") for c in row["Data"]]
                yield dict(zip(header, values))


def load_sql(name: str, day: date) -> str:
    """Read an aggregation query and prepend the shared base CTEs."""
    base = (QUERIES / "_base_passenger_hours.sql").read_text()
    tail = (QUERIES / f"{name}.sql").read_text()

    # Strip leading comment lines from the tail so the two files join cleanly.
    tail_body = "\n".join(
        line for line in tail.splitlines() if not line.strip().startswith("--")
    ).strip()

    date_filter = (
        f"n.year = '{day:%Y}' AND n.month = '{day:%m}' AND n.day = '{day:%d}'"
    )
    sql = f"{base}\n{tail_body}"
    return sql.format(
        date_filter=date_filter,
        odm_financial_year=ODM_FINANCIAL_YEAR,
        operating_day_mins=OPERATING_DAY_MINS,
        wait_cap_mins=WAIT_CAP_MINS,
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
        },
    }


def upsert_trend(
    output: Path,
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
    path = output / "trend.json"
    days: list[dict[str, Any]] = []
    if path.exists():
        days = json.loads(path.read_text()).get("days", [])

    key = f"{day:%Y-%m-%d}"
    days = [d for d in days if d["d"] != key]
    if hours:
        point: dict[str, Any] = {"d": key, "h": hours}
        if operators:
            point["toc"] = {o["toc"]: o["hours"] for o in operators}
        days.append(point)
    days.sort(key=lambda d: d["d"])

    path.write_text(json.dumps({"days": days}, separators=(",", ":")))
    return days


def rolling_average(days: list[dict[str, Any]], upto: date, window: int) -> float:
    key = f"{upto:%Y-%m-%d}"
    history = [d["h"] for d in days if d["d"] <= key][-window:]
    return sum(history) / len(history) if history else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Service day to build, YYYY-MM-DD. Defaults to yesterday.")
    parser.add_argument(
        "--backfill",
        nargs=2,
        metavar=("START", "END"),
        help="Fill the trend series between two dates. Writes trend.json only.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Directory for the JSON files.")
    parser.add_argument("--database", default="uk_rail")
    parser.add_argument("--workgroup", default="primary")
    parser.add_argument("--region", default="eu-west-1")
    parser.add_argument(
        "--results",
        required=True,
        help="S3 location for Athena query results, e.g. s3://my-bucket/athena-results/",
    )
    args = parser.parse_args()

    athena = Athena(args.database, args.workgroup, args.results, args.region)
    args.output.mkdir(parents=True, exist_ok=True)

    if args.backfill:
        start = date.fromisoformat(args.backfill[0])
        end = date.fromisoformat(args.backfill[1])
        day = start
        while day <= end:
            try:
                totals = national_hours(athena, day)
                if totals and totals["passenger_hours"]:
                    operators = operator_hours(athena, day)
                    upsert_trend(args.output, day, totals["passenger_hours"], operators)
                    print(f"{day:%Y-%m-%d}  {totals['passenger_hours']:>9,} h")
                else:
                    print(f"{day:%Y-%m-%d}        gap — no rows for this partition")
            except RuntimeError as exc:
                print(f"{day:%Y-%m-%d}  {exc}", file=sys.stderr)
            day += timedelta(days=1)
        return 0

    day = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    payload = build_day(athena, day)

    days = upsert_trend(args.output, day, payload["passenger_hours"], payload["operators"])
    avg_7 = rolling_average(days, day, 7)
    avg_28 = rolling_average(days, day, 28)
    payload["avg_7d"] = round(avg_7)
    payload["avg_28d"] = round(avg_28)
    payload["delta_28d_pct"] = round((payload["passenger_hours"] / avg_28 - 1) * 100, 1) if avg_28 else 0.0

    (args.output / "latest.json").write_text(json.dumps(payload, indent=1))
    print(f"{day:%Y-%m-%d}  {payload['passenger_hours']:,} passenger-hours  "
          f"({payload['delta_28d_pct']:+.1f}% vs 28-day average)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
