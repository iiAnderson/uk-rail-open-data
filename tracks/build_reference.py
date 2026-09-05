"""Build the map's static reference files. Run this by hand, rarely.

Two outputs, both derived from things that change on the timescale of the
railway rather than the timetable:

  site/tracks/geometry.json    the drawn network — one polyline per track
                               section, plus station and reason-code labels.
                               Committed, served with the site, ~500 KB.

  tracks/reference/crs.json    TIPLOC -> CRS, so the daily job never has to
                               query the tiplocs table at runtime.

Run it again when the track geometry changes or the station reference data is
corrected — not otherwise.

    python tracks/build_reference.py --workgroup uk-rail-dashboard-aggregate
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from common.aws import Athena  # noqa: E402

REFERENCE = HERE / "reference"
TRACK_SECTIONS = REFERENCE / "track_sections.json"
CRS_OVERRIDES = REFERENCE / "crs_overrides.json"
REASON_CODES = ROOT / "aggregate" / "reason_codes.json"

# Every station name in the source data ends this way. The map has no room for it.
NAME_SUFFIXES = (" Rail Station", " Station")

STATIONS_SQL = """
SELECT tiploc_code, crs_code, station_name
FROM tiplocs
WHERE tiploc_code <> '' AND crs_code <> ''
"""


def tidy(name: str) -> str:
    for suffix in NAME_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def build(athena: Athena) -> tuple[dict, dict[str, str]]:
    track = json.loads(TRACK_SECTIONS.read_text())
    overrides = json.loads(CRS_OVERRIDES.read_text())

    rows = athena.query(STATIONS_SQL)
    crs: dict[str, str] = {}
    names: dict[str, str] = {}
    for row in rows:
        tpl = (row["tiploc_code"] or "").strip()
        crs[tpl] = (row["crs_code"] or "").strip()
        names[tpl] = tidy((row["station_name"] or "").strip())

    for tpl in overrides["drop"]:
        crs.pop(tpl, None)
    crs.update(overrides["phantom"])

    sections = [
        {"k": s["id"], "c": s["coords"], "tpls": s["tiplocs"]}
        for s in track["sections"]
    ]

    # Only the stations the map can actually label are worth shipping.
    referenced = {tpl for s in sections for tpl in s["tpls"]}

    geometry = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sections": sections,
        "names": {t: names[t] for t in sorted(referenced) if t in names},
        "reasons": json.loads(REASON_CODES.read_text()),
    }
    return geometry, crs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="uk_rail")
    parser.add_argument("--workgroup", default="primary")
    parser.add_argument("--region", default="eu-west-1")
    parser.add_argument(
        "--results",
        default="",
        help="S3 location for Athena query results. Omit if the workgroup sets its own.",
    )
    args = parser.parse_args()

    geometry, crs = build(
        Athena(args.database, args.workgroup, args.results, args.region)
    )

    out = ROOT / "site" / "tracks" / "geometry.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(geometry, separators=(",", ":")))
    (REFERENCE / "crs.json").write_text(json.dumps(crs, separators=(",", ":"), sort_keys=True))

    unnamed = sum(1 for s in geometry["sections"] for t in s["tpls"] if t not in geometry["names"])
    print(f"{len(geometry['sections']):,} sections, "
          f"{len(geometry['names']):,} station names ({unnamed} TIPLOCs unnamed), "
          f"{len(crs):,} CRS mappings")
    print(f"  {out}  {out.stat().st_size / 1024:,.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
