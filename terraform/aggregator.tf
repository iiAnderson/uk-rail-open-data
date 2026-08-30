# ---------------------------------------------------------------------------
# The daily aggregation job.
#
# Runs on a schedule rather than off an S3 event. The dataset bucket belongs to
# someone else, and S3 event notifications only reach the bucket owner's
# account — a schedule is the only trigger that works for everyone deploying
# this. It runs well after the upstream normalisation job so the day's
# partition is there by the time it looks.
# ---------------------------------------------------------------------------

locals {
  aggregator_enabled = var.enable_aggregator ? 1 : 0
  aggregator_name    = "${var.project_name}-aggregate"
}

# A workgroup of its own, because querying a requester-pays bucket needs one.
# This is the setting that otherwise fails with an error never mentioning
# requester pays.
resource "aws_athena_workgroup" "aggregate" {
  count = local.aggregator_enabled
  name  = local.aggregator_name
  tags  = local.tags

  configuration {
    requester_pays_enabled             = true
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results[0].id}/results/"
    }
  }

  force_destroy = true
}

# Query results are working files, not site content. They get their own private
# bucket and are deleted on a timer — putting them in the bucket that serves the
# public site would publish every query you ever run.
resource "aws_s3_bucket" "athena_results" {
  count         = local.aggregator_enabled
  bucket        = "${var.project_name}-athena-results"
  force_destroy = true
  tags          = local.tags
}

resource "aws_s3_bucket_public_access_block" "athena_results" {
  count                   = local.aggregator_enabled
  bucket                  = aws_s3_bucket.athena_results[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "athena_results" {
  count  = local.aggregator_enabled
  bucket = aws_s3_bucket.athena_results[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "athena_results" {
  count  = local.aggregator_enabled
  bucket = aws_s3_bucket.athena_results[0].id

  rule {
    id     = "expire-results"
    status = "Enabled"

    filter {}

    expiration {
      days = var.athena_results_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# ---------------------------------------------------------------------------
# Package
#
# boto3 ships in the Lambda runtime, so there is nothing to vendor — the zip is
# the job plus its lookups plus the SQL it runs.
# ---------------------------------------------------------------------------

data "archive_file" "aggregate" {
  count       = local.aggregator_enabled
  type        = "zip"
  output_path = "${path.module}/.build/${local.aggregator_name}.zip"

  dynamic "source" {
    for_each = fileset("${path.module}/../site/aggregate", "*.{py,json}")
    content {
      content  = file("${path.module}/../site/aggregate/${source.value}")
      filename = source.value
    }
  }

  dynamic "source" {
    for_each = fileset("${path.module}/../queries", "*.sql")
    content {
      content  = file("${path.module}/../queries/${source.value}")
      filename = "queries/${source.value}"
    }
  }
}

resource "aws_lambda_function" "aggregate" {
  count            = local.aggregator_enabled
  function_name    = local.aggregator_name
  description      = "Builds the passenger-hours dashboard JSON from Athena"
  role             = aws_iam_role.aggregate[0].arn
  handler          = "aggregate.handler"
  runtime          = "python3.12"
  timeout          = 300
  memory_size      = 512
  filename         = data.archive_file.aggregate[0].output_path
  source_code_hash = data.archive_file.aggregate[0].output_base64sha256
  tags             = local.tags

  environment {
    variables = {
      ATHENA_DATABASE  = var.athena_database
      ATHENA_WORKGROUP = aws_athena_workgroup.aggregate[0].name
      OUTPUT_LOCATION  = "s3://${aws_s3_bucket.site.id}/data"
    }
  }
}

resource "aws_cloudwatch_log_group" "aggregate" {
  count             = local.aggregator_enabled
  name              = "/aws/lambda/${local.aggregator_name}"
  retention_in_days = 30
  tags              = local.tags
}

# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "aggregate_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "aggregate" {
  count              = local.aggregator_enabled
  name               = "${local.aggregator_name}-role"
  assume_role_policy = data.aws_iam_policy_document.aggregate_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "aggregate" {
  count = local.aggregator_enabled

  statement {
    sid = "Athena"
    actions = [
      "athena:StartQueryExecution",
      "athena:StopQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:GetWorkGroup",
    ]
    resources = [aws_athena_workgroup.aggregate[0].arn]
  }

  # Athena resolves table metadata through the Glue catalog.
  statement {
    sid = "GlueCatalog"
    actions = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable",
    "glue:GetTables", "glue:GetPartition", "glue:GetPartitions"]
    resources = ["*"]
  }

  # The dataset itself. Requester pays governs who is billed, not who is
  # allowed, so these permissions are still required.
  statement {
    sid     = "ReadDataset"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${var.dataset_bucket}",
      "arn:aws:s3:::${var.dataset_bucket}/*",
    ]
  }

  statement {
    sid = "AthenaResults"
    actions = ["s3:GetObject", "s3:PutObject", "s3:ListBucket",
    "s3:GetBucketLocation", "s3:AbortMultipartUpload"]
    resources = [
      aws_s3_bucket.athena_results[0].arn,
      "${aws_s3_bucket.athena_results[0].arn}/*",
    ]
  }

  # Only the dashboard's own data files, not the whole site.
  statement {
    sid       = "WriteSiteData"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.site.arn}/data/*"]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.aggregate[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "aggregate" {
  count  = local.aggregator_enabled
  name   = "${local.aggregator_name}-policy"
  role   = aws_iam_role.aggregate[0].id
  policy = data.aws_iam_policy_document.aggregate[0].json
}

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "aggregate" {
  count               = local.aggregator_enabled
  name                = local.aggregator_name
  description         = "Rebuild the passenger-hours dashboard for yesterday"
  schedule_expression = var.aggregate_schedule
  tags                = local.tags
}

resource "aws_cloudwatch_event_target" "aggregate" {
  count     = local.aggregator_enabled
  rule      = aws_cloudwatch_event_rule.aggregate[0].name
  target_id = "lambda"
  arn       = aws_lambda_function.aggregate[0].arn
}

resource "aws_lambda_permission" "aggregate" {
  count         = local.aggregator_enabled
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.aggregate[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.aggregate[0].arn
}
