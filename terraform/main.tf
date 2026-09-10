locals {
  bucket_name = var.project_name
  use_domain  = var.domain_name != ""

  # Framing is off unless someone is named. See the headers policy below.
  allow_framing = length(var.frame_ancestors) > 0
  tags          = merge({ Project = var.project_name }, var.tags)
}

# ---------------------------------------------------------------------------
# Origin bucket
#
# Private in every respect. The site is served through CloudFront, which reaches
# the bucket with Origin Access Control; nothing needs public access, and no ACLs
# are used at all.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "site" {
  bucket = local.bucket_name
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket = aws_s3_bucket.site.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    # Disables ACLs entirely. Access is governed by the bucket policy alone.
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ---------------------------------------------------------------------------
# CloudFront
# ---------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.project_name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "site" {
  name = "${var.project_name}-security-headers"

  security_headers_config {
    content_type_options { override = true }

    # X-Frame-Options has no way to name a cross-origin embedder, so when
    # framing is allowed it is dropped in favour of CSP frame-ancestors, which
    # can. Only that one directive is set, so nothing else on the page is
    # constrained by the policy.
    dynamic "frame_options" {
      for_each = local.allow_framing ? [] : [1]

      content {
        frame_option = "DENY"
        override     = true
      }
    }

    dynamic "content_security_policy" {
      for_each = local.allow_framing ? [1] : []

      content {
        content_security_policy = "frame-ancestors ${join(" ", var.frame_ancestors)}"
        override                = true
      }
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }

    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
  }
}

# Extension-less URLs are rewritten to the .html behind them. See the comment
# in pretty-urls.js for why this is a rewrite and deliberately not a redirect.
resource "aws_cloudfront_function" "pretty_urls" {
  name    = "${var.project_name}-pretty-urls"
  runtime = "cloudfront-js-2.0"
  comment = "Serve /tracks from /tracks.html without redirecting"
  publish = true
  code    = file("${path.module}/pretty-urls.js")
}

resource "aws_cloudfront_distribution" "site" {
  enabled         = true
  is_ipv6_enabled = true
  # The function rewrites "/" before this is consulted, so it is belt and
  # braces — but a stale index.html here would be misleading.
  default_root_object = "passenger-hours.html"
  price_class         = var.price_class
  aliases             = local.use_domain ? [var.domain_name] : []
  comment             = "${var.project_name} static site"
  tags                = local.tags

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "s3-${local.bucket_name}"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-${local.bucket_name}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # Explicit TTLs rather than a managed cache policy, so the caching
    # behaviour is readable in one place.
    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    min_ttl                    = 0
    default_ttl                = var.default_cache_seconds
    max_ttl                    = var.default_cache_seconds
    response_headers_policy_id = aws_cloudfront_response_headers_policy.site.id

    # Only the default behaviour needs this. Everything under /data/ carries an
    # extension already, so the function would be a no-op there.
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.pretty_urls.arn
    }
  }

  # The aggregation job rewrites these once a day. A short TTL is cheaper than
  # paying for an invalidation on every run.
  ordered_cache_behavior {
    path_pattern           = "/data/*"
    target_origin_id       = "s3-${local.bucket_name}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    min_ttl                    = 0
    default_ttl                = var.data_cache_seconds
    max_ttl                    = var.data_cache_seconds
    response_headers_policy_id = aws_cloudfront_response_headers_policy.site.id
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = local.use_domain ? false : true
    acm_certificate_arn            = local.use_domain ? var.acm_certificate_arn : null
    ssl_support_method             = local.use_domain ? "sni-only" : null
    minimum_protocol_version       = local.use_domain ? "TLSv1.2_2021" : null
  }
}

# Only this distribution may read the bucket.
data "aws_iam_policy_document" "site" {
  statement {
    sid       = "AllowCloudFrontRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket     = aws_s3_bucket.site.id
  policy     = data.aws_iam_policy_document.site.json
  depends_on = [aws_s3_bucket_public_access_block.site]
}
