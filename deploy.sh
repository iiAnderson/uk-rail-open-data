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

set -euo pipefail
cd "$(dirname "$0")"

BUCKET="${SITE_BUCKET:-$(terraform -chdir=terraform output -raw bucket_name)}"
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

aws s3 sync "$STAGE"/ "s3://$BUCKET/" --delete
echo "deployed to s3://$BUCKET/"
