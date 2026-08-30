terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# CloudFront certificates must live in us-east-1, whatever region the rest of
# the stack is in.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}
