output "bucket_name" {
  description = "Upload the contents of ../site/ here."
  value       = aws_s3_bucket.site.id
}

output "distribution_id" {
  description = "CloudFront distribution id, for invalidations."
  value       = aws_cloudfront_distribution.site.id
}

output "site_url" {
  description = "Where the dashboard is served."
  value       = var.domain_name != "" ? "https://${var.domain_name}" : "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "deploy_command" {
  description = "Copy-paste to publish the site. Use deploy.sh rather than a bare sync: it substitutes the basemap key, which is deliberately not in the repository."
  value       = "CARTO_KEY=your_key ../deploy.sh"
}

output "aggregate_function_name" {
  description = "Invoke manually with: aws lambda invoke --function-name <this> --payload '{\"date\":\"2026-05-16\"}' out.json"
  value       = var.enable_aggregator ? aws_lambda_function.aggregate[0].function_name : null
}

output "athena_workgroup" {
  description = "Workgroup with requester-pays enabled. Use it for your own queries too."
  value       = var.enable_aggregator ? aws_athena_workgroup.aggregate[0].name : null
}

output "tracks_function_name" {
  description = "Invoke manually with: aws lambda invoke --function-name <this> --payload '{\"date\":\"2026-09-04\"}' out.json"
  value       = var.enable_tracks && var.enable_aggregator ? aws_lambda_function.tracks[0].function_name : null
}
