
provider "aws" {
  region = var.region
}

resource "aws_s3_bucket" "s3_comprovante" {
  bucket = var.bucket_name
  force_destroy = true
  description = "s3 reserved to comprovante"

resource "aws_s3_object" "pendentes" {
  bucket = aws_s3_bucket.s3_comprovante.id
  key    = var.key         
  source = "/dev/null"         
}

resource "aws_s3_object" "aprovados" {
  bucket = aws_s3_bucket.s3_comprovante.id
  key    = "aprovados/"          
  source = "/dev/null"         
}
 
  tags = {
    Name = ""
  }
}

