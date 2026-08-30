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
  description = "Copy-paste to publish the site."
  value       = "aws s3 sync ../site/ s3://${aws_s3_bucket.site.id}/ --delete"
}
