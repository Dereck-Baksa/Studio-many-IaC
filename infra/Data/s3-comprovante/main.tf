
provider "aws" {
  region = "us-east-1" 
}

resource "aws_s3_bucket" "s3_comprovante" {
  bucket = "s3-comprovante-${random_string.sufixo.result}"
  force_destroy = true
  description = "s3 reserved to comprovante"

 
  tags = {
    Name = ""
  }
}

