# Deploying the site

Generic static-site hosting: a private S3 bucket behind CloudFront. Nothing here
is specific to this project — point it at any directory of static files.

```bash
cp terraform.tfvars.example terraform.tfvars   # set project_name at minimum
terraform init
terraform apply
aws s3 sync ../site/ "s3://$(terraform output -raw bucket_name)/" --delete
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

CloudFront's free tier covers 1 TB out and 10 million requests a month. For a
dashboard serving a 20 KB page and a 100 KB JSON file, expect the bill to be
rounding error — S3 storage on a few megabytes, plus the CloudFront requests.
`price_class` defaults to North America and Europe only.
