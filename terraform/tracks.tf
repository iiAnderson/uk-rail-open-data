# ---------------------------------------------------------------------------
# The daily track-section map job.
#
# A second Lambda rather than more work inside the first. It reads a different
# query, holds a cache of its own, and takes longer — folding it into the
# passenger-hours job would mean one failure taking down both pages, and one
# timeout sized for the slower of the two.
#
# It reuses the aggregator's workgroup and results bucket. Those exist to make
# requester-pays querying work at all, and there is nothing job-specific about
# them.
# ---------------------------------------------------------------------------

locals {
  tracks_enabled = var.enable_tracks && var.enable_aggregator ? 1 : 0
  tracks_name    = "${var.project_name}-tracks"
}

# ---------------------------------------------------------------------------
# Package
#
# The reference data ships inside the zip. It is the physical network — track
# geometry and the station codes on it — which changes on the timescale of the
# railway, not the timetable, so baking it in is simpler than a lookup at
# runtime and removes a failure mode.
# ---------------------------------------------------------------------------

data "archive_file" "tracks" {
  count       = local.tracks_enabled
  type        = "zip"
  output_path = "${path.module}/.build/${local.tracks_name}.zip"

  dynamic "source" {
    for_each = fileset("${path.module}/../tracks", "*.py")
    content {
      content  = file("${path.module}/../tracks/${source.value}")
      filename = source.value
    }
  }

  dynamic "source" {
    for_each = fileset("${path.module}/../tracks/reference", "*.json")
    content {
      content  = file("${path.module}/../tracks/reference/${source.value}")
      filename = "reference/${source.value}"
    }
  }

  dynamic "source" {
    for_each = fileset("${path.module}/../common", "*.py")
    content {
      content  = file("${path.module}/../common/${source.value}")
      filename = "common/${source.value}"
    }
  }

  source {
    content  = file("${path.module}/../queries/tracks_routes.sql")
    filename = "queries/tracks_routes.sql"
  }
}

resource "aws_lambda_function" "tracks" {
  count         = local.tracks_enabled
  function_name = local.tracks_name
  description   = "Builds the track-section map JSON from Athena"
  role          = aws_iam_role.tracks[0].arn
  handler       = "tracks.handler"
  runtime       = "python3.12"
  # Attribution runs in Python, and a day whose routes are mostly new — the
  # first run after a timetable change — does far more of it than a usual one.
  timeout          = 600
  memory_size      = 1024
  filename         = data.archive_file.tracks[0].output_path
  source_code_hash = data.archive_file.tracks[0].output_base64sha256
  tags             = local.tags

  environment {
    variables = {
      ATHENA_DATABASE  = var.athena_database
      ATHENA_WORKGROUP = aws_athena_workgroup.aggregate[0].name
      OUTPUT_LOCATION  = "s3://${aws_s3_bucket.site.id}/data/tracks"
      STATE_LOCATION   = "s3://${aws_s3_bucket.athena_results[0].id}/state"
    }
  }
}

resource "aws_cloudwatch_log_group" "tracks" {
  count             = local.tracks_enabled
  name              = "/aws/lambda/${local.tracks_name}"
  retention_in_days = 30
  tags              = local.tags
}

# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

resource "aws_iam_role" "tracks" {
  count              = local.tracks_enabled
  name               = "${local.tracks_name}-role"
  assume_role_policy = data.aws_iam_policy_document.aggregate_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "tracks" {
  count = local.tracks_enabled

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

  statement {
    sid = "GlueCatalog"
    actions = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable",
    "glue:GetTables", "glue:GetPartition", "glue:GetPartitions"]
    resources = ["*"]
  }

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

  # Only the map's own data, not the rest of the site. Delete is here because
  # retention is part of the job: a day rolled into its month is removed.
  statement {
    sid       = "WriteMapData"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.site.arn}/data/tracks/*"]
  }

  # Listing is a bucket-level action, so it is scoped by prefix instead.
  statement {
    sid       = "ListMapData"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.site.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["data/tracks/*"]
    }
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.tracks[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "tracks" {
  count  = local.tracks_enabled
  name   = "${local.tracks_name}-policy"
  role   = aws_iam_role.tracks[0].id
  policy = data.aws_iam_policy_document.tracks[0].json
}

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "tracks" {
  count               = local.tracks_enabled
  name                = local.tracks_name
  description         = "Rebuild the track-section map for yesterday"
  schedule_expression = var.tracks_schedule
  tags                = local.tags
}

resource "aws_cloudwatch_event_target" "tracks" {
  count     = local.tracks_enabled
  rule      = aws_cloudwatch_event_rule.tracks[0].name
  target_id = "lambda"
  arn       = aws_lambda_function.tracks[0].arn
}

resource "aws_lambda_permission" "tracks" {
  count         = local.tracks_enabled
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tracks[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.tracks[0].arn
}
