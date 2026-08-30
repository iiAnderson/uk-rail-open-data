# The aggregation job

Turns a day of `normalised_v1` into the two JSON files the dashboard reads.

```bash
pip install -r requirements.txt

python aggregate.py --date 2026-05-16 \
  --results s3://YOUR-BUCKET/athena-results/
```

Writes `../data/latest.json` and updates `../data/trend.json`.

## Design

**Nothing queries Athena at request time.** The page is static; the job runs once
a day and the browser fetches pre-built JSON. That is what keeps this near-free
to operate — no Lambda, no API Gateway, no query per page view.

**History accumulates rather than recomputing.** Each run adds one point to
`trend.json` and leaves the rest alone, so the cost of a run does not grow with
the length of the series. Use `--backfill` once to populate it:

```bash
python aggregate.py --backfill 2026-03-18 2026-05-16 --results s3://...
```

Each day is five queries scanning about 27 MB — roughly $0.0001, or under 5p to
backfill a year.

**Gaps stay gaps.** A day that returns no rows is skipped rather than recorded
as zero, so a pipeline failure never renders as a day on which nothing went
wrong. See [Known gaps](../../README.md#known-gaps).

## Running it daily

Any scheduler works. The job needs `athena:*Query*`, `glue:GetTable`, and S3 read
on the dataset plus write on your results bucket.

```cron
30 4 * * *  cd /srv/uk-rail && python site/aggregate/aggregate.py \
              --results s3://my-bucket/athena-results/ \
            && aws s3 sync site/ s3://my-site-bucket/ --delete
```

With no `--date` it builds yesterday.

## Files it uses

| File | Purpose |
|---|---|
| `../../queries/*.sql` | the metric itself |
| `toc_names.json` | operator code → name |
| `reason_codes.json` | Darwin reason code → text (507 codes) |

## Tuning the method

Constants at the top of `aggregate.py`:

| Constant | Default | Meaning |
|---|---|---|
| `ODM_FINANCIAL_YEAR` | `20242025` | which journey volumes to weight with |
| `OPERATING_DAY_MINS` | `1080` | service day length, 05:00–23:00 |
| `WAIT_CAP_MINS` | `120` | longest wait charged for a cancelled leg |
