# Querying the dataset with Athena

Run the files in this directory in numeric order, in **eu-west-1**.

```bash
for f in athena/0*.sql; do
  aws athena start-query-execution \
    --query-string "$(cat "$f")" \
    --result-configuration OutputLocation=s3://YOUR-BUCKET/athena-results/ \
    --work-group primary
done
```

## The one thing that will catch you out

`s3://darwin-connect` is a **requester pays** bucket. Athena will not read one
unless the workgroup is configured to allow it, and the error you get when it is
not does not mention requester pays — it looks like a permissions problem.

Enable it on the workgroup:

```bash
aws athena update-work-group --work-group primary \
  --configuration-updates 'EnableRequesterPaysS3=true'
```

Or in the console: **Athena → Workgroups → edit → "Enable queries on Requester
Pays buckets in Amazon S3"**. For Athena for Spark it is a per-session setting
instead.

You also need `s3:GetObject` and `s3:ListBucket` on the bucket in your own IAM
policy — requester pays governs who is billed, not who is allowed.

## Partitions

`normalised_v1` has one partition per day. Rather than registering 600 of them,
`05_load_partitions.sql` shows how to switch the table to **partition
projection**, after which partitions resolve automatically and you never run
`ALTER TABLE` again. `MSCK REPAIR` does not work on Athena engine v3.

`odm_v1` has one partition per financial year and is registered explicitly.

## Cost

Athena charges $5 per TB scanned, with a 10 MB minimum per query.

| Query | Scans | Costs |
|---|---|---|
| One day of `normalised_v1` | 6 MB | $0.00005 |
| One month | 190 MB | $0.001 |
| The entire history | 2.7 GB | $0.014 |

The partition keys are what make this true. A query without a `year`/`month`/`day`
predicate scans everything.
