# UK Rail Open Data

Every train on the British rail network, every day, since January 2025 — as
queryable Parquet on S3, plus a worked example of what you can do with it.

The data comes from the National Rail **Darwin** feed: schedules, live estimates
and actual times for every service, collected continuously and normalised into
one row per train.

Two worked examples are published from it, rebuilt every morning: **passenger
hours**, the time the network takes from the people travelling on it, and the
**track-section map**, every service drawn onto the physical railway it runs
over — 2,641 sections, by day, month or year.

- **`athena/`** — table definitions. Run these in your own AWS account and start querying.
- **`queries/`** — worked examples, including the full passenger-hours metric.
- **`site/`** — the two pages. Everything here is served publicly; nothing else is.
- **`aggregate/`** — the daily job that builds the passenger-hours dashboard.
- **`tracks/`** — the daily job that builds the [track-section map](tracks/README.md).
- **`terraform/`** — deploy your own copy of the site, and the Lambdas that rebuild it daily.
- **`deploy.sh`** — publishes `site/`, substituting the basemap key that is deliberately not committed.

## The dataset

| | |
|---|---|
| Bucket | `s3://darwin-connect` (**requester pays**) |
| Region | `eu-west-1` |
| Coverage | 2025-01-01 onwards |
| Size | ~2.7 GB total for `normalised_v1`, ~6 MB per day |

**Requester pays** means you are billed for the requests and transfer, not the
publisher. In practice that is Athena's $5 per TB scanned. Scanning the entire
20-month history of `normalised_v1` costs **about 1.4 pence**.

### Tables

| Table | Grain | Use it for |
|---|---|---|
| `normalised_v1` | one row per service | almost everything — delays, cancellations, routes, loading |
| `odm_v1` | annual journeys per station pair | weighting by how many people actually travel |
| `tiplocs` | one row per station code | mapping TIPLOC to CRS, station names, coordinates |

`normalised_v1` carries a `stops` array with the scheduled and actual time at
every station a service called at, so you can filter by station without joining
anything.

## Quick start

```sql
-- The ten operators that lost their passengers the most time yesterday
SELECT toc, COUNT(*) AS services, ROUND(AVG(avg_delay_mins), 1) AS avg_delay
FROM uk_rail.normalised_v1
WHERE year = '2026' AND month = '05' AND day = '16'
  AND passenger = true AND cancellation_status = 'ran'
GROUP BY toc ORDER BY avg_delay DESC LIMIT 10;
```

Setup is four files in [`athena/`](athena/), run in order. **One thing will
catch you out**: Athena refuses to read requester-pays buckets unless the
workgroup allows it. See [`athena/README.md`](athena/README.md) — it is a single
checkbox, and the error message when it is off does not mention requester pays.

## Always filter by partition

`year`, `month` and `day` are partition keys. A query without them scans
everything. With them, a single day is 6 MB.

## Known gaps

The pipeline has not been perfect, and the gaps are not self-announcing — a day
with no rows looks exactly like a day on which nothing happened. Query around
these.

**Days absent entirely** (29 days):

| Range | Days |
|---|---|
| 2025-01-14 – 2025-01-18 | 5 |
| 2025-01-23 – 2025-01-31 | 9 |
| 2025-02-10 – 2025-02-14 | 5 |
| 2025-02-20 – 2025-02-24 | 5 |
| 2026-04-13 – 2026-04-15 | 3 |
| 2026-04-17 – 2026-04-18 | 2 |

**Days present but unusable:**

| Range | Problem |
|---|---|
| 2026-02-19 – 2026-03-17 | 27 days with services but **empty `stops` arrays**. Row counts look normal (~32k/day); every stop-level query returns nothing. |
| 2025-02-25, 2025-03-27, 2026-02-10 | badly truncated — 20 to 60 services instead of ~30,000 |
| 2025-12-25, 2025-12-26 | genuinely reduced service, but also incomplete |

Two cheap guards worth putting in your own queries:

```sql
-- a day whose stops never populated
HAVING SUM(CARDINALITY(stops)) > 0

-- a truncated day
HAVING COUNT(*) > 20000
```

## Licence

Code in this repository is MIT — see [LICENSE](LICENSE).

The **data is not covered by that licence**. It derives from National Rail
Enquiries under their open data terms, and carries its own attribution and use
conditions. See [DATA.md](DATA.md) before you redistribute it or build a product
on it.

Contains information from National Rail Enquiries.
