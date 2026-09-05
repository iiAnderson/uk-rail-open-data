#!/usr/bin/env bash
#
# Publish the site.
#
# Everything under site/ is served as-is, except that __CARTO_KEY__ is replaced
# with the basemap key at upload time. The key is not in this repository: it
# ships in client-side JavaScript, so it is readable by anyone viewing the map,
# and committing it would let anyone spend the quota it belongs to.
#
#   CARTO_KEY=your_key ./deploy.sh
#
# Without CARTO_KEY the site still deploys and the map still works — CARTO just
# stamps "API KEY REQUIRED" across the basemap tiles. Get one free, no account
# needed, at https://carto.com/basemaps/apikey/
#
# data/ is NOT deployed. That prefix belongs to the Lambdas, which rewrite it
# daily; the copies under site/data/ are samples so the pages render locally.
# Syncing them up would revert the live figures to whatever was last committed,
# and --delete would remove any day the samples do not contain.

set -euo pipefail
cd "$(dirname "$0")"

BUCKET="${SITE_BUCKET:-$(terraform -chdir=terraform output -raw bucket_name)}"
DISTRIBUTION="${DISTRIBUTION_ID:-$(terraform -chdir=terraform output -raw distribution_id)}"
CARTO_KEY="${CARTO_KEY:-}"

if [ -z "$CARTO_KEY" ]; then
  echo "warning: CARTO_KEY not set — basemap tiles will carry a watermark" >&2
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R site/. "$STAGE"/

# perl rather than sed -i, which needs different arguments on BSD and GNU.
find "$STAGE" -name '*.html' -exec \
  perl -pi -e "s/__CARTO_KEY__/\Q$CARTO_KEY\E/g" {} +

if grep -rq '__CARTO_KEY__' "$STAGE"; then
  echo "error: placeholder still present after substitution" >&2
  exit 1
fi

aws s3 sync "$STAGE"/ "s3://$BUCKET/" --delete --exclude 'data/*'
echo "deployed to s3://$BUCKET/ (data/ left alone — the Lambdas own it)"

# The pages carry an hour-long TTL, so without this a deploy is invisible for up
# to an hour. Only the HTML needs it: /data/* has its own short TTL and is
# rewritten by the Lambdas, not by this script. The first 1,000 invalidation
# paths a month are free.
if [ -n "$DISTRIBUTION" ]; then
  ID=$(aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION"          --paths '/' '/index.html' '/tracks.html'          --query 'Invalidation.Id' --output text)
  echo "invalidating $DISTRIBUTION ($ID)"
  aws cloudfront wait invalidation-completed --distribution-id "$DISTRIBUTION" --id "$ID"
  echo "invalidation complete"
fi
