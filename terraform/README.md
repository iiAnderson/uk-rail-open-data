# Deploying the site

Generic static-site hosting: a private S3 bucket behind CloudFront. Nothing here
is specific to this project — point it at any directory of static files.

```bash
cp terraform.tfvars.example terraform.tfvars   # set project_name at minimum
terraform init
terraform apply
CARTO_KEY=your_key ../deploy.sh
terraform output site_url
```

## What it creates

| Resource | Notes |
|---|---|
| S3 bucket | private, ACLs disabled, encrypted, versioned |
| CloudFront distribution | HTTPS only, compression on, IPv6 |
| Origin Access Control | the only thing permitted to read the bucket |
| Response headers policy | HSTS, `X-Content-Type-Options`, `frame-options: DENY` |
| Bucket policy | scoped to this distribution by `AWS:SourceArn` |

The bucket is **not** public. It blocks public ACLs and policies, sets
`BucketOwnerEnforced` so ACLs cannot be used at all, and is reachable only
through the distribution. If you are adapting an older static-site setup that
used `acl = "public-read"`, this is the pattern that replaced it.

## Caching

`/data/*` gets a 5 minute TTL; everything else an hour. The aggregation job
rewrites the JSON once a day, so a short TTL on that path is cheaper than paying
for an invalidation on every run. Both are variables.

## Custom domain

Set `domain_name` and `acm_certificate_arn`. The certificate must be in
**us-east-1** regardless of where the bucket lives — CloudFront only reads
certificates from that region. Point a DNS ALIAS/CNAME at the distribution
domain afterwards; this module does not manage DNS.

## Cost

CloudFront's free tier covers 1 TB out and 10 million requests a month. The
dashboard is a 20 KB page and a 100 KB JSON file; the map is heavier, about
600 KB of track geometry cached for an hour plus one period file per view.
Expect the bill to be rounding error either way — S3 storage on a few tens of
megabytes, plus the CloudFront requests. `price_class` defaults to North America
and Europe only.

Athena is the other line, and it is smaller: both jobs together scan under
20 MB a day, which is about **2p a year**.

## The daily aggregation job

Set `enable_aggregator = false` if you only want the hosting.

Otherwise `terraform apply` also deploys a Lambda that rebuilds
`data/latest.json` and `data/trend.json` every day at **17:00 UTC**, writing
straight into the site bucket. CloudFront caches `/data/*` for five minutes, so
the new figures appear shortly afterwards without an invalidation.

| Resource | Notes |
|---|---|
| Lambda | Python 3.12, 512 MB, 5 min timeout. boto3 is in the runtime, so the package is just the job, its lookups and the SQL — about 53 KB. |
| Athena workgroup | **requester pays enabled** — this is the setting that otherwise fails with an error that never mentions requester pays. Use it for your own queries too. |
| Results bucket | Private, encrypted, results deleted after 7 days. |
| EventBridge rule | `cron(0 17 * * ? *)`, override with `aggregate_schedule`. |
| Log group | 30 day retention. |

### Why a schedule and not an S3 event

The dataset bucket belongs to someone else. S3 event notifications only reach
the bucket owner's account, so an event trigger would work for exactly one
person. A schedule works for anyone, at the cost of having to pick a time late
enough that the day's partition has landed. 17:00 UTC leaves a wide margin.

### Query results do not go in the site bucket

They get their own private bucket. Putting Athena output in the bucket that
serves your public site publishes every query you have ever run — an easy
mistake, because it is the path of least resistance.

### Seed the trend before the first scheduled run

The dashboard's "vs 28-day average" needs history, and a fresh deployment has
none — the first run would show `+0.0%` against a single day. Populate it once:

```bash
python aggregate/aggregate.py \
  --backfill 2026-03-18 2026-05-16 \
  --output "s3://$(terraform -chdir=terraform output -raw bucket_name)/data" \
  --workgroup "$(terraform -chdir=terraform output -raw athena_workgroup)"
```

Then upload the page itself, which the Lambda never touches:

```bash
CARTO_KEY=your_key ./deploy.sh
```

`deploy.sh` is a sync with one substitution: `__CARTO_KEY__` in the HTML is
replaced with the basemap key on the way up. The key is not in the repository —
it ships in client-side JavaScript, so anyone viewing the map can read it, and
committing it would let anyone spend the quota. Deploying without `CARTO_KEY`
works fine; CARTO just stamps "API KEY REQUIRED" across the basemap tiles. Free
key, no account needed, at <https://carto.com/basemaps/apikey/>.

### Running it by hand

```bash
aws lambda invoke --function-name "$(terraform -chdir=terraform output -raw aggregate_function_name)" \
  --payload '{"date":"2026-05-16"}' --cli-binary-format raw-in-base64-out /dev/stdout
```

With no `date` it builds yesterday.

### When there is no data

The job **fails loudly** rather than writing an empty day. A dashboard that
quietly stops updating is worse than one that visibly breaks — this project ran
for 106 days with a dead upstream job before anyone noticed. If you want to hear
about it, alarm on the Lambda's `Errors` metric.

## The daily track-section map job

`enable_tracks` (default true) deploys a second Lambda, `<project>-tracks`,
which rebuilds `data/tracks/` every day at **17:30 UTC** — half an hour after
the aggregation job, for the same reason. It requires `enable_aggregator`,
whose Athena workgroup and results bucket it shares.

| Resource | Notes |
|---|---|
| Lambda | Python 3.12, 1024 MB, 10 min timeout. Larger than the aggregation job because attribution runs in Python and the first day after a timetable change does far more of it. The package carries the track geometry, about 700 KB. |
| IAM | Same as the aggregation job, plus delete on `data/tracks/*` — retention is part of the job — and read/write on `state/` in the results bucket. |
| Schedule | `tracks_schedule`, default `cron(30 17 * * ? *)`. |

### The route cache is not a query artefact

The job keeps `state/route_sections.json.gz` in the Athena results bucket. It is
accumulated attribution work, some of it bought with a scan ninety times the
price of a normal run, and losing it makes the job both slower and less
accurate. The expiry rule on that bucket is therefore scoped to `results/`.

If you move the cache elsewhere, keep it somewhere durable.

### Seed the map before the first scheduled run

The map has nothing to show until some history exists, and the daily job only
ever builds one day. Backfill it once, from a machine with credentials:

```bash
python tracks/tracks.py --backfill 2025-01-01 2026-09-04 \
    --timing-points --raw-database darwin-connect \
    --output s3://$(terraform output -raw bucket_name)/data/tracks \
    --state s3://$(terraform output -raw bucket_name)-athena-results/state \
    --workgroup $(terraform output -raw athena_workgroup)
```

That is about 280 GB scanned, or $1.40, and takes a few hours. `--timing-points`
is what makes it worth doing properly — see [tracks/README.md](../tracks/README.md).

### Running it by hand

```bash
aws lambda invoke --function-name $(terraform output -raw tracks_function_name) \
  --payload '{"date":"2026-09-04"}' --cli-binary-format raw-in-base64-out out.json
```
