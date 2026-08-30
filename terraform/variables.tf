variable "project_name" {
  description = "Name prefix for created resources. Also used for the S3 bucket, so it must be globally unique."
  type        = string
  default     = "uk-rail-dashboard"
}

variable "region" {
  description = "Region for the S3 bucket. Keep it close to where the aggregation job runs."
  type        = string
  default     = "eu-west-1"
}

variable "domain_name" {
  description = "Custom domain for the site, e.g. rail.example.com. Leave empty to use the CloudFront domain instead."
  type        = string
  default     = ""
}

variable "acm_certificate_arn" {
  description = "ARN of an ACM certificate in us-east-1 covering domain_name. Required only when domain_name is set."
  type        = string
  default     = ""
}

variable "price_class" {
  description = "CloudFront price class. PriceClass_100 is North America and Europe only, and is the cheapest."
  type        = string
  default     = "PriceClass_100"

  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.price_class)
    error_message = "price_class must be PriceClass_100, PriceClass_200 or PriceClass_All."
  }
}

variable "data_cache_seconds" {
  description = "How long CloudFront caches files under /data/. The aggregation job writes these once a day, so a short TTL means updates appear without paying for invalidations."
  type        = number
  default     = 300
}

variable "default_cache_seconds" {
  description = "How long CloudFront caches everything else."
  type        = number
  default     = 3600
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
