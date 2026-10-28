provider "aws" {
  region = var.region
}

resource "aws_s3_bucket" "bronze" {
  bucket = "s3-bronze-${var.bucket_suffix}"
}

resource "aws_s3_bucket" "silver" {
  bucket = "s3-silver-${var.bucket_suffix}"
}

resource "aws_s3_bucket" "gold" {
  bucket = "s3-gold-${var.bucket_suffix}"
}
